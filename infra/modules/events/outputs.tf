output "stream_name" {
  description = "Kinesis stream name (exists only while stream_enabled)."
  value       = local.name
}

output "stream_arn" {
  description = "Kinesis stream ARN (stable; for producers' IAM policies)."
  value       = local.stream_arn
}

output "bus_name" {
  description = "EventBridge custom bus."
  value       = aws_cloudwatch_event_bus.this.name
}

output "log_group" {
  description = "Log group receiving every sale event."
  value       = aws_cloudwatch_log_group.events.name
}
