output "state_bucket" {
  description = "S3 bucket holding Terraform state for every root in the repo."
  value       = aws_s3_bucket.state.bucket
}

output "github_oidc_provider_arn" {
  description = "ARN of the GitHub Actions OIDC identity provider."
  value       = aws_iam_openid_connect_provider.github.arn
}

output "plan_role_arn" {
  description = "Role for infra-plan.yml (pull requests, read-only)."
  value       = aws_iam_role.plan.arn
}

output "apply_role_arn" {
  description = "Role for infra-apply.yml (main branch, dev and demo environments)."
  value       = aws_iam_role.apply.arn
}
