variable "name" {
  description = "Name prefix, e.g. surgegate-dev."
  type        = string
}

variable "source_dir" {
  description = "Directory holding the sg_workers package (services/workers/src)."
  type        = string
}

variable "vpc_id" {
  description = "VPC for the release Lambda."
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnets for the release Lambda (reach PostgreSQL; AWS APIs via NAT)."
  type        = list(string)
}

variable "db_instance_id" {
  description = "RDS instance identifier (endpoint and managed secret are looked up)."
  type        = string
}

variable "kms_key_arn" {
  description = "KMS key encrypting the RDS-managed secret."
  type        = string
}

variable "sale_events_stream" {
  description = "Kinesis stream for hold_released events."
  type        = string
}

variable "sale_events_arn" {
  description = "Kinesis stream ARN."
  type        = string
}

variable "log_retention_days" {
  description = "CloudWatch Logs retention."
  type        = number
  default     = 7
}

variable "tags" {
  description = "Extra tags."
  type        = map(string)
  default     = {}
}

variable "payments_visibility_timeout" {
  description = "Seconds a received payment message stays invisible (must exceed the worker's worst case, ~15 s)."
  type        = number
  default     = 60
}

variable "payments_max_receive_count" {
  description = "Failed receives before a payment message moves to the DLQ."
  type        = number
  default     = 5
}

variable "alert_email_enabled" {
  description = "Subscribe an email address to the alerts topic (the address itself is alert_email)."
  type        = bool
  default     = false
}

variable "alert_email" {
  description = "Alert email address. Set it only in an uncommitted *.auto.tfvars or TF_VAR_alert_email."
  type        = string
  default     = ""
  sensitive   = true
}
