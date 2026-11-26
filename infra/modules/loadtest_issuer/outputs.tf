output "issuer" {
  description = "Token issuer (iss): the function URL without the trailing slash."
  value       = trimsuffix(aws_lambda_function_url.issuer.function_url, "/")
}

output "audience" {
  description = "aud claim of the test tokens."
  value       = local.audience
}

output "key_secret_id" {
  description = "Secrets Manager name of the private key (keygen writes it, k6 reads it)."
  value       = aws_secretsmanager_secret.key.name
}

output "jwks_param" {
  description = "SSM parameter holding the public JWKS."
  value       = aws_ssm_parameter.jwks.name
}
