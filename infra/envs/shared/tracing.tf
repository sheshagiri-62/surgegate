# ---------------------------------------------------------------------------
# X-Ray Transaction Search (Day 9 Task 3), account-wide in ap-south-1. The CloudWatch agent
# add-on sends OpenTelemetry spans to X-Ray's OTLP endpoint, which only accepts them when the
# segment destination is CloudWatch Logs: spans land in the "aws/spans" log group (log
# ingestion, $0.67/GB) and 1% are indexed as trace summaries (free; more is $0.75 per million).
# ---------------------------------------------------------------------------
data "aws_caller_identity" "tracing" {}

locals {
  xray_logs_arn = "arn:aws:logs:${var.region}:${data.aws_caller_identity.tracing.account_id}:log-group"
}

# "aws/spans" is created by X-Ray itself on the first span (names starting with aws/ are reserved
# for AWS, so Terraform can't create it); imported here to give it 7 days instead of 30.
import {
  to = aws_cloudwatch_log_group.spans
  id = "aws/spans"
}

resource "aws_cloudwatch_log_group" "spans" {
  name              = "aws/spans"
  retention_in_days = 7
  tags              = { Component = "observability" }
}

# X-Ray may write spans (and Application Signals data, unused) into these log groups only.
resource "aws_cloudwatch_log_resource_policy" "xray" {
  policy_name = "surgegate-xray-transaction-search"
  policy_document = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "TransactionSearchXRayAccess"
      Effect    = "Allow"
      Principal = { Service = "xray.amazonaws.com" }
      Action    = "logs:PutLogEvents"
      Resource = [
        "${local.xray_logs_arn}:aws/spans:*",
        "${local.xray_logs_arn}:/aws/application-signals/data:*",
      ]
      Condition = {
        ArnLike      = { "aws:SourceArn" = "arn:aws:xray:${var.region}:${data.aws_caller_identity.tracing.account_id}:*" }
        StringEquals = { "aws:SourceAccount" = data.aws_caller_identity.tracing.account_id }
      }
    }]
  })
}

resource "aws_xray_trace_segment_destination" "this" {
  destination = "CloudWatchLogs"
  depends_on  = [aws_cloudwatch_log_resource_policy.xray]
}

resource "aws_xray_indexing_rule" "default" {
  name = "Default"
  rule {
    probabilistic {
      desired_sampling_percentage = 1 # the free tier
    }
  }
  depends_on = [aws_xray_trace_segment_destination.this]
}
