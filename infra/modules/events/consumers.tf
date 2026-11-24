# Sale-events consumers (Day 8 Task 3; blueprint "Sale events"): Lambda consumers of the Kinesis
# stream, in order per shard, checkpoint by sequence number (ReportBatchItemFailures), bisect a
# failing batch, 3 retries / 1 h max age, then the on-failure SQS destination (+ alarm).
#
#   live-dashboard : counters in DynamoDB (deduped by message id) -> WebSocket push to organisers
#
# The event-source mappings follow the stream (make up / make down); Lambdas, tables, the
# WebSocket API and queues are pay per use and persistent. Nothing hourly.

data "archive_file" "consumers" {
  type             = "zip"
  source_dir       = var.consumers_source_dir
  output_path      = "${path.module}/.build/sg_consumers.zip"
  output_file_mode = "0644"
  excludes         = ["**/__pycache__/**", "**/*.pyc"]
}

# --- Live counters + WebSocket connections (one table) ---------------------------------------
resource "aws_dynamodb_table" "stats" {
  name         = "${var.name}-sale-stats"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "PK"
  range_key    = "SK"

  attribute {
    name = "PK"
    type = "S"
  }
  attribute {
    name = "SK"
    type = "S"
  }

  ttl {
    attribute_name = "expires" # dedupe markers (24 h) and connections (2 h)
    enabled        = true
  }

  server_side_encryption {
    enabled = true
  }

  tags = local.tags
}

# --- Live-token key (booking API issues, the WebSocket authorizer verifies) -------------------
resource "random_password" "live_key" {
  length  = 48
  special = false
}

resource "aws_secretsmanager_secret" "live_key" {
  name                    = "${var.secrets_prefix}/events/live-key"
  description             = "HMAC key for 60-second live-dashboard WebSocket tokens {kid, key} (Terraform-generated)."
  recovery_window_in_days = 7
  tags                    = local.tags
}

resource "aws_secretsmanager_secret_version" "live_key" {
  secret_id     = aws_secretsmanager_secret.live_key.id
  secret_string = jsonencode({ kid = "l1", key = random_password.live_key.result })
}

# --- Failed records (on-failure destination) + alarm ------------------------------------------
resource "aws_sqs_queue" "consumers_failed" {
  name                      = "${var.name}-consumers-failed"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
  tags                      = local.tags
}

resource "aws_cloudwatch_metric_alarm" "consumers_failed" {
  alarm_name          = "${var.name}-consumers-failed-not-empty"
  alarm_description   = "A sale-events consumer gave up on a batch (pointer to the shard range is in the queue). Inspect, fix, re-read."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = aws_sqs_queue.consumers_failed.name }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [var.alerts_topic_arn]
  ok_actions          = [var.alerts_topic_arn]
  tags                = local.tags
}

# --- Lambdas: live-dashboard consumer, WebSocket handler, WebSocket authorizer ---------------
locals {
  consumer_functions = {
    live-dashboard = { handler = "sg_consumers.live_dashboard.handler", timeout = 30 }
    ws             = { handler = "sg_consumers.ws.handler", timeout = 10 }
    ws-authorizer  = { handler = "sg_consumers.ws.authorizer", timeout = 5 }
  }
  ws_stage = "live"
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

resource "aws_iam_role" "consumer" {
  for_each           = local.consumer_functions
  name               = "${var.name}-events-${each.key}"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
  tags               = local.tags
}

resource "aws_cloudwatch_log_group" "consumer" {
  for_each          = local.consumer_functions
  name              = "/aws/lambda/${var.name}-events-${each.key}"
  retention_in_days = var.log_retention_days
  tags              = local.tags
}

data "aws_iam_policy_document" "consumer" {
  for_each = local.consumer_functions

  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.consumer[each.key].arn}:*"]
  }

  dynamic "statement" {
    for_each = each.key == "live-dashboard" ? [1] : []
    content {
      sid = "ReadSaleEvents"
      actions = [
        "kinesis:GetRecords", "kinesis:GetShardIterator", "kinesis:DescribeStream",
        "kinesis:DescribeStreamSummary", "kinesis:ListShards", "kinesis:ListStreams",
      ]
      resources = [local.stream_arn]
    }
  }

  dynamic "statement" {
    for_each = each.key == "live-dashboard" ? [1] : []
    content {
      sid       = "OnFailureDestination"
      actions   = ["sqs:SendMessage"]
      resources = [aws_sqs_queue.consumers_failed.arn]
    }
  }

  dynamic "statement" {
    for_each = each.key == "ws-authorizer" ? [] : [1]
    content {
      sid = "CountersAndConnections"
      actions = [
        "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem",
        "dynamodb:Query", "dynamodb:ConditionCheckItem",
      ]
      resources = [aws_dynamodb_table.stats.arn]
    }
  }

  dynamic "statement" {
    for_each = each.key == "ws-authorizer" ? [] : [1]
    content {
      sid       = "WaitingRoomStatus"
      actions   = ["dynamodb:GetItem"]
      resources = [var.queue_table_arn]
    }
  }

  dynamic "statement" {
    for_each = each.key == "ws-authorizer" ? [] : [1]
    content {
      sid       = "PushToConnections"
      actions   = ["execute-api:ManageConnections"]
      resources = ["${aws_apigatewayv2_api.live.execution_arn}/${local.ws_stage}/POST/@connections/*"]
    }
  }

  dynamic "statement" {
    for_each = each.key == "ws-authorizer" ? [1] : []
    content {
      sid       = "ReadLiveKey"
      actions   = ["secretsmanager:GetSecretValue"]
      resources = [aws_secretsmanager_secret.live_key.arn]
    }
  }
}

