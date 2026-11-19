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

locals {
  env  = "dev"
  name = "${var.project}-${local.env}"
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
