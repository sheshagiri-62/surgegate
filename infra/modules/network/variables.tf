variable "name" {
  description = "Name prefix for every resource, e.g. surgegate-dev."
  type        = string
}

variable "cidr_block" {
  description = "VPC CIDR. A /16 leaves room for /20 private subnets (EKS pods take VPC IPs)."
  type        = string
  default     = "10.20.0.0/16"

  validation {
    condition     = can(cidrhost(var.cidr_block, 0)) && tonumber(split("/", var.cidr_block)[1]) <= 16
    error_message = "cidr_block must be a valid CIDR of /16 or larger."
  }
}

variable "azs" {
  description = "Availability Zones to use (two for SurgeGate)."
  type        = list(string)

  validation {
    condition     = length(var.azs) >= 2
    error_message = "Use at least two Availability Zones."
  }
}

variable "enable_nat_gateway" {
  description = "Create NAT gateway(s). make down sets this to false to stop the hourly NAT + Elastic IP charge."
  type        = bool
  default     = true
}

variable "nat_gateway_count" {
  description = "1 = one shared NAT (dev, cheap); length(azs) = one per AZ (demo, survives an AZ loss)."
  type        = number
  default     = 1

  validation {
    condition     = var.nat_gateway_count >= 1
    error_message = "nat_gateway_count must be at least 1 (use enable_nat_gateway = false for none)."
  }
}

variable "cluster_name" {
  description = "EKS cluster name, used for the Karpenter subnet discovery tag."
  type        = string
}

variable "tags" {
  description = "Extra tags for every resource (Project and Env come from provider default_tags)."
  type        = map(string)
  default     = {}
}
