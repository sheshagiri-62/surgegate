# Added after the first apply: bootstrap creates this bucket, so its very first run used local
# state, then `terraform init -migrate-state` moved the state here.
terraform {
  backend "s3" {
    bucket       = "surgegate-tfstate-968077439619"
    key          = "bootstrap/terraform.tfstate"
    region       = "ap-south-1"
    encrypt      = true
    use_lockfile = true # S3 native lock file (<key>.tflock); no DynamoDB table
  }
}
