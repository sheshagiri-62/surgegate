# Ticket worker (Day 8 Task 1): order_paid -> SQS tickets -> Lambda -> PDF (one signed QR per
# seat) -> S3 tickets bucket (KMS) -> SES email. Plus a 5-minute sweep (EventBridge Scheduler)
# that re-queues paid orders without a ticket email (order_paid is published best-effort).
# All pay per use; nothing hourly.

# --- Ticket-signing key (QR tokens; the gate verifies them) ----------------------------------
resource "random_password" "ticket_key" {
  length  = 48
  special = false
}

resource "aws_secretsmanager_secret" "ticket_key" {
  name                    = "${var.secrets_prefix}/data/ticket-key"
  description             = "HMAC key for ticket QR tokens {kid, key} (Terraform-generated)."
  recovery_window_in_days = 7
  tags                    = local.tags
}

resource "aws_secretsmanager_secret_version" "ticket_key" {
  secret_id     = aws_secretsmanager_secret.ticket_key.id
  secret_string = jsonencode({ kid = "t1", key = random_password.ticket_key.result })
}

# --- Email settings (addresses only from the uncommitted *.auto.tfvars) ----------------------
resource "aws_ssm_parameter" "ticket_email" {
  name        = "/${var.secrets_prefix}/tickets/email"
  description = "Ticket email sender and SES-sandbox recipient (JSON)."
  type        = "String"
  value = jsonencode({
    sender            = var.ses_sender
    sandbox_recipient = var.ses_sandbox_recipient
  })
  tags = local.tags

  lifecycle {
    ignore_changes = [value] # CI plans run without the addresses
  }
}

# --- SES (ap-south-1, sandbox) -----------------------------------------------------------------
resource "aws_sesv2_email_identity" "sender" {
  count          = var.ses_identity_enabled ? 1 : 0
  email_identity = var.ses_sender # AWS emails a verification link to this address
  tags           = local.tags

  lifecycle {
    ignore_changes = [email_identity]
  }
}

resource "aws_sesv2_configuration_set" "tickets" {
  configuration_set_name = "${var.name}-tickets"

  delivery_options {
    tls_policy = "REQUIRE"
  }

  reputation_options {
    reputation_metrics_enabled = true
  }

  tags = local.tags
}

resource "aws_sesv2_configuration_set_event_destination" "tickets_metrics" {
  configuration_set_name = aws_sesv2_configuration_set.tickets.configuration_set_name
  event_destination_name = "cloudwatch-metrics"

  event_destination {
    enabled              = true
    matching_event_types = ["SEND", "DELIVERY", "BOUNCE", "COMPLAINT", "REJECT", "DELIVERY_DELAY"]

    cloud_watch_destination {
      dimension_configuration {
        dimension_name          = "channel"
        dimension_value_source  = "MESSAGE_TAG"
        default_dimension_value = "tickets"
      }
    }
  }
}

# --- Queue + DLQ + alarm (same pattern as payments) ------------------------------------------
resource "aws_sqs_queue" "tickets_dlq" {
  name                      = "${var.name}-tickets-dlq"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
  tags                      = local.tags
}

resource "aws_sqs_queue" "tickets" {
  name                       = "${var.name}-tickets"
  visibility_timeout_seconds = 360 # 6 x the Lambda timeout (AWS guidance for SQS -> Lambda)
  receive_wait_time_seconds  = 20
  message_retention_seconds  = 345600
  sqs_managed_sse_enabled    = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.tickets_dlq.arn
    maxReceiveCount     = 5
  })

  tags = local.tags
}

resource "aws_sqs_queue_redrive_allow_policy" "tickets_dlq" {
  queue_url = aws_sqs_queue.tickets_dlq.id
  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns   = [aws_sqs_queue.tickets.arn]
  })
}

