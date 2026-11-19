output "vpc_id" {
  description = "VPC ID."
  value       = aws_vpc.this.id
}

output "vpc_cidr_block" {
  description = "VPC CIDR block."
  value       = aws_vpc.this.cidr_block
}

output "azs" {
  description = "Availability Zones used, in subnet order."
  value       = var.azs
}

output "public_subnet_ids" {
  description = "Public subnet IDs (ALB, NAT)."
  value       = aws_subnet.public[*].id
}

output "private_subnet_ids" {
  description = "Private subnet IDs (EKS nodes and pods, Lambdas in the VPC)."
  value       = aws_subnet.private[*].id
}

output "data_subnet_ids" {
  description = "Data subnet IDs (RDS, ElastiCache); no internet route."
  value       = aws_subnet.data[*].id
}

output "private_route_table_ids" {
  description = "Private route table IDs, one per AZ."
  value       = aws_route_table.private[*].id
}

output "data_route_table_id" {
  description = "Data route table ID."
  value       = aws_route_table.data.id
}

output "nat_gateway_ids" {
  description = "NAT gateway IDs (empty when enable_nat_gateway = false)."
  value       = aws_nat_gateway.this[*].id
}

output "nat_public_ips" {
  description = "Elastic IPs of the NAT gateways (the VPC's outbound IPs)."
  value       = aws_eip.nat[*].public_ip
}

output "gateway_endpoint_ids" {
  description = "Gateway endpoint IDs by service (s3, dynamodb)."
  value       = { for k, v in aws_vpc_endpoint.gateway : k => v.id }
}
