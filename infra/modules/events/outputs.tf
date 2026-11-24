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

output "live_ws_url" {
  description = "Organiser live-dashboard WebSocket (append ?token=<live token>)."
  value       = "wss://${aws_apigatewayv2_api.live.id}.execute-api.${local.region}.amazonaws.com/${local.ws_stage}"
}

output "live_key_secret_arn" {
  description = "HMAC key for the 60-second live tokens (the booking API issues them)."
  value       = aws_secretsmanager_secret.live_key.arn
}

output "stats_table_name" {
  description = "Live counters + WebSocket connections."
  value       = aws_dynamodb_table.stats.name
}