resource "aws_cloudwatch_metric_alarm" "tickets_dlq" {
  alarm_name          = "${var.name}-tickets-dlq-not-empty"
  alarm_description   = "A ticket job failed 5 times and is in the DLQ: a paid buyer may have no ticket email. Inspect, fix, redrive."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = aws_sqs_queue.tickets_dlq.name }
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

# --- EventBridge rule: order_paid on the sale-events bus -> tickets queue ---------------------
resource "aws_cloudwatch_event_rule" "order_paid" {
  name           = "${var.name}-order-paid-to-tickets"
  description    = "order_paid -> ticket job"
  event_bus_name = var.event_bus_name
  event_pattern = jsonencode({
    source = ["surgegate.sale-events"]
    detail = { type = ["order_paid"] }
  })
  tags = local.tags
}

resource "aws_cloudwatch_event_target" "order_paid_to_tickets" {
  rule           = aws_cloudwatch_event_rule.order_paid.name
  event_bus_name = var.event_bus_name
  target_id      = "tickets-queue"
  arn            = aws_sqs_queue.tickets.arn

  retry_policy {
    maximum_event_age_in_seconds = 3600
    maximum_retry_attempts       = 50
  }

  dead_letter_config {
    arn = aws_sqs_queue.tickets_dlq.arn # EventBridge could not deliver -> same DLQ + alarm
  }
}

data "aws_iam_policy_document" "tickets_queue" {
  statement {
    sid       = "OrderPaidRuleMaySend"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.tickets.arn]
    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }
    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_cloudwatch_event_rule.order_paid.arn]
    }
  }
}

resource "aws_sqs_queue_policy" "tickets" {
  queue_url = aws_sqs_queue.tickets.id
  policy    = data.aws_iam_policy_document.tickets_queue.json
}

data "aws_iam_policy_document" "tickets_dlq" {
  statement {
    sid       = "OrderPaidRuleDeadLetters"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.tickets_dlq.arn]
    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }
    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_cloudwatch_event_rule.order_paid.arn]
    }
  }
}

resource "aws_sqs_queue_policy" "tickets_dlq" {
  queue_url = aws_sqs_queue.tickets_dlq.id
  policy    = data.aws_iam_policy_document.tickets_dlq.json
}

# --- The Lambda --------------------------------------------------------------------------------
resource "aws_iam_role" "tickets" {
  name               = "${var.name}-ticket-worker"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
  tags               = local.tags
}

resource "aws_iam_role_policy_attachment" "tickets_vpc" {
  role       = aws_iam_role.tickets.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_cloudwatch_log_group" "tickets" {
  name              = "/aws/lambda/${var.name}-ticket-worker"
  retention_in_days = var.log_retention_days
  tags              = local.tags
}

data "aws_iam_policy_document" "tickets" {
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.tickets.arn}:*"]
  }
  statement {
    sid       = "ConsumeAndRequeueTickets"
    actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes", "sqs:SendMessage"]
    resources = [aws_sqs_queue.tickets.arn]
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
    sid       = "ReadTicketKey"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.ticket_key.arn]
  }
  statement {
    sid       = "ReadEmailSettings"
    actions   = ["ssm:GetParameter"]
    resources = [aws_ssm_parameter.ticket_email.arn]
  }
  statement {
    sid       = "WriteTicketPdfs"
    actions   = ["s3:PutObject"]
    resources = ["${var.tickets_bucket_arn}/tickets/*"]
  }
  statement {
    sid       = "DataKeyViaSecretsManagerAndS3"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
    resources = [var.kms_key_arn]
    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["secretsmanager.${local.region}.amazonaws.com", "s3.${local.region}.amazonaws.com"]
    }
  }
  statement {
    sid     = "SendTicketEmails"
    actions = ["ses:SendEmail", "ses:SendRawEmail"]
    resources = concat(
      [aws_sesv2_configuration_set.tickets.arn],
      [for i in aws_sesv2_email_identity.sender : i.arn],
    )
  }
  statement {
    sid       = "FindBuyerEmail"
    actions   = ["cognito-idp:ListUsers"]
    resources = [var.cognito_user_pool_arn]
  }
  statement {
    sid       = "PublishSaleEvents"
    actions   = ["kinesis:PutRecord"]
    resources = [var.sale_events_arn]
  }
}

