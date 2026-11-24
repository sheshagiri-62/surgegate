variable "name" {
  description = "Name prefix, e.g. surgegate-dev."
  type        = string
}

variable "stream_enabled" {
  description = "Create the Kinesis stream and the Pipe (hourly; make up / make down)."
  type        = bool
  default     = false
}

variable "shard_count" {
  description = "Provisioned shards (1 shard = 1,000 records/s or 1 MB/s of writes)."
  type        = number
  default     = 1
}

variable "archive_days" {
  description = "EventBridge archive retention (replay)."
  type        = number
  default     = 7
}

variable "log_retention_days" {
  description = "Retention of the sale-events log group."
  type        = number
  default     = 7
}

variable "tags" {
  description = "Extra tags."
  type        = map(string)
  default     = {}
}

variable "consumers_source_dir" {
  description = "Directory holding the sg_consumers package (services/event-consumers/src)."
  type        = string
}

variable "secrets_prefix" {
  description = "Secrets Manager prefix, e.g. surgegate/dev."
  type        = string
}

variable "queue_table_name" {
  description = "Waiting-room table (the dashboard shows status and admission rate)."
  type        = string
}

variable "queue_table_arn" {
  description = "ARN of the waiting-room table."
  type        = string
}

variable "alerts_topic_arn" {
  description = "SNS topic for the consumers' failure alarm."
  type        = string
}

variable "analytics_bucket_name" {
  description = "S3 bucket for analytics objects and Athena results (SSE-KMS)."
  type        = string
}

variable "kms_key_arn" {
  description = "Data KMS key (analytics bucket and Athena results)."
  type        = string
}
