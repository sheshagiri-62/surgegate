# infra/bootstrap

Applied **once, by hand** (never by CI). Creates what every other Terraform root and pipeline needs:

| Resource | Purpose |
| --- | --- |
| S3 bucket `surgegate-tfstate-<account-id>` | Remote state for all roots; versioned, encrypted, private, TLS-only. Locking uses the native S3 lock file (`use_lockfile = true`), so there's no DynamoDB table |
| GitHub OIDC provider | Lets GitHub Actions get short-lived AWS credentials without stored keys |
| `surgegate-gha-plan` role | `ReadOnlyAccess` plus state lock files; pull requests from this repo only |
| `surgegate-gha-apply` role | `AdministratorAccess` with explicit denies (Organizations/account, users and access keys, CI roles, OIDC provider, state bucket); `main` or the `dev`/`demo` environments only |

## Using the backend in other roots

```hcl
terraform {
  backend "s3" {
    bucket       = "surgegate-tfstate-968077439619"
    key          = "envs/dev/terraform.tfstate"   # one key per root
    region       = "ap-south-1"
    encrypt      = true
    use_lockfile = true
  }
}
```

## Re-applying

```bash
export AWS_PROFILE=surgegate        # after: aws login --profile surgegate
terraform init
terraform fmt -check && terraform validate && tflint --config=../../.tflint.hcl
terraform plan -out=bootstrap.tfplan
terraform apply bootstrap.tfplan
```

## Tearing down (end of project only)

The bucket has `prevent_destroy`. To remove everything: migrate state back to local
(delete `backend.tf`, `terraform init -migrate-state`), empty every object version in the bucket,
remove `prevent_destroy`, then `terraform destroy`.
