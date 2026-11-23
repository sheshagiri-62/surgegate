variable "name" {
  description = "Name prefix, e.g. surgegate-dev."
  type        = string
}

variable "vpc_id" {
  description = "VPC from the network module."
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnets for the internal ALB (CloudFront VPC origin)."
  type        = list(string)
  default     = []
}

variable "public_subnet_ids" {
  description = "Public subnets (one per AZ) for the internet-facing ALB."
  type        = list(string)
}

variable "cloudfront_enabled" {
  description = "Create the CloudFront distribution. false until AWS verifies the account (ADR 003)."
  type        = bool
  default     = true
}

variable "origin_enabled" {
  description = "true = ALB origin exists (dev up). false = no ALB; CloudFront answers 503 at the edge."
  type        = bool
  default     = true
}

variable "node_security_group_id" {
  description = "EKS node security group; pods (VPC CNI) receive ALB traffic through it. Null when down."
  type        = string
  default     = null
}

variable "target_group_name" {
  description = "Fixed target group name; the booking-api chart's TargetGroupBinding refers to it by name."
  type        = string
}

variable "target_port" {
  description = "Container port of the booking API pods."
  type        = number
  default     = 8000
}

variable "health_check_path" {
  description = "ALB health check path."
  type        = string
  default     = "/healthz"
}

variable "origin_verify_header_name" {
  description = "Custom header CloudFront adds and the ALB requires."
  type        = string
  default     = "X-Origin-Verify"
}

variable "origin_verify_secret" {
  description = "Value of the origin header (from Secrets Manager). Never in Git."
  type        = string
  sensitive   = true
}

variable "domain_name" {
  description = "Own domain (e.g. example.com). Empty = use the CloudFront default *.cloudfront.net domain."
  type        = string
  default     = ""
}

variable "api_subdomain" {
  description = "Subdomain for the API when domain_name is set (api.<domain>)."
  type        = string
  default     = "api"
}

variable "price_class" {
  description = "CloudFront price class. PriceClass_200 includes India edge locations."
  type        = string
  default     = "PriceClass_200"
}

variable "tags" {
  description = "Extra tags (Project and Env come from provider default_tags)."
  type        = map(string)
  default     = {}
}

variable "queue_api_domain" {
  description = "Waiting-room API Gateway host (xxx.execute-api.<region>.amazonaws.com); empty = no /queue/* behaviours."
  type        = string
  default     = ""
}

variable "debug_ingress_cidr" {
  description = "TEMPORARY: one /32 allowed to reach the ALB directly (demo of the no-header 403). Empty = none."
  type        = string
  default     = ""
  validation {
    condition     = var.debug_ingress_cidr == "" || endswith(var.debug_ingress_cidr, "/32")
    error_message = "Only a single address (/32) may be opened."
  }
}

variable "extra_routes" {
  description = <<-EOT
    More in-cluster services behind the same ALB: key => {path_patterns, priority,
    health_check_path}. Each gets a target group "<name>-<key>" (pods join it through a
    TargetGroupBinding) and a listener rule that needs BOTH the paths and the origin-verify
    header. Same target port as the booking API, so the existing security-group rules apply.
  EOT
  type = map(object({
    path_patterns     = list(string)
    priority          = number
    health_check_path = optional(string, "/healthz")
  }))
  default = {}
}
