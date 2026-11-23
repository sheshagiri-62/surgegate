output "hold_timer_arn" {
  description = "State machine the booking API starts for every hold."
  value       = aws_sfn_state_machine.hold_timer.arn
}

output "release_security_group_id" {
  description = "Security group of the release Lambda (allowed into PostgreSQL)."
  value       = aws_security_group.release.id
}
