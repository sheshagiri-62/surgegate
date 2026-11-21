# Waiting room (blueprint "Front of house"): API Gateway HTTP API + Lambda + SQS + DynamoDB.
# Everything here is pay-per-request (no hourly cost) and persistent; make down leaves it.
#
#   POST /queue/{event}/join  -> join Lambda -> SQS joins -> sequencer Lambda -> DynamoDB


locals {
  tags = merge(var.tags, { Component = "queue" })
  # One zip with the whole sg_queue package; each function uses its own handler.
  functions = {
    join = {
      handler = "sg_queue.join.handler"
      timeout = 10
      memory  = 256
    }
    sequencer = {
      handler = "sg_queue.sequencer.handler"
      timeout = 30
      memory  = 256
    }
    starter = {
      handler = "sg_queue.starter.handler"
      timeout = 60
      memory  = 256
    }
    position = {
      handler = "sg_queue.position.handler"
      timeout = 10
      memory  = 256
    }
  }
  # Functions behind API Gateway routes.
  routes = {
    join     = "POST /queue/{event}/join"
    position = "GET /queue/{event}/position"
  }
}

data "archive_file" "code" {
  type             = "zip"
  source_dir       = var.source_dir
  output_path      = "${path.module}/.build/sg_queue.zip"
  output_file_mode = "0644" # same zip on Windows and in CI
  excludes         = ["**/__pycache__/**", "**/*.pyc"]
}

# --- SQS: joins + dead-letter queue ------------------------------------------------
resource "aws_sqs_queue" "joins_dlq" {
  name                      = "${var.name}-joins-dlq"
  message_retention_seconds = 1209600 # 14 days to inspect failures
  sqs_managed_sse_enabled   = true
  tags                      = local.tags
}

resource "aws_sqs_queue" "joins" {
  name                       = "${var.name}-joins"
  visibility_timeout_seconds = 6 * local.functions.sequencer.timeout # AWS guidance for Lambda sources
  message_retention_seconds  = 86400
  receive_wait_time_seconds  = 20
  sqs_managed_sse_enabled    = true
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.joins_dlq.arn
    maxReceiveCount     = 5
  })
  tags = local.tags
}

# --- IAM: one role per function, least privilege ----------------------------------------
data "aws_iam_policy_document" "lambda_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "fn" {
  for_each           = local.functions
  name               = "${var.name}-queue-${each.key}"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
  tags               = local.tags
}

resource "aws_cloudwatch_log_group" "fn" {
  for_each          = local.functions
  name              = "/aws/lambda/${var.name}-queue-${each.key}"
  retention_in_days = var.log_retention_days
  tags              = local.tags
}

data "aws_iam_policy_document" "fn" {
  for_each = local.functions

  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.fn[each.key].arn}:*"]
  }

  dynamic "statement" {
    for_each = each.key == "join" ? [1] : []
    content {
      sid       = "SendJoins"
      actions   = ["sqs:SendMessage"]
      resources = [aws_sqs_queue.joins.arn]
    }
  }

  dynamic "statement" {
    for_each = each.key == "join" ? [1] : []
    content {
      sid       = "ReadQueueState"
      actions   = ["dynamodb:GetItem"]
      resources = [var.table_arn]
    }
  }

  dynamic "statement" {
    for_each = each.key == "sequencer" ? [1] : []
    content {
      sid       = "ConsumeJoins"
      actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
      resources = [aws_sqs_queue.joins.arn]
    }
  }

  dynamic "statement" {
    for_each = each.key == "sequencer" ? [1] : []
    content {
      sid       = "ClaimPlacesAndWritePositions"
      actions   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem"]
      resources = [var.table_arn]
    }
  }

  dynamic "statement" {
    for_each = each.key == "position" ? [1] : []
    content {
      sid       = "ReadPlaces"
      actions   = ["dynamodb:GetItem"]
      resources = [var.table_arn]
    }
  }

  dynamic "statement" {
    for_each = each.key == "position" ? [1] : []
    content {
      sid       = "ReadTokenKey"
      actions   = ["secretsmanager:GetSecretValue"]
      resources = [aws_secretsmanager_secret.token_key.arn]
    }
  }

  dynamic "statement" {
    for_each = each.key == "starter" ? [1] : []
    content {
      sid       = "OpenQueuesAndShuffle"
      actions   = ["dynamodb:Query", "dynamodb:UpdateItem"]
      resources = [var.table_arn, "${var.table_arn}/index/active-queues"]
    }
  }
}

resource "aws_iam_role_policy" "fn" {
  for_each = local.functions
  name     = "queue-${each.key}"
  role     = aws_iam_role.fn[each.key].id
  policy   = data.aws_iam_policy_document.fn[each.key].json
}

# --- Lambda functions --------------------------------------------------------------
resource "aws_lambda_function" "fn" {
  for_each         = local.functions
  function_name    = "${var.name}-queue-${each.key}"
  role             = aws_iam_role.fn[each.key].arn
  runtime          = "python3.12"
  architectures    = ["arm64"]
  handler          = each.value.handler
  filename         = data.archive_file.code.output_path
  source_code_hash = data.archive_file.code.output_base64sha256
  timeout          = each.value.timeout
  memory_size      = each.value.memory

  environment {
    variables = {
      QUEUE_TABLE      = var.table_name
      JOIN_QUEUE_URL   = aws_sqs_queue.joins.url
      TOKEN_KEY_SECRET = aws_secretsmanager_secret.token_key.arn
    }
  }

  logging_config {
    log_format = "JSON"
    log_group  = aws_cloudwatch_log_group.fn[each.key].name
  }

  tags       = local.tags
  depends_on = [aws_iam_role_policy.fn]
}

