# ---------------------------------------------------------------------------
# SLO alarms (Day 9 Task 4) -> SNS "<name>-alerts" (email). Each alarm names its runbook.
# SLOs (blueprint "Observability and SLOs"):
#   joins 99.9% successful | booking p95 < 500 ms | paid orders confirmed within 60 s (99%) |
#   ticket email within 5 min (99%) | 0 oversold seats (enforced by the database, not an alarm)
# Cost: $0.10 per standard alarm metric per month (metric-math alarms count each metric);
# about $1.6/month here, prorated.
# The DLQ alarms (payments, tickets, consumers-failed) already live in the async/events modules.
# ---------------------------------------------------------------------------
locals {
  rb = "${var.runbook_base_url}/docs/runbooks"

  # SQS "oldest message" alarms: queue -> (seconds, runbook, why)
  age_alarms = {
    joins    = { seconds = 60, runbook = "queue-backlog.md", why = "Joins are not being sequenced (sequencer stuck or throttled): buyers see 'joining' forever." }
    payments = { seconds = 60, runbook = "payment-backlog.md", why = "SLO: paid orders confirmed within 60 s. The order worker is behind or down." }
    tickets  = { seconds = 300, runbook = "payment-backlog.md", why = "SLO: ticket email within 5 min. The ticket worker is behind or failing." }
  }
}

