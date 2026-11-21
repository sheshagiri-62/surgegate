output "api_endpoint" {
  description = "Waiting-room API base URL."
  value       = aws_apigatewayv2_api.this.api_endpoint
}

output "join_queue_url" {
  description = "SQS joins queue URL."
  value       = aws_sqs_queue.joins.url
}

output "join_dlq_arn" {
  description = "Dead-letter queue for joins that failed 5 times."
  value       = aws_sqs_queue.joins_dlq.arn
}

output "function_names" {
  description = "Lambda function names by role."
  value       = { for k, f in aws_lambda_function.fn : k => f.function_name }
}

output "pass_key_secret_arn" {
  description = "Secrets Manager secret holding the booking-pass HMAC key."
  value       = aws_secretsmanager_secret.pass_key.arn
}

output "pass_key_secret_name" {
  description = "Name of the booking-pass key secret."
  value       = aws_secretsmanager_secret.pass_key.name
}
