variable "name" {
  description = "Cluster name, e.g. surgegate-dev."
  type        = string
}

variable "kubernetes_version" {
  description = "EKS Kubernetes version (standard support only; extended support costs 6x more)."
  type        = string
  default     = "1.37"
}

variable "vpc_id" {
  description = "VPC from the network module."
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnets (one per AZ) for nodes, pods and the control-plane ENIs."
  type        = list(string)
}

variable "node_instance_types" {
  description = "Instance types for the managed node group."
  type        = list(string)
  default     = ["t3.medium"]
}

variable "node_min_size" {
  description = "Minimum nodes."
  type        = number
  default     = 1
}

variable "node_desired_size" {
  description = "Nodes to start with."
  type        = number
  default     = 2
}

variable "node_max_size" {
  description = "Maximum nodes (keep vCPUs within the EC2 On-Demand quota)."
  type        = number
  default     = 3
}

variable "node_disk_size_gb" {
  description = "Root EBS volume per node (gp3)."
  type        = number
  default     = 20
}

variable "admin_principal_arns" {
  description = "IAM principals with cluster-admin access (you and the CI apply role)."
  type        = list(string)
}

variable "viewer_principal_arns" {
  description = "IAM principals with read-only access to all objects (the CI plan role, so helm plans work)."
  type        = list(string)
  default     = []
}

variable "log_retention_days" {
  description = "CloudWatch retention for control-plane logs."
  type        = number
  default     = 14
}

variable "lbc_chart_version" {
  description = "aws-load-balancer-controller Helm chart version."
  type        = string
  default     = "3.6.3"
}

variable "lbc_replicas" {
  description = "Load Balancer Controller replicas (1 in dev, 2 in demo)."
  type        = number
  default     = 1
}

variable "argocd_chart_version" {
  description = "argo-cd Helm chart version."
  type        = string
  default     = "10.18.2"
}

variable "argocd_apps_chart_version" {
  description = "argocd-apps Helm chart version (creates the root Application)."
  type        = string
  default     = "2.0.8"
}

variable "gitops_repo_url" {
  description = "Git repository Argo CD watches (public, so no credentials needed)."
  type        = string
}

variable "gitops_path" {
  description = "Folder of Argo CD Application manifests (app of apps)."
  type        = string
  default     = "deploy/argocd"
}

variable "gitops_revision" {
  description = "Branch Argo CD follows."
  type        = string
  default     = "main"
}

variable "tags" {
  description = "Extra tags (Project and Env come from provider default_tags)."
  type        = map(string)
  default     = {}
}

variable "enable_karpenter" {
  description = "Karpenter for burst capacity (demo). dev keeps only the managed node group."
  type        = bool
  default     = false
}

variable "karpenter_chart_version" {
  description = "Karpenter Helm chart (oci://public.ecr.aws/karpenter/karpenter)."
  type        = string
  default     = "1.15.3"
}

variable "karpenter_cpu_limit" {
  description = "Most vCPUs Karpenter may launch in total (keeps the account's EC2 vCPU quota safe)."
  type        = number
  default     = 6
}

variable "karpenter_instance_types" {
  description = "Instance types Karpenter may launch (small, burstable; Spot preferred when available)."
  type        = list(string)
  default     = ["t3.medium", "t3a.medium", "t3.large", "t3a.large"]
}

variable "enable_container_insights" {
  description = "EKS add-on amazon-cloudwatch-observability: Container Insights (enhanced), Fluent Bit pod logs, OTLP traces -> X-Ray."
  type        = bool
  default     = false
}

variable "cloudwatch_addon_version" {
  description = "amazon-cloudwatch-observability add-on version (default for Kubernetes 1.37 on 25 Nov 2026)."
  type        = string
  default     = "v8.0.1-eksbuild.1"
}

variable "container_log_retention_days" {
  description = "Retention of the Container Insights log groups (application, dataplane, host, performance)."
  type        = number
  default     = 7
}
