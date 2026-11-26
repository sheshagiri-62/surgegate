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

variable "secrets_prefix" {
  description = "Secrets Manager / SSM prefix, e.g. surgegate/dev."
  type        = string
}

variable "tickets_bucket_name" {
  description = "S3 bucket for ticket PDFs (SSE-KMS with kms_key_arn)."
  type        = string
}

variable "tickets_bucket_arn" {
  description = "ARN of the tickets bucket."
  type        = string
}

variable "event_bus_name" {
  description = "Sale-events EventBridge bus (order_paid rule)."
  type        = string
}

variable "cognito_user_pool_id" {
  description = "User pool (buyer email lookup outside the SES sandbox)."
  type        = string
}

variable "cognito_user_pool_arn" {
  description = "User pool ARN."
  type        = string
}

variable "ses_identity_enabled" {
  description = "Create the SES email identity for ses_sender (the address itself is not in Git)."
  type        = bool
  default     = false
}

variable "ses_sender" {
  description = "Verified SES sender address. Only in an uncommitted *.auto.tfvars / TF_VAR."
  type        = string
  default     = ""
  sensitive   = true
}

variable "ses_sandbox_recipient" {
  description = "SES sandbox: every ticket email goes to this verified address. Uncommitted."
  type        = string
  default     = ""
  sensitive   = true
}

variable "sweep_enabled" {
  description = "Run the 5-minute ticket sweep (only while the database exists)."
  type        = bool
  default     = false
}

variable "tickets_max_concurrency" {
  description = "Ticket-worker Lambda instances at most (SQS event source; 2 is the minimum)."
  type        = number
  default     = 5
}

variable "ses_min_send_interval_seconds" {
  description = "Seconds between ticket emails per worker instance (0 = no pacing). demo: 2 x 2 s = 1/s, the SES sandbox rate."
  type        = number
  default     = 0
}

variable "tickets_consumer_enabled" {
  description = "Ticket queue -> worker mapping on. Off while the database is down, so jobs wait instead of going to the DLQ."
  type        = bool
  default     = true
}
