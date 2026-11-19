variable "project" {
  description = "Project name, used as a prefix for every resource."
  type        = string
  default     = "surgegate"
}

variable "region" {
  description = "AWS region for the state bucket."
  type        = string
  default     = "ap-south-1"
}

variable "github_repo" {
  description = "GitHub repository allowed to assume the CI roles, as owner/name."
  type        = string
  default     = "sheshagiri-62/surgegate"
}

variable "apply_subjects" {
  description = "OIDC sub suffixes (after repo:<owner/name>:) allowed to assume the apply role."
  type        = list(string)
  default = [
    "ref:refs/heads/main",
    "environment:dev",
    "environment:demo",
  ]
}

variable "noncurrent_state_days" {
  description = "Days to keep old (non-current) versions of state files."
  type        = number
  default     = 90
}