resource "aws_iam_role_policy" "tickets" {
  name   = "ticket-worker"
  role   = aws_iam_role.tickets.id
  policy = data.aws_iam_policy_document.tickets.json
}

resource "aws_lambda_function" "tickets" {
  function_name    = "${var.name}-ticket-worker"
  description      = "order_paid -> PDF with one signed QR per seat -> S3 -> SES (idempotent per order)"
  role             = aws_iam_role.tickets.arn
  runtime          = "python3.12"
  architectures    = ["arm64"]
  handler          = "sg_workers.ticket_worker.handler"
  filename         = data.archive_file.workers.output_path
  source_code_hash = data.archive_file.workers.output_base64sha256
  timeout          = 60
  memory_size      = 512

  vpc_config {
    subnet_ids         = var.private_subnet_ids
    security_group_ids = [aws_security_group.release.id] # already allowed into PostgreSQL
  }

  environment {
    variables = {
      DB_INSTANCE_ID        = var.db_instance_id
      TICKET_KEY_SECRET_ID  = aws_secretsmanager_secret.ticket_key.arn
      TICKET_EMAIL_PARAM    = aws_ssm_parameter.ticket_email.name
      TICKETS_BUCKET        = var.tickets_bucket_name
      TICKETS_QUEUE_URL     = aws_sqs_queue.tickets.url
      SES_CONFIGURATION_SET = aws_sesv2_configuration_set.tickets.configuration_set_name
      COGNITO_USER_POOL_ID  = var.cognito_user_pool_id
      SALE_EVENTS_STREAM    = var.sale_events_stream
      TICKET_CLAIM_SECONDS  = "120" # 2 x timeout
    }
  }

  logging_config {
    log_format = "JSON"
    log_group  = aws_cloudwatch_log_group.tickets.name
  }

  tags = local.tags
  depends_on = [
    aws_iam_role_policy.tickets,
    aws_iam_role_policy_attachment.tickets_vpc,
  ]
}

resource "aws_lambda_event_source_mapping" "tickets" {
  event_source_arn                   = aws_sqs_queue.tickets.arn
  function_name                      = aws_lambda_function.tickets.arn
  batch_size                         = 5
  maximum_batching_window_in_seconds = 0
  function_response_types            = ["ReportBatchItemFailures"] # one bad order never retries the rest
  scaling_config {
    maximum_concurrency = 5 # SES sandbox: 1 email/second
  }
  tags = local.tags
}

# --- Sweep: every 5 minutes, only while the database exists ----------------------------------
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
      values   = [local.account]
    }
  }
}

resource "aws_iam_role" "tickets_sweep" {
  name               = "${var.name}-ticket-sweep"
  assume_role_policy = data.aws_iam_policy_document.scheduler_trust.json
  tags               = local.tags
}

resource "aws_iam_role_policy" "tickets_sweep" {
  name = "invoke-ticket-worker"
  role = aws_iam_role.tickets_sweep.id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "lambda:InvokeFunction", Resource = aws_lambda_function.tickets.arn }]
  })
}

resource "aws_scheduler_schedule" "tickets_sweep" {
  name                = "${var.name}-ticket-sweep"
  description         = "Re-queue paid orders older than 2 minutes without a ticket email"
  schedule_expression = "rate(5 minutes)"
  state               = var.sweep_enabled ? "ENABLED" : "DISABLED" # off while the database is down

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.tickets.arn
    role_arn = aws_iam_role.tickets_sweep.arn
    input    = jsonencode({ sweep = true })
    retry_policy {
      maximum_retry_attempts = 0 # the next run in 5 minutes is the retry
    }
  }
}