# --- Joins: 99.9% success -> fast-burn alarm on the queue API's 5xx rate -------------------------
# Error budget 0.1%. Burning it 14.4x faster than allowed (1.44% errors over 5 min) would use a
# 30-day budget in about 2 days: page now. Needs at least 100 requests, so idle noise can't fire it.
resource "aws_cloudwatch_metric_alarm" "join_error_burn" {
  alarm_name          = "${var.name}-slo-queue-api-5xx-fast-burn"
  alarm_description   = "Queue API 5xx > 1.44% over 5 min (14.4x the 0.1% error budget). Runbook: ${local.rb}/queue-backlog.md"
  comparison_operator = "GreaterThanThreshold"
  threshold           = 1.44
  evaluation_periods  = 1
  treat_missing_data  = "notBreaching"
  alarm_actions       = [var.alerts_topic_arn]
  ok_actions          = [var.alerts_topic_arn]

  metric_query {
    id          = "rate"
    expression  = "IF(requests >= 100, 100 * errors / requests, 0)"
    label       = "5xx %"
    return_data = true
  }
  metric_query {
    id = "errors"
    metric {
      namespace   = "AWS/ApiGateway"
      metric_name = "5xx"
      dimensions  = { ApiId = var.queue_api_id }
      period      = 300
      stat        = "Sum"
    }
  }
  metric_query {
    id = "requests"
    metric {
      namespace   = "AWS/ApiGateway"
      metric_name = "Count"
      dimensions  = { ApiId = var.queue_api_id }
      period      = 300
      stat        = "Sum"
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "queue_lambda_errors" {
  for_each            = toset(["join", "admit", "sequencer", "valve"])
  alarm_name          = "${var.name}-queue-${each.key}-errors"
  alarm_description   = "Waiting-room Lambda ${each.key} errors or throttles (2 of 3 minutes). Runbook: ${local.rb}/queue-backlog.md"
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  evaluation_periods  = 3
  datapoints_to_alarm = 2
  treat_missing_data  = "notBreaching"
  alarm_actions       = [var.alerts_topic_arn]
  ok_actions          = [var.alerts_topic_arn]

  metric_query {
    id          = "bad"
    expression  = "errors + throttles"
    label       = "errors + throttles"
    return_data = true
  }
  metric_query {
    id = "errors"
    metric {
      namespace   = "AWS/Lambda"
      metric_name = "Errors"
      dimensions  = { FunctionName = "${var.name}-queue-${each.key}" }
      period      = 60
      stat        = "Sum"
    }
  }
  metric_query {
    id = "throttles"
    metric {
      namespace   = "AWS/Lambda"
      metric_name = "Throttles"
      dimensions  = { FunctionName = "${var.name}-queue-${each.key}" }
      period      = 60
      stat        = "Sum"
    }
  }
}

# --- Queues: oldest message age (joins, payments, tickets) -----------------------------------
resource "aws_cloudwatch_metric_alarm" "queue_age" {
  for_each            = local.age_alarms
  alarm_name          = "${var.name}-${each.key}-oldest-message-age"
  alarm_description   = "${each.key} queue: oldest message older than ${each.value.seconds} s. ${each.value.why} Runbook: ${local.rb}/${each.value.runbook}"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateAgeOfOldestMessage"
  dimensions          = { QueueName = "${var.name}-${each.key}" }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 3
  datapoints_to_alarm = 2
  threshold           = each.value.seconds
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [var.alerts_topic_arn]
  ok_actions          = [var.alerts_topic_arn]
}

# --- Booking API: p95 < 500 ms, 5xx, healthy targets (only while the ALB exists) --------------
resource "aws_cloudwatch_metric_alarm" "booking_p95" {
  count               = local.alb ? 1 : 0
  alarm_name          = "${var.name}-slo-booking-p95-latency"
  alarm_description   = "SLO: booking API p95 > 500 ms in 3 of 5 minutes. Lower the admission rate first. Runbook: ${local.rb}/booking-latency.md"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "TargetResponseTime"
  dimensions          = { LoadBalancer = var.alb_arn_suffix, TargetGroup = var.target_group_arn_suffix }
  extended_statistic  = "p95"
  period              = 60
  evaluation_periods  = 5
  datapoints_to_alarm = 3
  threshold           = 0.5
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [var.alerts_topic_arn]
  ok_actions          = [var.alerts_topic_arn]
}

resource "aws_cloudwatch_metric_alarm" "booking_5xx" {
  count               = local.alb ? 1 : 0
  alarm_name          = "${var.name}-booking-5xx-rate"
  alarm_description   = "Booking API 5xx > 1% over 5 min (at least 50 requests). Runbook: ${local.rb}/booking-latency.md"
  comparison_operator = "GreaterThanThreshold"
  threshold           = 1
  evaluation_periods  = 1
  treat_missing_data  = "notBreaching"
  alarm_actions       = [var.alerts_topic_arn]
  ok_actions          = [var.alerts_topic_arn]

  metric_query {
    id          = "rate"
    expression  = "IF(requests >= 50, 100 * errors / requests, 0)"
    label       = "5xx %"
    return_data = true
  }
  metric_query {
    id = "errors"
    metric {
      namespace   = "AWS/ApplicationELB"
      metric_name = "HTTPCode_Target_5XX_Count"
      dimensions  = { LoadBalancer = var.alb_arn_suffix, TargetGroup = var.target_group_arn_suffix }
      period      = 300
      stat        = "Sum"
    }
  }
  metric_query {
    id = "requests"
    metric {
      namespace   = "AWS/ApplicationELB"
      metric_name = "RequestCount"
      dimensions  = { LoadBalancer = var.alb_arn_suffix, TargetGroup = var.target_group_arn_suffix }
      period      = 300
      stat        = "Sum"
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "booking_no_healthy_targets" {
  count               = local.alb ? 1 : 0
  alarm_name          = "${var.name}-booking-no-healthy-targets"
  alarm_description   = "No healthy booking-api pod behind the ALB for 2 minutes. Runbook: ${local.rb}/booking-latency.md"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HealthyHostCount"
  dimensions          = { LoadBalancer = var.alb_arn_suffix, TargetGroup = var.target_group_arn_suffix }
  statistic           = "Minimum"
  period              = 60
  evaluation_periods  = 2
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"
  alarm_actions       = [var.alerts_topic_arn]
  ok_actions          = [var.alerts_topic_arn]
}

# --- Data -------------------------------------------------------------------------------------
resource "aws_cloudwatch_metric_alarm" "rds_cpu" {
  alarm_name          = "${var.name}-rds-cpu-high"
  alarm_description   = "PostgreSQL CPU > 80% for 5 minutes. Runbook: ${local.rb}/booking-latency.md"
  namespace           = "AWS/RDS"
  metric_name         = "CPUUtilization"
  dimensions          = { DBInstanceIdentifier = "${var.name}-pg" }
  statistic           = "Average"
  period              = 60
  evaluation_periods  = 5
  threshold           = 80
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [var.alerts_topic_arn]
  ok_actions          = [var.alerts_topic_arn]
}

resource "aws_cloudwatch_metric_alarm" "rds_connections" {
  alarm_name          = "${var.name}-rds-connections-high"
  alarm_description   = "PostgreSQL connections > ${var.rds_connections_threshold} (db.t4g.micro allows about 80-110). Runbook: ${local.rb}/booking-latency.md"
  namespace           = "AWS/RDS"
  metric_name         = "DatabaseConnections"
  dimensions          = { DBInstanceIdentifier = "${var.name}-pg" }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 3
  threshold           = var.rds_connections_threshold
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [var.alerts_topic_arn]
  ok_actions          = [var.alerts_topic_arn]
}

resource "aws_cloudwatch_metric_alarm" "kinesis_throttled" {
  alarm_name          = "${var.name}-sale-events-write-throttled"
  alarm_description   = "Sale-events stream refused writes (over shard capacity): dashboards and analytics fall behind. Runbook: ${local.rb}/queue-backlog.md"
  namespace           = "AWS/Kinesis"
  metric_name         = "WriteProvisionedThroughputExceeded"
  dimensions          = { StreamName = var.stream_name }
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 3
  datapoints_to_alarm = 2
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [var.alerts_topic_arn]
  ok_actions          = [var.alerts_topic_arn]
}
