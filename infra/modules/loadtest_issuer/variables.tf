variable "name" {
  description = "Name prefix, e.g. surgegate-demo."
  type        = string
}

variable "secrets_prefix" {
  description = "Secrets Manager / SSM prefix, e.g. surgegate/demo."
  type        = string
}

variable "source_dir" {
  description = "services/queue/src (holds sg_queue/loadtest_issuer.py)."
  type        = string
}

variable "cluster_name" {
  description = "EKS cluster the k6 pods run in (Pod Identity association)."
  type        = string
}

variable "k6_namespace" {
  description = "Namespace of the k6 Jobs."
  type        = string
  default     = "loadtest"
}

variable "k6_service_account" {
  description = "Service account of the k6 Jobs."
  type        = string
  default     = "k6"
}

variable "tags" {
  description = "Extra tags (Project/Env come from the provider's default_tags)."
  type        = map(string)
  default     = {}
}
