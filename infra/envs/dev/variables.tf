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
