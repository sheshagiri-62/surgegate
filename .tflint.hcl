# TFLint config used by pre-commit and by CI (infra-plan.yml).
# Run `tflint --init` once to download the AWS plugin.
config {
  call_module_type = "local"
}

plugin "terraform" {
  enabled = true
  preset  = "recommended"
}

plugin "aws" {
  enabled = true
  version = "0.50.0"
  source  = "github.com/terraform-linters/tflint-ruleset-aws"
}
