variable "name" {
  description = "Name prefix (surgegate-<env>); resource names follow the other modules' conventions."
  type        = string
}

variable "region" {
  description = "Region of the regional metrics."
  type        = string
}

variable "cluster_name" {
  description = "EKS cluster (Container Insights ClusterName)."
  type        = string
}

variable "distribution_id" {
  description = "CloudFront distribution id."
  type        = string
}

variable "web_acl_name" {
  description = "WAF web ACL name (metrics in us-east-1)."
  type        = string
}

variable "queue_api_id" {
  description = "Waiting-room HTTP API id."
  type        = string
}

variable "queue_table" {
  description = "Waiting-room DynamoDB table."
  type        = string
}

variable "stream_name" {
  description = "Kinesis sale-events stream."
  type        = string
}

variable "alb_arn_suffix" {
  description = "ALB ARN suffix; null while the environment is down (ALB widgets hidden)."
  type        = string
  default     = null
}

variable "target_group_arn_suffix" {
  description = "booking-api target group ARN suffix; null while down."
  type        = string
  default     = null
}

variable "alerts_topic_arn" {
  description = "SNS topic every alarm notifies (email subscription in the async module)."
  type        = string
}

variable "runbook_base_url" {
  description = "Where the runbooks are read (alarm descriptions link to docs/runbooks/*.md)."
  type        = string
  default     = "https://github.com/sheshagiri-62/surgegate/blob/main"
}

variable "rds_connections_threshold" {
  description = "Alarm above this many PostgreSQL connections."
  type        = number
  default     = 70
}
