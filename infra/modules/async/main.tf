# Background work (plan layout: "async/ Step Functions, payment and ticket workers, SES").
#
# Hold timer (Day 7): the booking API starts one Standard execution per hold, named by the
# hold id:   Wait (wait_seconds, default 600) -> Release (Lambda in the VPC, conditional UPDATE)
# Payment intake (Day 7 Task 4): webhook endpoint -> SQS payments -> order worker (EKS pod);
# 5 failed receives -> DLQ -> CloudWatch alarm -> SNS (email).
# Pay per use: about $0.025 per 1,000 state transitions; SQS requests (free tier);
# one alarm ($0.10/month). Nothing hourly.

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  tags            = merge(var.tags, { Component = "async" })
  account         = data.aws_caller_identity.current.account_id
  region          = data.aws_region.current.region
  db_instance_arn = "arn:aws:rds:${local.region}:${local.account}:db:${var.db_instance_id}"
}

data "archive_file" "workers" {
  type             = "zip"
  source_dir       = var.source_dir
  output_path      = "${path.module}/.build/sg_workers.zip"
  output_file_mode = "0644"
  excludes         = ["**/__pycache__/**", "**/*.pyc"]
}

# --- Release Lambda (in the VPC, next to the database) -------------------------------------
resource "aws_security_group" "release" {
  name        = "${var.name}-hold-release"
  description = "Hold-release Lambda: outbound to PostgreSQL and AWS APIs"
  vpc_id      = var.vpc_id
  tags        = merge(local.tags, { Name = "${var.name}-hold-release" })
}

resource "aws_vpc_security_group_egress_rule" "release_all" {
  security_group_id = aws_security_group.release.id
  description       = "PostgreSQL in the VPC; AWS APIs via NAT / endpoints"
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

data "aws_iam_policy_document" "lambda_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "release" {
  name               = "${var.name}-hold-release"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
  tags               = local.tags
}

resource "aws_iam_role_policy_attachment" "release_vpc" {
  role       = aws_iam_role.release.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_cloudwatch_log_group" "release" {
  name              = "/aws/lambda/${var.name}-hold-release"
  retention_in_days = var.log_retention_days
  tags              = local.tags
}

data "aws_iam_policy_document" "release" {
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.release.arn}:*"]
  }
  statement {
    sid       = "DescribeOwnDatabase"
    actions   = ["rds:DescribeDBInstances"]
    resources = [local.db_instance_arn]
  }
  statement {
    sid       = "ReadOwnDatabaseSecret"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = ["arn:aws:secretsmanager:${local.region}:${local.account}:secret:rds!db-*"]
    condition {
      test     = "StringEquals"
      variable = "secretsmanager:ResourceTag/aws:rds:primaryDBInstanceArn"
      values   = [local.db_instance_arn]
    }
  }
  statement {
    sid       = "DecryptSecretsViaSecretsManager"
    actions   = ["kms:Decrypt"]
    resources = [var.kms_key_arn]
    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["secretsmanager.${local.region}.amazonaws.com"]
    }
  }
  statement {
    sid       = "PublishSaleEvents"
    actions   = ["kinesis:PutRecord"]
    resources = [var.sale_events_arn]
  }
}

resource "aws_iam_role_policy" "release" {
  name   = "hold-release"
  role   = aws_iam_role.release.id
  policy = data.aws_iam_policy_document.release.json
}

resource "aws_lambda_function" "release" {
  function_name    = "${var.name}-hold-release"
  description      = "Hold timer: release seats still held by this hold (never sold ones)"
  role             = aws_iam_role.release.arn
  runtime          = "python3.12"
  architectures    = ["arm64"]
  handler          = "sg_workers.release_hold.handler"
  filename         = data.archive_file.workers.output_path
  source_code_hash = data.archive_file.workers.output_base64sha256
  timeout          = 30
  memory_size      = 256

  vpc_config {
    subnet_ids         = var.private_subnet_ids
    security_group_ids = [aws_security_group.release.id]
  }

  environment {
    variables = {
      DB_INSTANCE_ID     = var.db_instance_id
      SALE_EVENTS_STREAM = var.sale_events_stream
    }
  }

  logging_config {
    log_format = "JSON"
    log_group  = aws_cloudwatch_log_group.release.name
  }

  tags = local.tags
  depends_on = [
    aws_iam_role_policy.release,
    aws_iam_role_policy_attachment.release_vpc,
  ]
}

