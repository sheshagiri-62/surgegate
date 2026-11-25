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
# (AWS_PROFILE locally, OIDC role credentials in CI), fetched through a small retrying wrapper
# (infra/scripts/eks-token.sh; see why there). Empty when the cluster is down.
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
      command     = var.token_shell
      args        = ["${path.root}/../../scripts/eks-token.sh", local.name, var.region]
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

  # CloudWatch agent add-on: dev keeps only its OTLP receiver (traces -> X-Ray). Container
  # Insights metrics + pod logs measured ~$0.60/day, so they're on in demo only (25 Nov decision).
  enable_container_insights  = true
  container_insights_metrics = false

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
  web_acl_arn            = var.enable_waf ? module.waf[0].web_acl_arn : null
  origin_enabled         = var.enable_eks
  vpc_id                 = module.network.vpc_id
  public_subnet_ids      = module.network.public_subnet_ids
  private_subnet_ids     = module.network.private_subnet_ids
  node_security_group_id = try(module.eks[0].node_security_group_id, null)
  target_group_name      = "${local.name}-booking-api"
  origin_verify_secret   = aws_secretsmanager_secret_version.origin_verify.secret_string
  domain_name            = var.domain_name
  # /queue/* -> API Gateway, /queue/*/serving cached 5 s (pending CloudFront verification)
  queue_api_domain  = trimprefix(module.queue.api_endpoint, "https://")
  queue_api_enabled = true
  # TEMPORARY demo access to the ALB: pass -var=debug_ingress_cidr=<ip>/32, then apply without it.
  debug_ingress_cidr = var.debug_ingress_cidr
  # Buyer site on S3 is the default behaviour; everything served by the ALB is listed here
  # (no cache, cookies/headers forwarded). /book/* and /queue/* have their own behaviours.
  buyer_site_enabled = true
  alb_path_patterns = [
    "/organiser", "/organiser/*",          # organiser dashboard (SSR + session cookie)
    "/org/*", "/me", "/me/*", "/orders/*", # booking API
    "/webhooks/*", "/healthz",
    "/mockpay/checkout/*", # mock-pay checkout page (ADR 004)
  ]
  # mock-pay (ADR 004): ONLY the public checkout page; /v1/* and /mockpay/test/* stay in-cluster.
  extra_routes = {
    "mock-pay" = { path_patterns = ["/mockpay/checkout/*"], priority = 5 }
    # Organiser dashboard (Next.js SSR, Day 8 Task 4)
    "organiser" = {
      path_patterns     = ["/organiser", "/organiser/*"]
      priority          = 6
      health_check_path = "/organiser/api/healthz"
    }
  }
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

  compute_enabled = var.enable_data
  client_security_group_ids = concat(
    var.enable_eks ? [module.eks[0].node_security_group_id] : [],
    [module.async.release_security_group_id], # hold-release Lambda
  )
  restore_snapshot_id = var.restore_snapshot_id

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

# ---------------------------------------------------------------------------
# Waiting room: API Gateway HTTP API + Lambda + SQS (+ DynamoDB table in the data module).
# Pay per request, persistent: make down leaves it (no hourly cost).
# ---------------------------------------------------------------------------
module "queue" {
  source = "../../modules/queue"

  name               = local.name
  secrets_prefix     = "${var.project}/${local.env}"
  source_dir         = "${path.root}/../../../services/queue/src"
  table_name         = module.data.queue_table_name
  table_arn          = module.data.queue_table_arn
  cognito_issuer     = module.identity.issuer
  cognito_client_ids = values(module.identity.client_ids)
  cors_allow_origins = ["http://localhost:3000", "https://d1t9vww2xtyvsz.cloudfront.net"] # laptop app; the CloudFront site is same-origin
  sale_events_stream = module.events.stream_name
  sale_events_arn    = module.events.stream_arn

  # Only requests through our CloudFront (and so through WAF) once required (Day 9 Task 2).
  origin_verify_secret   = aws_secretsmanager_secret_version.origin_verify.secret_string
  origin_verify_required = var.queue_origin_verify_required

