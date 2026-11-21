variable "name" {
  description = "Name prefix, e.g. surgegate-dev."
  type        = string
}

variable "enable_test_client" {
  description = "Create a password-auth app client for scripts and load tests (dev only, never demo users)."
  type        = bool
  default     = false
}

variable "deletion_protection" {
  description = "Protect the user pool from deletion (demo: true)."
  type        = bool
  default     = false
}

variable "tags" {
  description = "Extra tags."
  type        = map(string)
  default     = {}
}
