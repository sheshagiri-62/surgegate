# dev: small, single NAT, created per work session. make down turns off the hourly parts.
# Credentials come from AWS_PROFILE locally and from OIDC in CI.
provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project = var.project
      Env     = local.env
      # Component is set by each module (network, eks, data, …)
    }
  }
}

# CloudFront only accepts ACM certificates from us-east-1 (used only when domain_name is set).
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"

  default_tags {
    tags = { Project = var.project, Env = local.env }
  }
}

# Helm talks to the cluster with a short-lived token from `aws eks get-token`
# (AWS_PROFILE locally, OIDC role credentials in CI). Empty when the cluster is down.
provider "helm" {
  # Own repo list and cache (gitignored), so a developer's personal `helm repo` setup can't
  # break chart lookups and local runs behave like CI. Charts use their full repository URL.
  repository_config_path = "${path.root}/.helm/repositories.yaml"
  repository_cache       = "${path.root}/.helm/cache"

  kubernetes = {
    host                   = try(module.eks[0].cluster_endpoint, "")
    cluster_ca_certificate = try(base64decode(module.eks[0].cluster_certificate_authority_data), "")
    exec = {
      api_version = "client.authentication.k8s.io/v1beta1"
      command     = "aws"
      args        = ["eks", "get-token", "--cluster-name", local.name, "--region", var.region]
    }
  }
}

data "aws_caller_identity" "current" {}

locals {
  env        = "dev"
  name       = "${var.project}-${local.env}"
  account_id = data.aws_caller_identity.current.account_id
}

module "network" {
  source = "../../modules/network"

  name               = local.name
  cidr_block         = "10.20.0.0/16"
  azs                = ["ap-south-1a", "ap-south-1b"]
  enable_nat_gateway = var.enable_nat_gateway
  nat_gateway_count  = 1 # one shared NAT in dev; demo uses one per AZ
  cluster_name       = local.name
}

# make up: enable_eks = true; make down: enable_eks = false (cluster, nodes, controller destroyed).
module "eks" {
  source = "../../modules/eks"
  count  = var.enable_eks ? 1 : 0

  name               = local.name
  kubernetes_version = "1.37"
  vpc_id             = module.network.vpc_id
  private_subnet_ids = module.network.private_subnet_ids

  node_instance_types = ["t3.medium"] # 2 vCPU / 4 GiB; 3 nodes max = 6 vCPU (quota is 8)
  node_min_size       = 1
  node_desired_size   = 2
  node_max_size       = 3

  admin_principal_arns = [
    "arn:aws:iam::${local.account_id}:user/sheshagiri-admin",
    "arn:aws:iam::${local.account_id}:role/${var.project}-gha-apply",
  ]
  viewer_principal_arns = [
    "arn:aws:iam::${local.account_id}:role/${var.project}-gha-plan",
  ]

  lbc_replicas = 1

  gitops_repo_url = "https://github.com/sheshagiri-62/surgegate.git"
  gitops_path     = "deploy/argocd"
  gitops_revision = "main"

  # default_tags don't reach EC2 instances/volumes launched by the node group's launch
  # template, so pass them explicitly (needed for cost-by-tag reports).
  tags = { Project = var.project, Env = local.env }
}

# ---------------------------------------------------------------------------
# Edge: CloudFront → ALB → booking-api pods (ADR 003)
# ---------------------------------------------------------------------------
# The shared secret CloudFront sends and the ALB requires. Generated once and kept across
# make down/up (Secrets Manager $0.40/month), so the value is stable between sessions.
resource "random_password" "origin_verify" {
  length  = 48
  special = false
}

resource "aws_secretsmanager_secret" "origin_verify" {
  name                    = "${var.project}/${local.env}/edge/origin-verify"
  description             = "Header value CloudFront sends to the ALB (X-Origin-Verify)"
  recovery_window_in_days = 7
  tags                    = { Component = "edge" }
}

resource "aws_secretsmanager_secret_version" "origin_verify" {
  secret_id     = aws_secretsmanager_secret.origin_verify.id
  secret_string = random_password.origin_verify.result
}

# CloudFront is persistent (no hourly cost, stable *.cloudfront.net URL). Only the hourly ALB
# side follows the EKS switch; while dev is down CloudFront answers 503 at the edge.
module "edge" {
  source = "../../modules/edge"

  providers = {
    aws           = aws
    aws.us_east_1 = aws.us_east_1
  }

  name                   = local.name
  cloudfront_enabled     = var.enable_cloudfront
  origin_enabled         = var.enable_eks
  vpc_id                 = module.network.vpc_id
  public_subnet_ids      = module.network.public_subnet_ids
  node_security_group_id = try(module.eks[0].node_security_group_id, null)
  target_group_name      = "${local.name}-booking-api"
  origin_verify_secret   = aws_secretsmanager_secret_version.origin_verify.secret_string
  domain_name            = var.domain_name
}

# ---------------------------------------------------------------------------
# Data: RDS PostgreSQL + ElastiCache Redis (hourly, follow enable_data) and
# KMS, S3, secrets, subnet groups, SGs (persistent). RDS survives make down as a final snapshot.
# ---------------------------------------------------------------------------
module "data" {
  source = "../../modules/data"

  name            = local.name
  secrets_prefix  = "${var.project}/${local.env}"
  vpc_id          = module.network.vpc_id
  data_subnet_ids = module.network.data_subnet_ids

  compute_enabled           = var.enable_data
  client_security_group_ids = var.enable_eks ? [module.eks[0].node_security_group_id] : []
  restore_snapshot_id       = var.restore_snapshot_id

  pg_instance_class = "db.t4g.micro"
  pg_multi_az       = false # dev: single-AZ (demo: Multi-AZ)
  redis_node_type   = "cache.t4g.micro"
  redis_replicas    = 0 # dev: 1 node (demo: primary + replica)
}

# ---------------------------------------------------------------------------
# Identity: Cognito user pool (buyer / organiser groups, tenant_id claim). Persistent, no
# hourly cost; free up to 10,000 monthly active users.
# ---------------------------------------------------------------------------
module "identity" {
  source = "../../modules/identity"

  name               = local.name
  enable_test_client = true # password-auth client for scripts and tests (dev only)
}
