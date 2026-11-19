# Lets GitHub Actions swap its short-lived OIDC token for AWS credentials (no stored keys).
# AWS checks GitHub's certificate against its own trusted CA list, so no thumbprint is needed.
resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}
