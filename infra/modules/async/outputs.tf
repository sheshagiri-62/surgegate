output "hold_timer_arn" {
  description = "State machine the booking API starts for every hold."
  value       = aws_sfn_state_machine.hold_timer.arn
}

output "release_security_group_id" {
  description = "Security group of the release Lambda (allowed into PostgreSQL)."
  value       = aws_security_group.release.id
}

output "payments_queue_url" {
  description = "SQS queue the webhook endpoint writes to and the order worker reads."
  value       = aws_sqs_queue.payments.url
}

output "payments_queue_arn" {
  description = "ARN of the payments queue."
  value       = aws_sqs_queue.payments.arn
}

output "payments_dlq_url" {
  description = "Dead-letter queue for payment messages that failed 5 times."
  value       = aws_sqs_queue.payments_dlq.url
}

output "alerts_topic_arn" {
  description = "SNS topic for alarms."
  value       = aws_sns_topic.alerts.arn
}