  # Backpressure (Day 10 Task 1) watches the booking API through its ALB metrics.
  booking_alb_arn_suffix          = module.edge.alb_arn_suffix
  booking_target_group_arn_suffix = module.edge.target_group_arn_suffix
}

# ---------------------------------------------------------------------------
# WAF on CloudFront (Day 9 Task 2). A CloudFront web ACL lives in us-east-1.
# Fixed fees are prorated hourly: $5/month ACL + $1/month per rule + $10/month Bot Control.
# ---------------------------------------------------------------------------
module "waf" {
  source = "../../modules/waf"
  count  = var.enable_waf ? 1 : 0

  providers = {
    aws = aws.us_east_1
  }

  name              = local.name
  load_test_enabled = var.waf_load_test_enabled
  load_test_cidrs   = var.waf_load_test_cidrs
}

# ---------------------------------------------------------------------------
# Sale events (ADR 002): Kinesis "sale-events" (hourly: make up / make down) + EventBridge bus,
# archive and a log-group rule (persistent, pay per event).
# ---------------------------------------------------------------------------
module "events" {
  source = "../../modules/events"

  name           = local.name
  stream_enabled = var.enable_kinesis
  shard_count    = 1

  # Consumers (Day 8 Task 3): live dashboard over WebSocket
  consumers_source_dir = "${path.root}/../../../services/event-consumers/src"
  secrets_prefix       = "${var.project}/${local.env}"
  queue_table_name     = module.data.queue_table_name
  queue_table_arn      = module.data.queue_table_arn
  alerts_topic_arn     = module.async.alerts_topic_arn
  # analytics (Day 8 Task 3b)
  analytics_bucket_name = module.data.bucket_names["analytics"]
  kms_key_arn           = module.data.kms_key_arn
}


# ---------------------------------------------------------------------------
# Async work: the 10-minute hold timer (Step Functions + release Lambda in the VPC).
# Pay per use; persistent.
# ---------------------------------------------------------------------------
module "async" {
  source = "../../modules/async"

  name               = local.name
  source_dir         = "${path.root}/../../../services/workers/src"
  vpc_id             = module.network.vpc_id
  private_subnet_ids = module.network.private_subnet_ids
  db_instance_id     = "${local.name}-pg"
  kms_key_arn        = module.data.kms_key_arn
  sale_events_stream = module.events.stream_name
  sale_events_arn    = module.events.stream_arn
  # DLQ alarm email: address only in the uncommitted alerts.auto.tfvars (never in Git).
  alert_email_enabled = true
  alert_email         = var.alert_email

  # Ticket worker (Day 8 Task 1)
  secrets_prefix        = "${var.project}/${local.env}"
  tickets_bucket_name   = module.data.bucket_names["tickets"]
  tickets_bucket_arn    = "arn:aws:s3:::${module.data.bucket_names["tickets"]}"
  event_bus_name        = module.events.bus_name
  cognito_user_pool_id  = module.identity.user_pool_id
  cognito_user_pool_arn = module.identity.user_pool_arn
  ses_identity_enabled  = true
  ses_sender            = var.ses_sender            # uncommitted alerts.auto.tfvars
  ses_sandbox_recipient = var.ses_sandbox_recipient # uncommitted alerts.auto.tfvars
  sweep_enabled         = var.enable_data
}

# ---------------------------------------------------------------------------
# Observability (Day 9 Task 3): the "sale room" CloudWatch dashboard (free: first 3 dashboards).
# ---------------------------------------------------------------------------
module "observability" {
  source = "../../modules/observability"

  name                    = local.name
  region                  = var.region
  cluster_name            = local.name
  distribution_id         = coalesce(module.edge.distribution_id, "none")
  web_acl_name            = local.name
  queue_api_id            = module.queue.api_id
  queue_table             = module.data.queue_table_name
  stream_name             = module.events.stream_name
  alb_arn_suffix          = module.edge.alb_arn_suffix
  target_group_arn_suffix = module.edge.target_group_arn_suffix

  # SLO alarms (Day 9 Task 4) -> the existing alerts topic (email)
  alerts_topic_arn = module.async.alerts_topic_arn
}
