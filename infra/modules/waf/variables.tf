variable "name" {
  description = "Name prefix (surgegate-<env>)."
  type        = string
}

variable "load_test_enabled" {
  description = "Switch on the ALLOW rule for the load generators (only for a k6 window)."
  type        = bool
  default     = false
}

variable "load_test_cidrs" {
  description = "Load-generator source addresses (/32) allowed past every other rule while load_test_enabled."
  type        = list(string)
  default     = []
}

variable "rate_limit_per_5min" {
  description = "Requests per client IP per 5 minutes, all paths (waiting-room polling is ~60-150)."
  type        = number
  default     = 2000
}

variable "join_limit_per_min" {
  description = "Joins per client IP per minute. Kept generous: many mobile users share one carrier IP (CGNAT)."
  type        = number
  default     = 30
}

variable "challenge_immunity_seconds" {
  description = "How long a solved challenge (aws-waf-token) is valid."
  type        = number
  default     = 1800
}

variable "log_retention_days" {
  description = "Retention of the WAF log group (only BLOCK / CHALLENGE / COUNT are logged)."
  type        = number
  default     = 7
}

variable "tags" {
  description = "Extra tags."
  type        = map(string)
  default     = {}
}
