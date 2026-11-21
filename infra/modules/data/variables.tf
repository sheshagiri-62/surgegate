variable "name" {
  description = "Name prefix, e.g. surgegate-dev."
  type        = string
}

variable "secrets_prefix" {
  description = "Secrets Manager name prefix, e.g. surgegate/dev (secrets go under <prefix>/data/...)."
  type        = string
}

variable "vpc_id" {
  description = "VPC from the network module."
  type        = string
}

variable "data_subnet_ids" {
  description = "Data subnets (no internet route) for RDS and ElastiCache."
  type        = list(string)
}

variable "compute_enabled" {
  description = "Hourly-billed part on/off: RDS instance and ElastiCache. make down = false (RDS final snapshot kept)."
  type        = bool
  default     = true
}

variable "client_security_group_ids" {
  description = "Security groups allowed to reach PostgreSQL and Redis (EKS nodes). Empty when the cluster is down."
  type        = list(string)
  default     = []
}

variable "restore_snapshot_id" {
  description = "RDS snapshot to create the instance from (newest final snapshot, passed by make up). Empty = new empty database."
  type        = string
  default     = ""
}

variable "pg_engine_version" {
  description = "PostgreSQL major version (RDS picks the newest minor; auto minor upgrades on)."
  type        = string
  default     = "18"
}

variable "pg_instance_class" {
  description = "RDS instance class. db.t4g.micro is the smallest Graviton class."
  type        = string
  default     = "db.t4g.micro"
}

variable "pg_allocated_storage_gb" {
  description = "RDS gp3 storage (20 GiB is the gp3 minimum)."
  type        = number
  default     = 20
}

variable "pg_multi_az" {
  description = "Multi-AZ standby (demo only; dev is single-AZ)."
  type        = bool
  default     = false
}

variable "pg_backup_retention_days" {
  description = "Automated backups / point-in-time recovery window."
  type        = number
  default     = 1
}

variable "redis_node_type" {
  description = "ElastiCache node type."
  type        = string
  default     = "cache.t4g.micro"
}

variable "redis_engine_version" {
  description = "Redis OSS engine version."
  type        = string
  default     = "7.1"
}

variable "redis_replicas" {
  description = "Read replicas in addition to the primary (dev 0, demo 1)."
  type        = number
  default     = 0
}

variable "buckets" {
  description = "S3 buckets to create (<project>-<env>-<name>-<account>)."
  type        = list(string)
  default     = ["tickets", "seatmaps"]
}

variable "bucket_noncurrent_days" {
  description = "Days to keep old object versions."
  type        = number
  default     = 30
}

variable "tags" {
  description = "Extra tags (Project and Env come from provider default_tags)."
  type        = map(string)
  default     = {}
}

variable "queue_table_deletion_protection" {
  description = "Protect the DynamoDB queue table from deletion."
  type        = bool
  default     = true
}

variable "queue_table_pitr" {
  description = "Point-in-time recovery for the queue table (demo: true)."
  type        = bool
  default     = false
}
