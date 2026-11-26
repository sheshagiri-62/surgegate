variable "name" {
  description = "Name prefix, e.g. surgegate-dev."
  type        = string
}

variable "source_dir" {
  description = "Directory holding the sg_queue package (services/queue/src)."
  type        = string
}

variable "table_name" {
  description = "DynamoDB queue table name (data module)."
  type        = string
}

variable "table_arn" {
  description = "DynamoDB queue table ARN."
  type        = string
}

variable "cognito_issuer" {
  description = "Cognito user pool issuer URL."
  type        = string
}

variable "cognito_client_ids" {
  description = "App client IDs accepted by the JWT authorizer."
  type        = list(string)
}

variable "loadtest_issuer" {
  description = "demo load-test window ONLY: the test issuer the JWT authorizer trusts INSTEAD of Cognito. Empty = Cognito (dev, always)."
  type        = string
  default     = ""
}

variable "loadtest_audience" {
  description = "aud claim of the test issuer's tokens (used only with loadtest_issuer)."
  type        = string
  default     = ""

  validation {
    condition     = var.loadtest_issuer == "" || var.loadtest_audience != ""
    error_message = "loadtest_issuer needs loadtest_audience."
  }
}

variable "cors_allow_origins" {
  description = "Browser origins allowed to call the queue API."
  type        = list(string)
  default     = []
}

variable "throttle_burst" {
  description = "API Gateway burst limit (requests)."
  type        = number
  default     = 2000
}

variable "throttle_rate" {
  description = "API Gateway steady rate limit (requests per second)."
  type        = number
  default     = 1000
}

variable "sequencer_max_concurrency" {
  description = "Max parallel sequencer invocations (SQS scaling; minimum 2)."
  type        = number
  default     = 2
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

variable "schedules_enabled" {
  description = "Run the every-minute queue schedules (starter, later valve)."
  type        = bool
  default     = true
}

variable "secrets_prefix" {
  description = "Secrets Manager name prefix, e.g. surgegate/dev."
  type        = string
}

variable "token_key_version" {
  description = "Version of the queue-token key; increase to rotate."
  type        = number
  default     = 1
}

variable "pass_key_version" {
  description = "Version of the booking-pass key; increase to rotate."
  type        = number
  default     = 1
}

variable "sale_events_stream" {
  description = "Kinesis stream name for sale events (empty = do not publish)."
  type        = string
  default     = ""
}

variable "sale_events_arn" {
  description = "Kinesis stream ARN for the producers' IAM policies."
  type        = string
  default     = ""
}

variable "origin_verify_header_name" {
  description = "Header CloudFront adds on the queue origin."
  type        = string
  default     = "X-Origin-Verify"
}

variable "origin_verify_secret" {
  description = "Its value (shared with the ALB origin). Empty = no check possible."
  type        = string
  default     = ""
  sensitive   = true
}

variable "origin_verify_required" {
  description = "Refuse API requests without the header (i.e. sent straight to execute-api, bypassing CloudFront and WAF)."
  type        = bool
  default     = false
}

variable "booking_alb_arn_suffix" {
  description = "Booking API ALB ARN suffix (backpressure reads its metrics); null while down."
  type        = string
  default     = null
}

variable "booking_target_group_arn_suffix" {
  description = "Booking API target group ARN suffix; null while down."
  type        = string
  default     = null
}

variable "backpressure_slow_p95" {
  description = "Booking p95 (seconds) above which backpressure lowers the admission rate. 0.5 = the SLO; a tiny value only for a live test."
  type        = number
  default     = 0.5
}
