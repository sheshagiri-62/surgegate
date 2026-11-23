# Sale-events stream (ADR 002): Kinesis Data Streams + EventBridge custom bus.
#
#   producers (queue Lambdas, booking API) --PutRecord, partition key = sale event id-->
#     Kinesis "sale-events"  (ordered per sale, replayable for 24 h; consumers: Day 8)
#       --EventBridge Pipe--> custom bus "sale-events" --> archive (7-day replay)
#                                                     \-> rule -> log group (debug / audit trail)
#
# Hourly cost: only the Kinesis shard (and the Pipe, which follows it): created by make up,
# destroyed by make down (stream_enabled). The bus, archive, rule and log group are pay-per-use
# and persistent.

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  tags    = merge(var.tags, { Component = "events" })
  stream  = var.stream_enabled ? 1 : 0
  name    = "${var.name}-sale-events"
  account = data.aws_caller_identity.current.account_id
  region  = data.aws_region.current.region
  # Known even while the stream does not exist, so producers' IAM policies never change.
  stream_arn = "arn:aws:kinesis:${local.region}:${local.account}:stream/${local.name}"
}

# --- Kinesis (hourly, sessions only) -------------------------------------------------------
resource "aws_kinesis_stream" "this" {
  count            = local.stream
  name             = local.name
  retention_period = 24
  encryption_type  = "KMS"
  kms_key_id       = "alias/aws/kinesis"

  stream_mode_details {
    stream_mode = "PROVISIONED"
  }
  shard_count = var.shard_count # dev: 1 shard ($0.0175/h); demo: on-demand or more shards (ADR 002)

  tags = local.tags
}

# --- EventBridge bus (persistent, pay per event) --------------------------------------------
resource "aws_cloudwatch_event_bus" "this" {
  name = local.name
  tags = local.tags
}

resource "aws_cloudwatch_event_archive" "this" {
  name             = local.name
  event_source_arn = aws_cloudwatch_event_bus.this.arn
  retention_days   = var.archive_days
  description      = "Replay of sale events (Kinesis keeps only 24 h)"
}

resource "aws_cloudwatch_log_group" "events" {
  # EventBridge requires log groups for rule targets to start with /aws/events/.
  name              = "/aws/events/${local.name}"
  retention_in_days = var.log_retention_days
  tags              = local.tags
}

data "aws_iam_policy_document" "events_to_logs" {
  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.events.arn}:*"]
    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com", "delivery.logs.amazonaws.com"]
    }
  }
}

resource "aws_cloudwatch_log_resource_policy" "events_to_logs" {
  policy_name     = "${local.name}-to-logs"
  policy_document = data.aws_iam_policy_document.events_to_logs.json
}

resource "aws_cloudwatch_event_rule" "all" {
  name           = "${local.name}-all"
  description    = "Every sale event -> log group (debugging, audit trail)"
  event_bus_name = aws_cloudwatch_event_bus.this.name
  event_pattern  = jsonencode({ source = ["surgegate.sale-events"] })
  tags           = local.tags
}

resource "aws_cloudwatch_event_target" "logs" {
  rule           = aws_cloudwatch_event_rule.all.name
  event_bus_name = aws_cloudwatch_event_bus.this.name
  target_id      = "logs"
  arn            = aws_cloudwatch_log_group.events.arn
  depends_on     = [aws_cloudwatch_log_resource_policy.events_to_logs]
}

# --- Pipe: Kinesis -> bus (follows the stream) -----------------------------------------------
data "aws_iam_policy_document" "pipe_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["pipes.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account]
    }
  }
}

resource "aws_iam_role" "pipe" {
  count              = local.stream
  name               = "${local.name}-pipe"
  assume_role_policy = data.aws_iam_policy_document.pipe_trust.json
  tags               = local.tags
}

data "aws_iam_policy_document" "pipe" {
  statement {
    sid = "ReadStream"
    actions = [
      "kinesis:DescribeStream", "kinesis:DescribeStreamSummary", "kinesis:GetRecords",
      "kinesis:GetShardIterator", "kinesis:ListShards", "kinesis:ListStreams",
    ]
    resources = [local.stream_arn]
  }
  statement {
    sid       = "PutOnBus"
    actions   = ["events:PutEvents"]
    resources = [aws_cloudwatch_event_bus.this.arn]
  }
  statement {
    sid       = "PipeErrorLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.pipe.arn}:*"]
  }
}

# Pipe errors (why a batch failed), with the failing record, kept 7 days.
resource "aws_cloudwatch_log_group" "pipe" {
  name              = "/aws/vendedlogs/pipes/${local.name}-to-bus"
  retention_in_days = var.log_retention_days
  tags              = local.tags
}

resource "aws_iam_role_policy" "pipe" {
  count  = local.stream
  name   = "pipe"
  role   = aws_iam_role.pipe[0].id
  policy = data.aws_iam_policy_document.pipe.json
}

resource "aws_pipes_pipe" "stream_to_bus" {
  count    = local.stream
  name     = "${local.name}-to-bus"
  role_arn = aws_iam_role.pipe[0].arn
  source   = aws_kinesis_stream.this[0].arn
  target   = aws_cloudwatch_event_bus.this.arn

  log_configuration {
    level                  = "ERROR"
    include_execution_data = ["ALL"]
    cloudwatch_logs_log_destination {
      log_group_arn = aws_cloudwatch_log_group.pipe.arn
    }
  }

  source_parameters {
    kinesis_stream_parameters {
      starting_position                  = "LATEST"
      batch_size                         = 10
      maximum_batching_window_in_seconds = 1
      maximum_retry_attempts             = 3
    }
  }

  target_parameters {
    # The event detail = our envelope, built field by field as a JSON object (a bare "<$.data>"
    # template produced unquoted, non-JSON text and EventBridge rejected every entry with
    # BadRequest), plus the Kinesis sequence number for ordering / de-duplication.
    # The detail-type is fixed; rules and consumers route on detail.type ("joined", ...).
    input_template = <<-EOT
      {"id": <$.data.id>, "type": <$.data.type>, "sale_event_id": <$.data.sale_event_id>, "at": <$.data.at>, "data": <$.data.data>, "kinesis_sequence": <$.sequenceNumber>}
    EOT
    eventbridge_event_bus_parameters {
      source      = "surgegate.sale-events"
      detail_type = "sale-event"
    }
  }

  tags       = local.tags
  depends_on = [aws_iam_role_policy.pipe]
}
