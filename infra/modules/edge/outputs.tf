output "api_url" {
  description = "Public HTTPS URL of the booking API."
  value       = local.use_domain ? "https://${local.api_fqdn}" : "https://${aws_cloudfront_distribution.api.domain_name}"
}

output "cloudfront_domain_name" {
  description = "CloudFront distribution domain (*.cloudfront.net)."
  value       = aws_cloudfront_distribution.api.domain_name
}

output "cloudfront_distribution_id" {
  description = "CloudFront distribution ID."
  value       = aws_cloudfront_distribution.api.id
}

output "alb_dns_name" {
  description = "ALB DNS name (direct requests get 403)."
  value       = aws_lb.this.dns_name
}

output "target_group_name" {
  description = "Target group the booking-api TargetGroupBinding uses."
  value       = aws_lb_target_group.api.name
}

output "route53_name_servers" {
  description = "Name servers to set at the registrar (only when domain_name is set)."
  value       = local.use_domain ? aws_route53_zone.this[0].name_servers : []
}