# --- State machine ----------------------------------------------------------------------
data "aws_iam_policy_document" "sfn_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account]
    }
  }
}

resource "aws_iam_role" "sfn" {
  name               = "${var.name}-hold-timer"
  assume_role_policy = data.aws_iam_policy_document.sfn_trust.json
  tags               = local.tags
}

data "aws_iam_policy_document" "sfn" {
  statement {
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.release.arn, "${aws_lambda_function.release.arn}:*"]
  }
}

resource "aws_iam_role_policy" "sfn" {
  name   = "invoke-release"
  role   = aws_iam_role.sfn.id
  policy = data.aws_iam_policy_document.sfn.json
}

resource "aws_sfn_state_machine" "hold_timer" {
  name     = "${var.name}-hold-timer"
  type     = "STANDARD" # waits of 10 minutes; one execution per hold, named by the hold id
  role_arn = aws_iam_role.sfn.arn

  definition = jsonencode({
    Comment = "Release a hold's seats after the hold time, only if still held by that hold"
    StartAt = "Wait"
    States = {
      Wait = {
        Type        = "Wait"
        SecondsPath = "$.wait_seconds"
        Next        = "Release"
      }
      Release = {
        Type       = "Task"
        Resource   = "arn:aws:states:::lambda:invoke"
        Parameters = { FunctionName = aws_lambda_function.release.arn, "Payload.$" = "$" }
        OutputPath = "$.Payload"
        Retry = [{
          ErrorEquals     = ["States.ALL"]
          IntervalSeconds = 10
          MaxAttempts     = 6
          BackoffRate     = 2
        }]
        End = true
      }
    }
  })

  tags = local.tags
}

# --- Payment intake: SQS + DLQ ---------------------------------------------------------------
resource "aws_sqs_queue" "payments_dlq" {
  name                      = "${var.name}-payments-dlq"
  message_retention_seconds = 1209600 # 14 days to inspect and replay
  sqs_managed_sse_enabled   = true
  tags                      = local.tags
}

resource "aws_sqs_queue" "payments" {
  name                       = "${var.name}-payments"
  visibility_timeout_seconds = var.payments_visibility_timeout # > worst-case worker time (~15 s)
  receive_wait_time_seconds  = 20                              # long polling
  message_retention_seconds  = 345600                          # 4 days
  sqs_managed_sse_enabled    = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.payments_dlq.arn
    maxReceiveCount     = var.payments_max_receive_count
  })

  tags = local.tags
}

resource "aws_sqs_queue_redrive_allow_policy" "payments_dlq" {
  queue_url = aws_sqs_queue.payments_dlq.id
  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns   = [aws_sqs_queue.payments.arn]
  })
}

# --- Alerts: DLQ not empty -> SNS -> email -----------------------------------------------------
resource "aws_sns_topic" "alerts" {
  name = "${var.name}-alerts"
  # No KMS: CloudWatch alarms can't publish to a topic encrypted with the AWS-managed SNS key,
  # and alerts carry no secrets.
  tags = local.tags
}

# The address is NOT in Git: it comes from an uncommitted *.auto.tfvars (or TF_VAR_alert_email).
# The committed flag keeps the subscription in place when a plan runs without the address (CI).
resource "aws_sns_topic_subscription" "alerts_email" {
  count     = var.alert_email_enabled ? 1 : 0
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email

  lifecycle {
    ignore_changes = [endpoint]
  }
}

resource "aws_cloudwatch_metric_alarm" "payments_dlq" {
  alarm_name          = "${var.name}-payments-dlq-not-empty"
  alarm_description   = "A payment webhook failed 5 times and is in the DLQ: a paid order may be unconfirmed. Inspect, fix, then redrive."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = aws_sqs_queue.payments_dlq.name }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
  tags                = local.tags
}
