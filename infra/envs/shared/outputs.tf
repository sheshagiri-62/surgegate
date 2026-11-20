output "ecr_repository_urls" {
  description = "ECR repository URLs by service."
  value       = { for k, r in aws_ecr_repository.service : k => r.repository_url }
}
