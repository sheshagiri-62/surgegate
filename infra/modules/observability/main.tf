# ---------------------------------------------------------------------------
# "Sale room" CloudWatch dashboard (Day 9 Task 3): one screen for a live sale, top to bottom in
# the order a buyer moves: edge -> waiting room -> booking -> payments/tickets -> data -> pods.
# Free: the first 3 dashboards per account (50 metrics each); this is the first.
# ---------------------------------------------------------------------------
locals {
  r   = var.region
  fn  = { for k in ["join", "position", "admit", "serving", "sequencer", "valve"] : k => "${var.name}-queue-${k}" }
  alb = var.alb_arn_suffix != null && var.target_group_arn_suffix != null

  text = { type = "text", width = 24, height = 1 }

  widgets = concat(
    [merge(local.text, { properties = { markdown = "## Edge: CloudFront + WAF" } })],
    [
      {
        type = "metric", width = 8, height = 6
        properties = {
          title   = "CloudFront requests / min", region = "us-east-1", stat = "Sum", period = 60, view = "timeSeries"
          metrics = [["AWS/CloudFront", "Requests", "DistributionId", var.distribution_id, "Region", "Global"]]
        }
      },
      {
        type = "metric", width = 8, height = 6
        properties = {
          title = "CloudFront error rate %", region = "us-east-1", stat = "Average", period = 60, view = "timeSeries"
          metrics = [
            ["AWS/CloudFront", "4xxErrorRate", "DistributionId", var.distribution_id, "Region", "Global"],
            ["AWS/CloudFront", "5xxErrorRate", "DistributionId", var.distribution_id, "Region", "Global"],
          ]
        }
      },
      {
        type = "metric", width = 8, height = 6
        properties = {
          title = "WAF: blocked / challenged per rule", region = "us-east-1", stat = "Sum", period = 60, view = "timeSeries"
          metrics = [
            ["AWS/WAFV2", "BlockedRequests", "WebACL", var.web_acl_name, "Rule", "RateLimitAll"],
            ["AWS/WAFV2", "BlockedRequests", "WebACL", var.web_acl_name, "Rule", "RateLimitJoin"],
            ["AWS/WAFV2", "BlockedRequests", "WebACL", var.web_acl_name, "Rule", "BotControl"],
            ["AWS/WAFV2", "ChallengeRequests", "WebACL", var.web_acl_name, "Rule", "ChallengeJoin"],
            ["AWS/WAFV2", "ChallengeRequests", "WebACL", var.web_acl_name, "Rule", "ChallengePage"],
          ]
        }
      },
    ],
    [merge(local.text, { properties = { markdown = "## Waiting room: API Gateway + Lambda + SQS + DynamoDB" } })],
    [
      {
        type = "metric", width = 8, height = 6
        properties = {
          title = "Queue API: requests, 4xx, 5xx / min", region = local.r, stat = "Sum", period = 60, view = "timeSeries"
          metrics = [
            ["AWS/ApiGateway", "Count", "ApiId", var.queue_api_id],
            ["AWS/ApiGateway", "4xx", "ApiId", var.queue_api_id],
            ["AWS/ApiGateway", "5xx", "ApiId", var.queue_api_id],
          ]
        }
      },
      {
        type = "metric", width = 8, height = 6
        properties = {
          title   = "Queue Lambdas: p95 duration (ms)", region = local.r, stat = "p95", period = 60, view = "timeSeries"
          metrics = [for k, f in local.fn : ["AWS/Lambda", "Duration", "FunctionName", f, { label = k }]]
        }
      },
      {
        type = "metric", width = 8, height = 6
        properties = {
          title = "Queue Lambdas: errors + throttles", region = local.r, stat = "Sum", period = 60, view = "timeSeries"
          metrics = concat(
            [for k, f in local.fn : ["AWS/Lambda", "Errors", "FunctionName", f, { label = "${k} errors" }]],
            [["AWS/Lambda", "Throttles", "FunctionName", local.fn["join"], { label = "join throttles" }]],
          )
        }
      },
      {
        type = "metric", width = 8, height = 6
        properties = {
          title = "Join backlog (SQS): visible + oldest age (s)", region = local.r, stat = "Maximum", period = 60, view = "timeSeries"
          metrics = [
            ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", "${var.name}-joins"],
            ["AWS/SQS", "ApproximateAgeOfOldestMessage", "QueueName", "${var.name}-joins", { yAxis = "right" }],
          ]
        }
      },
      {
        type = "metric", width = 8, height = 6
        properties = {
          title = "Queue table: consumed capacity + throttles", region = local.r, stat = "Sum", period = 60, view = "timeSeries"
          metrics = [
            ["AWS/DynamoDB", "ConsumedWriteCapacityUnits", "TableName", var.queue_table],
            ["AWS/DynamoDB", "ConsumedReadCapacityUnits", "TableName", var.queue_table],
            ["AWS/DynamoDB", "ThrottledRequests", "TableName", var.queue_table, { yAxis = "right" }],
          ]
        }
      },
      {
        type = "metric", width = 8, height = 6
        properties = {
          title   = "Lambda concurrency (account)", region = local.r, stat = "Maximum", period = 60, view = "timeSeries"
          metrics = [["AWS/Lambda", "ConcurrentExecutions"]]
        }
      },
    ],
    [merge(local.text, { properties = { markdown = "## Booking API (ALB -> EKS)" } })],
    # ALB widgets only while the ALB exists (a filtered for keeps both branches' types apart)
    [for w in [
      {
        type = "metric", width = 8, height = 6
        properties = {
          title = "Booking API latency p95 / p99 (s)  [SLO p95 < 0.5 s]", region = local.r, period = 60, view = "timeSeries"
          metrics = [
            ["AWS/ApplicationELB", "TargetResponseTime", "LoadBalancer", var.alb_arn_suffix, "TargetGroup", var.target_group_arn_suffix, { stat = "p95" }],
            ["AWS/ApplicationELB", "TargetResponseTime", "LoadBalancer", var.alb_arn_suffix, "TargetGroup", var.target_group_arn_suffix, { stat = "p99" }],
          ]
          annotations = { horizontal = [{ label = "SLO p95", value = 0.5 }] }
        }
      },
      {
        type = "metric", width = 8, height = 6
        properties = {
          title = "Booking API requests + 5xx / min", region = local.r, stat = "Sum", period = 60, view = "timeSeries"
          metrics = [
            ["AWS/ApplicationELB", "RequestCount", "LoadBalancer", var.alb_arn_suffix, "TargetGroup", var.target_group_arn_suffix],
            ["AWS/ApplicationELB", "HTTPCode_Target_5XX_Count", "LoadBalancer", var.alb_arn_suffix, "TargetGroup", var.target_group_arn_suffix, { yAxis = "right" }],
          ]
        }
      },
      {
        type = "metric", width = 8, height = 6
        properties = {
          title   = "Healthy booking-api targets", region = local.r, stat = "Minimum", period = 60, view = "timeSeries"
          metrics = [["AWS/ApplicationELB", "HealthyHostCount", "LoadBalancer", var.alb_arn_suffix, "TargetGroup", var.target_group_arn_suffix]]
        }
      },
    ] : w if local.alb],
    [for w in [merge(local.text, { height = 2, properties = { markdown = "_ALB widgets appear once the environment is up (make up, then apply)._" } })] : w if !local.alb],
    [merge(local.text, { properties = { markdown = "## Payments + tickets" } })],
    [
      {
        type = "metric", width = 12, height = 6
        properties = {
          title = "Payments / tickets queues + DLQs (visible)", region = local.r, stat = "Maximum", period = 60, view = "timeSeries"
          metrics = [for q in ["payments", "payments-dlq", "tickets", "tickets-dlq", "consumers-failed"] :
          ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", "${var.name}-${q}", { label = q }]]
        }
      },
      {
        type = "metric", width = 12, height = 6
        properties = {
          title = "Ticket worker: invocations, errors, p95 (ms)", region = local.r, period = 60, view = "timeSeries"
          metrics = [
            ["AWS/Lambda", "Invocations", "FunctionName", "${var.name}-ticket-worker", { stat = "Sum" }],
            ["AWS/Lambda", "Errors", "FunctionName", "${var.name}-ticket-worker", { stat = "Sum" }],
            ["AWS/Lambda", "Duration", "FunctionName", "${var.name}-ticket-worker", { stat = "p95", yAxis = "right" }],
          ]
        }
      },
    ],
    [merge(local.text, { properties = { markdown = "## Data: RDS, Redis, Kinesis" } })],
    [
      {
        type = "metric", width = 8, height = 6
        properties = {
          title = "RDS: CPU % + connections", region = local.r, stat = "Average", period = 60, view = "timeSeries"
          metrics = [
            ["AWS/RDS", "CPUUtilization", "DBInstanceIdentifier", "${var.name}-pg"],
            ["AWS/RDS", "DatabaseConnections", "DBInstanceIdentifier", "${var.name}-pg", { yAxis = "right" }],
          ]
        }
      },
      {
        type = "metric", width = 8, height = 6
        properties = {
          title = "Redis: CPU % + cache hits / misses", region = local.r, period = 60, view = "timeSeries"
          metrics = [
            ["AWS/ElastiCache", "EngineCPUUtilization", "CacheClusterId", "${var.name}-redis-001", { stat = "Average" }],
            ["AWS/ElastiCache", "CacheHits", "CacheClusterId", "${var.name}-redis-001", { stat = "Sum", yAxis = "right" }],
            ["AWS/ElastiCache", "CacheMisses", "CacheClusterId", "${var.name}-redis-001", { stat = "Sum", yAxis = "right" }],
          ]
        }
      },
      {
        type = "metric", width = 8, height = 6
        properties = {
          title = "Sale events (Kinesis): in / throttled / consumer lag (ms)", region = local.r, period = 60, view = "timeSeries"
          metrics = [
            ["AWS/Kinesis", "IncomingRecords", "StreamName", var.stream_name, { stat = "Sum" }],
            ["AWS/Kinesis", "WriteProvisionedThroughputExceeded", "StreamName", var.stream_name, { stat = "Sum" }],
            ["AWS/Kinesis", "GetRecords.IteratorAgeMilliseconds", "StreamName", var.stream_name, { stat = "Maximum", yAxis = "right" }],
          ]
        }
      },
    ],
    [merge(local.text, { properties = { markdown = "## Pods (Container Insights) + errors (logs)" } })],
    [
      {
        type = "metric", width = 8, height = 6
        properties = {
          title   = "Pod CPU % (booking namespace)", region = local.r, period = 60, view = "timeSeries"
          metrics = [[{ expression = "SEARCH('{ContainerInsights,ClusterName,Namespace,PodName} MetricName=\"pod_cpu_utilization\" ClusterName=\"${var.cluster_name}\" Namespace=\"booking\"', 'Average', 60)", id = "cpu" }]]
        }
      },
      {
        type = "metric", width = 8, height = 6
        properties = {
          title = "Nodes + running pods", region = local.r, stat = "Average", period = 60, view = "timeSeries"
          metrics = [
            ["ContainerInsights", "cluster_node_count", "ClusterName", var.cluster_name],
            ["ContainerInsights", "cluster_number_of_running_pods", "ClusterName", var.cluster_name, { yAxis = "right" }],
          ]
        }
      },
      {
        type = "log", width = 8, height = 6
        properties = {
          title = "Latest ERROR lines (pods)", region = local.r, view = "table"
          query = "SOURCE '/aws/containerinsights/${var.cluster_name}/application' | fields @timestamp, kubernetes.pod_name as pod, log_processed.message as message, log_processed.trace_id as trace | filter log_processed.level = 'ERROR' | sort @timestamp desc | limit 20"
        }
      },
    ],
  )
}

resource "aws_cloudwatch_dashboard" "sale_room" {
  dashboard_name = "${var.name}-sale-room"
  dashboard_body = jsonencode({ widgets = local.widgets })
}
