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
  default     = ["booking-api"]
}

variable "keep_images" {
  description = "Images kept per repository; older ones expire."
  type        = number
  default     = 10
}
