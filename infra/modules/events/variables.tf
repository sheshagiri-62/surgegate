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
