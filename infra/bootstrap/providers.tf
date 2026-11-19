# Credentials come from the environment: AWS_PROFILE=surgegate locally (aws login),
# OIDC role credentials in GitHub Actions. No profile or keys in code.
provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project   = var.project
      Env       = "shared" # bootstrap serves both dev and demo
      Component = "bootstrap"
    }
  }
}
