output "api_url" {
  description = "Public HTTPS URL of the booking API (null while CloudFront is disabled)."
  value = !var.cloudfront_enabled ? null : (
    local.use_domain ? "https://${local.api_fqdn}" : "https://${aws_cloudfront_distribution.api[0].domain_name}"
  )
}

output "cloudfront_domain_name" {
  description = "CloudFront distribution domain (*.cloudfront.net)."
  value       = try(aws_cloudfront_distribution.api[0].domain_name, null)
}

output "cloudfront_distribution_id" {
  description = "CloudFront distribution ID."
  value       = try(aws_cloudfront_distribution.api[0].id, null)
}

output "alb_dns_name" {
  description = "ALB DNS name (direct requests get 403); null while dev is down."
  value       = try(aws_lb.this[0].dns_name, null)
}

output "target_group_name" {
  description = "Target group the booking-api TargetGroupBinding uses."
  value       = var.target_group_name
}

output "route53_name_servers" {
  description = "Name servers to set at the registrar (only when domain_name is set)."
  value       = local.use_domain ? aws_route53_zone.this[0].name_servers : []
}

output "buyer_site_bucket" {
  description = "S3 bucket of the buyer site (CI uploads the static export here)."
  value       = local.site == 1 ? aws_s3_bucket.site[0].bucket : null
}

output "distribution_id" {
  description = "CloudFront distribution ID (cache invalidation after a site deploy)."
  value       = var.cloudfront_enabled ? aws_cloudfront_distribution.api[0].id : null
}

output "alb_arn_suffix" {
  description = "ALB ARN suffix (CloudWatch LoadBalancer dimension); null while dev is down."
  value       = try(aws_lb.this[0].arn_suffix, null)
}

output "target_group_arn_suffix" {
  description = "booking-api target group ARN suffix (CloudWatch TargetGroup dimension); null while dev is down."
  value       = try(aws_lb_target_group.api[0].arn_suffix, null)
}
