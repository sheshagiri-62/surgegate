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