resource "aws_lambda_event_source_mapping" "sequencer" {
  event_source_arn                   = aws_sqs_queue.joins.arn
  function_name                      = aws_lambda_function.fn["sequencer"].arn
  batch_size                         = 100
  maximum_batching_window_in_seconds = 1
  function_response_types            = ["ReportBatchItemFailures"]
  scaling_config {
    maximum_concurrency = var.sequencer_max_concurrency # leave room for the API functions
  }
}

# --- API Gateway HTTP API -------------------------------------------------------------
resource "aws_apigatewayv2_api" "this" {
  name          = "${var.name}-queue"
  protocol_type = "HTTP"
  description   = "SurgeGate waiting room"

  cors_configuration {
    allow_origins = var.cors_allow_origins
    allow_methods = ["GET", "POST", "OPTIONS"]
    allow_headers = ["authorization", "content-type"]
    max_age       = 600
  }

  tags = local.tags
}

# Cognito access tokens are checked by API Gateway before any Lambda runs (signature, issuer,
# expiry, and client_id in the audience list).
resource "aws_apigatewayv2_authorizer" "cognito" {
  api_id           = aws_apigatewayv2_api.this.id
  name             = "cognito"
  authorizer_type  = "JWT"
  identity_sources = ["$request.header.Authorization"]
  jwt_configuration {
    issuer   = var.cognito_issuer
    audience = var.cognito_client_ids
  }
}

resource "aws_apigatewayv2_integration" "fn" {
  for_each               = local.routes
  api_id                 = aws_apigatewayv2_api.this.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.fn[each.key].invoke_arn
  payload_format_version = "2.0"
  timeout_milliseconds   = 10000
}

resource "aws_apigatewayv2_route" "fn" {
  for_each           = local.routes
  api_id             = aws_apigatewayv2_api.this.id
  route_key          = each.value
  target             = "integrations/${aws_apigatewayv2_integration.fn[each.key].id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.cognito.id
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/apigateway/${var.name}-queue"
  retention_in_days = var.log_retention_days
  tags              = local.tags
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.this.id
  name        = "$default"
  auto_deploy = true

  # A cap on requests (abuse and cost guard); per-route limits can be tighter later (WAF on demo).
  default_route_settings {
    throttling_burst_limit = var.throttle_burst
    throttling_rate_limit  = var.throttle_rate
  }

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api.arn
    format = jsonencode({
      requestId = "$context.requestId"
      time      = "$context.requestTime"
      route     = "$context.routeKey"
      status    = "$context.status"
      latencyMs = "$context.responseLatency"
      sub       = "$context.authorizer.claims.sub"
      error     = "$context.authorizer.error"
    })
  }

  tags = local.tags
}

resource "aws_lambda_permission" "api" {
  for_each      = aws_apigatewayv2_integration.fn
  statement_id  = "AllowApiGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.fn[each.key].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.this.execution_arn}/*/*"
}

# --- Every minute: open queues whose sale has started (shuffle the pre-queue) -------------
data "aws_iam_policy_document" "scheduler_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

data "aws_caller_identity" "current" {}

resource "aws_iam_role" "scheduler" {
  name               = "${var.name}-queue-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_trust.json
  tags               = local.tags
}

data "aws_iam_policy_document" "scheduler" {
  statement {
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.fn["starter"].arn]
  }
}

resource "aws_iam_role_policy" "scheduler" {
  name   = "invoke-queue-tick"
  role   = aws_iam_role.scheduler.id
  policy = data.aws_iam_policy_document.scheduler.json
}

resource "aws_scheduler_schedule" "starter" {
  name                         = "${var.name}-queue-starter"
  description                  = "Open waiting rooms at sale start (pre-queue shuffle)"
  schedule_expression          = "rate(1 minute)"
  schedule_expression_timezone = "UTC"
  state                        = var.schedules_enabled ? "ENABLED" : "DISABLED"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.fn["starter"].arn
    role_arn = aws_iam_role.scheduler.arn
    retry_policy {
      maximum_retry_attempts       = 0 # the next minute's run is the retry
      maximum_event_age_in_seconds = 60
    }
  }
}

# --- Queue-token signing key ------------------------------------------------------------
# Generated by Terraform but NEVER stored in state: an ephemeral random value goes into a
# write-only attribute. Bump token_key_version to rotate (tokens carry the kid).
ephemeral "random_password" "token_key" {
  length  = 64
  special = false
}

resource "aws_secretsmanager_secret" "token_key" {
  name                    = "${var.secrets_prefix}/queue/token-key"
  description             = "HMAC key for signed queue tokens (JSON: kid, key)"
  recovery_window_in_days = 7
  tags                    = local.tags
}

resource "aws_secretsmanager_secret_version" "token_key" {
  secret_id = aws_secretsmanager_secret.token_key.id
  secret_string_wo = jsonencode({
    kid = "v${var.token_key_version}"
    key = ephemeral.random_password.token_key.result
  })
  secret_string_wo_version = var.token_key_version
}

# The join route became one entry of the routes map (Day 5 Task 3): keep it, don't recreate it.
moved {
  from = aws_apigatewayv2_route.join
  to   = aws_apigatewayv2_route.fn["join"]
}
