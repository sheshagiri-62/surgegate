terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.73"
      # A CloudFront web ACL must be created in us-east-1: pass the us-east-1 provider as `aws`.
    }
  }
}
