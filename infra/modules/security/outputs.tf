output "trail_bucket" {
  description = "CloudTrail (and Config) log bucket."
  value       = aws_s3_bucket.trail.bucket
}

output "guardduty_detector_id" {
  description = "GuardDuty detector (null when paid services are off)."
  value       = try(aws_guardduty_detector.this[0].id, null)
}
