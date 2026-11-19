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

output "nat_public_ips" {
  description = "Outbound public IPs."
  value       = module.network.nat_public_ips
}
