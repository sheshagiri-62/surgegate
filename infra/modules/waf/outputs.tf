output "web_acl_arn" {
  description = "Attach to the CloudFront distribution (web_acl_id)."
  value       = aws_wafv2_web_acl.this.arn
}

output "challenge_sdk_url" {
  description = "WAF JavaScript SDK (challenge.js) the buyer site loads to get its aws-waf-token."
  value       = "${aws_wafv2_web_acl.this.application_integration_url}challenge.js"
}

output "log_group_name" {
  description = "WAF log group (us-east-1)."
  value       = aws_cloudwatch_log_group.waf.name
}
