output "cluster_name" {
  description = "EKS cluster name."
  value       = module.eks.cluster_name
}

output "cluster_endpoint" {
  description = "Kubernetes API endpoint."
  value       = module.eks.cluster_endpoint
}

output "cluster_certificate_authority_data" {
  description = "Base64 CA bundle for the API endpoint."
  value       = module.eks.cluster_certificate_authority_data
}

output "cluster_version" {
  description = "Kubernetes version."
  value       = module.eks.cluster_version
}

output "node_security_group_id" {
  description = "Security group of the nodes (RDS/Redis will allow this group)."
  value       = module.eks.node_security_group_id
}

output "cluster_security_group_id" {
  description = "Cluster security group created by EKS."
  value       = module.eks.cluster_primary_security_group_id
}

output "lbc_role_arn" {
  description = "IAM role used by the AWS Load Balancer Controller (Pod Identity)."
  value       = module.lbc_pod_identity.iam_role_arn
}
