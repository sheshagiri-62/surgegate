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
