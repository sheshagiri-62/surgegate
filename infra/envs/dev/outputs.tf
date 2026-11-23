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

output "api_url" {
  description = "Public HTTPS URL of the booking API (stable; 503 while dev is down)."
  value       = module.edge.api_url
}

output "alb_dns_name" {
  description = "ALB DNS name; direct requests are refused (403). Null while dev is down."
  value       = module.edge.alb_dns_name
}

output "nat_public_ips" {
  description = "Outbound public IPs."
  value       = module.network.nat_public_ips
}

output "postgres_endpoint" {
  description = "PostgreSQL endpoint (null while down)."
  value       = module.data.postgres_endpoint
}

output "postgres_master_secret_arn" {
  description = "RDS-managed master credentials in Secrets Manager (null while down)."
  value       = module.data.postgres_master_secret_arn
}

output "redis_primary_endpoint" {
  description = "Redis primary endpoint (TLS + AUTH; null while down)."
  value       = module.data.redis_primary_endpoint
}

output "data_buckets" {
  description = "S3 buckets (tickets, seatmaps)."
  value       = module.data.bucket_names
}

output "cognito_user_pool_id" {
  description = "Cognito user pool ID."
  value       = module.identity.user_pool_id
}

output "cognito_issuer" {
  description = "JWT issuer the booking API accepts."
  value       = module.identity.issuer
}

output "cognito_client_ids" {
  description = "Cognito app client IDs (buyer_web, organiser_web, test)."
  value       = module.identity.client_ids
}

output "queue_api_endpoint" {
  description = "Waiting-room API (API Gateway)."
  value       = module.queue.api_endpoint
}

output "queue_table" {
  description = "DynamoDB waiting-room table."
  value       = module.data.queue_table_name
}

output "sale_events" {
  description = "Sale-events stream, bus and log group."
  value = {
    stream    = module.events.stream_name
    bus       = module.events.bus_name
    log_group = module.events.log_group
  }
}
