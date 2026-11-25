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

variable "services" {
  description = "Services that get an ECR repository (<project>/<service>)."
  type        = list(string)
  default     = ["booking-api", "mock-pay", "organiser"]
}

variable "keep_images" {
  description = "Images kept per repository; older ones expire."
  type        = number
  default     = 10
}

variable "enable_security_services" {
  description = "GuardDuty + Security Hub + Config recorder. `make security-off` sets false (before ~26 Dec 2026, when the free trials end)."
  type        = bool
  default     = true
}
