output "user_pool_id" {
  description = "Cognito user pool ID."
  value       = aws_cognito_user_pool.this.id
}

output "user_pool_arn" {
  description = "Cognito user pool ARN."
  value       = aws_cognito_user_pool.this.arn
}

output "issuer" {
  description = "JWT issuer (iss claim) the API must accept."
  value       = "https://${aws_cognito_user_pool.this.endpoint}"
}

output "client_ids" {
  description = "App client IDs by name (buyer_web, organiser_web, test)."
  value = merge(
    { for k, c in aws_cognito_user_pool_client.web : k => c.id },
    { for c in aws_cognito_user_pool_client.test : "test" => c.id },
  )
}
