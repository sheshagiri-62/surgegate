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
