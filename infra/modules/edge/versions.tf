terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source                = "hashicorp/aws"
      version               = "~> 6.73"
      configuration_aliases = [aws.us_east_1] # ACM certificates for CloudFront live in us-east-1
    }
  }
}
