output "vpc_id" {
  description = "dev VPC ID."
  value       = module.network.vpc_id
}

output "public_subnet_ids" {
  description = "Public subnet IDs."
  value       = module.network.public_subnet_ids
}

output "private_subnet_ids" {
  description = "Private subnet IDs."
  value       = module.network.private_subnet_ids
}

output "data_subnet_ids" {
  description = "Data subnet IDs."
  value       = module.network.data_subnet_ids
}

output "nat_gateway_ids" {
  description = "NAT gateway IDs (empty after make down)."
  value       = module.network.nat_gateway_ids
}

output "eks_cluster_name" {
  description = "EKS cluster name (null after make down)."
  value       = try(module.eks[0].cluster_name, null)
}

output "eks_kubeconfig_command" {
  description = "Command to point kubectl at the cluster."
  value       = var.enable_eks ? "aws eks update-kubeconfig --name ${local.name} --region ${var.region}" : null
}

output "nat_public_ips" {
  description = "Outbound public IPs."
  value       = module.network.nat_public_ips
}