resource "aws_iam_role_policy" "consumer" {
  for_each = local.consumer_functions
  name     = "events-${each.key}"
  role     = aws_iam_role.consumer[each.key].id
  policy   = data.aws_iam_policy_document.consumer[each.key].json
}

resource "aws_lambda_function" "consumer" {
  for_each         = local.consumer_functions
  function_name    = "${var.name}-events-${each.key}"
  role             = aws_iam_role.consumer[each.key].arn
  runtime          = "python3.12"
  architectures    = ["arm64"]
  handler          = each.value.handler
  filename         = data.archive_file.consumers.output_path
  source_code_hash = data.archive_file.consumers.output_base64sha256
  timeout          = each.value.timeout
  memory_size      = 256

  environment {
    variables = {
      STATS_TABLE        = aws_dynamodb_table.stats.name
      QUEUE_TABLE        = var.queue_table_name
      WS_ENDPOINT        = "https://${aws_apigatewayv2_api.live.id}.execute-api.${local.region}.amazonaws.com/${local.ws_stage}"
      LIVE_KEY_SECRET_ID = aws_secretsmanager_secret.live_key.arn
    }
  }

  logging_config {
    log_format = "JSON"
    log_group  = aws_cloudwatch_log_group.consumer[each.key].name
  }

  tags       = local.tags
  depends_on = [aws_iam_role_policy.consumer]
}

resource "aws_lambda_event_source_mapping" "live_dashboard" {
  count                              = local.stream
  event_source_arn                   = aws_kinesis_stream.this[0].arn
  function_name                      = aws_lambda_function.consumer["live-dashboard"].arn
  starting_position                  = "LATEST"
  batch_size                         = 100
  maximum_batching_window_in_seconds = 0 # live: no waiting to fill a batch
  parallelization_factor             = 1 # in order per shard
  bisect_batch_on_function_error     = true
  maximum_retry_attempts             = 3
  maximum_record_age_in_seconds      = 3600
  function_response_types            = ["ReportBatchItemFailures"]

  destination_config {
    on_failure {
      destination_arn = aws_sqs_queue.consumers_failed.arn
    }
  }

  tags = local.tags
}

# --- WebSocket API: wss://<id>.execute-api.<region>.amazonaws.com/live?token=... -------------
resource "aws_apigatewayv2_api" "live" {
  name                       = "${var.name}-live"
  description                = "Organiser live dashboard (Day 8 Task 3)"
  protocol_type              = "WEBSOCKET"
  route_selection_expression = "$request.body.action"
  tags                       = local.tags
}

resource "aws_apigatewayv2_authorizer" "live" {
  api_id           = aws_apigatewayv2_api.live.id
  name             = "live-token"
  authorizer_type  = "REQUEST"
  authorizer_uri   = aws_lambda_function.consumer["ws-authorizer"].invoke_arn
  identity_sources = ["route.request.querystring.token"]
}

resource "aws_apigatewayv2_integration" "ws" {
  api_id             = aws_apigatewayv2_api.live.id
  integration_type   = "AWS_PROXY"
  integration_uri    = aws_lambda_function.consumer["ws"].invoke_arn
  integration_method = "POST"
}

resource "aws_apigatewayv2_route" "connect" {
  api_id             = aws_apigatewayv2_api.live.id
  route_key          = "$connect"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.live.id
  target             = "integrations/${aws_apigatewayv2_integration.ws.id}"
}

resource "aws_apigatewayv2_route" "other" {
  for_each  = toset(["$disconnect", "snapshot"])
  api_id    = aws_apigatewayv2_api.live.id
  route_key = each.value
  target    = "integrations/${aws_apigatewayv2_integration.ws.id}"
}

resource "aws_apigatewayv2_stage" "live" {
  api_id      = aws_apigatewayv2_api.live.id
  name        = local.ws_stage
  auto_deploy = true

  default_route_settings {
    throttling_burst_limit = 100
    throttling_rate_limit  = 50
  }

  tags = local.tags
}

resource "aws_lambda_permission" "ws" {
  for_each      = toset(["ws", "ws-authorizer"])
  statement_id  = "AllowApiGatewayWebSocket"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.consumer[each.key].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.live.execution_arn}/*"
}
