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
