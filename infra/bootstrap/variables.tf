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

variable "github_oidc_subject_prefix" {
  description = <<-EOT
    Start of the GitHub OIDC sub claim for this repo. The repo uses GitHub's immutable subject
    format (owner@owner_id/repo@repo_id), so a renamed or re-created repo with the same name
    cannot assume the roles. Check with:
    gh api repos/<owner>/<repo>/actions/oidc/customization/sub
  EOT
  type        = string
  default     = "repo:sheshagiri-62@144677187/surgegate@1463328699"
}

variable "apply_subjects" {
  description = "OIDC sub suffixes (after the subject prefix and ':') allowed to assume the apply role."
  type        = list(string)
  default = [
    "ref:refs/heads/main",
    "environment:dev",
    "environment:demo",
  ]
}

variable "ecr_push_repositories" {
  description = "ECR repositories (names) the build-deploy role may push to."
  type        = list(string)
  default     = ["surgegate/booking-api", "surgegate/mock-pay", "surgegate/organiser"]
}

variable "noncurrent_state_days" {
  description = "Days to keep old (non-current) versions of state files."
  type        = number
  default     = 90
}

variable "site_deploy_envs" {
  description = "Environments whose buyer-site bucket (<project>-<env>-buyer-site-<account>) CI may upload to."
  type        = list(string)
  default     = ["dev"]
}

variable "site_distribution_ids" {
  description = "CloudFront distributions whose cache the site deploy may invalidate (not secret)."
  type        = list(string)
  default     = ["E8H8TXUDV1OG7"] # dev
}

variable "budget_alert_emails" {
  description = "Budget alert recipients. ONLY in the uncommitted budget.auto.tfvars (never in Git)."
  type        = list(string)
  default     = []
  sensitive   = true
}
