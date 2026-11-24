variable "project" {
  description = "Project name."
  type        = string
  default     = "surgegate"
}

variable "region" {
  description = "AWS region."
  type        = string
  default     = "ap-south-1"
}

variable "enable_nat_gateway" {
  description = "Hourly-billed NAT gateway on/off. make up = true, make down = false."
  type        = bool
  default     = true
}

variable "domain_name" {
  description = "Own domain for api.<domain> (Route 53 + ACM). Empty = CloudFront *.cloudfront.net."
  type        = string
  default     = ""
}

variable "enable_data" {
  description = "Hourly-billed RDS + ElastiCache on/off. make up = true, make down = false (RDS final snapshot kept)."
  type        = bool
  default     = true
}

variable "restore_snapshot_id" {
  description = "RDS snapshot to restore on make up (the newest final snapshot; looked up by the Makefile). Empty = fresh DB."
  type        = string
  default     = ""
}

variable "enable_cloudfront" {
  description = "CloudFront distribution in front of the ALB (ADR 003). Enabled after AWS verified the account (support case 179519256900023, 23 Nov)."
  type        = bool
  default     = true
}

variable "enable_eks" {
  description = "Hourly-billed EKS cluster + nodes on/off. make up = true, make down = false."
  type        = bool
  default     = true

  validation {
    # Nodes pull images and reach AWS APIs through the NAT; without it they never join.
    condition     = !var.enable_eks || var.enable_nat_gateway
    error_message = "enable_eks = true needs enable_nat_gateway = true."
  }
}

variable "token_shell" {
  description = "Shell that runs infra/scripts/eks-token.sh. make passes its own bash's absolute path (on Windows a bare \"bash\" can be the WSL stub)."
  type        = string
  default     = "bash"
}

variable "debug_ingress_cidr" {
  description = "TEMPORARY /32 allowed to reach the ALB directly (demo only; never commit a value)."
  type        = string
  default     = ""
}

variable "enable_kinesis" {
  description = "Kinesis stream sale-events + its Pipe (hourly, about $0.0175/h for 1 shard). make down sets false."
  type        = bool
  default     = true
}

variable "alert_email" {
  description = "Email for alarms (DLQ). Set ONLY in the uncommitted alerts.auto.tfvars or TF_VAR_alert_email."
  type        = string
  default     = ""
  sensitive   = true
}
