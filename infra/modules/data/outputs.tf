output "kms_key_arn" {
  description = "Customer-managed KMS key for data at rest."
  value       = aws_kms_key.data.arn
}

output "bucket_names" {
  description = "S3 bucket names by purpose."
  value       = { for k, b in aws_s3_bucket.this : k => b.bucket }
}

output "postgres_endpoint" {
  description = "PostgreSQL host:port (null while down)."
  value       = try(aws_db_instance.postgres[0].endpoint, null)
}

output "postgres_master_secret_arn" {
  description = "Secrets Manager ARN of the RDS-managed master credentials (null while down)."
  value       = try(aws_db_instance.postgres[0].master_user_secret[0].secret_arn, null)
}

output "postgres_final_snapshot_id" {
  description = "Name the final snapshot will get at the next make down."
  value       = try(aws_db_instance.postgres[0].final_snapshot_identifier, null)
}

output "redis_primary_endpoint" {
  description = "Redis primary endpoint (TLS, AUTH; null while down)."
  value       = try(aws_elasticache_replication_group.redis[0].primary_endpoint_address, null)
}

output "redis_auth_secret_arn" {
  description = "Secrets Manager ARN of the Redis AUTH token."
  value       = aws_secretsmanager_secret.redis_auth.arn
}

output "razorpay_secret_arn" {
  description = "Secrets Manager ARN for the Razorpay test keys (value set manually)."
  value       = aws_secretsmanager_secret.razorpay.arn
}

output "postgres_security_group_id" {
  description = "PostgreSQL security group."
  value       = aws_security_group.postgres.id
}

output "redis_security_group_id" {
  description = "Redis security group."
  value       = aws_security_group.redis.id
}
