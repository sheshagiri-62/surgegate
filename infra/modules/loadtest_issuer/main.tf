# ---------------------------------------------------------------------------
# Demo-ONLY load-test token issuer (Day 10 Task 4). Exists only for a load-test window:
# enable_loadtest_issuer = true creates it, false REMOVES all of it (key, issuer, k6 role) and
# the demo queue API + booking API go back to trusting only Cognito.
#
#   Secrets Manager  <prefix>/loadtest/issuer-key   private key (put by demo_loadtest.py keygen,
#                                                   never by Terraform: not in state). Read ONLY
#                                                   by the k6 pods (Pod Identity, below).
#   SSM              /<prefix>/loadtest/jwks        the public key (JWKS)
#   Lambda + URL     https://<id>.lambda-url...     serves /.well-known/{openid-configuration,
#                                                   jwks.json}: the token issuer ("iss") that the
#                                                   demo JWT checkers fetch keys from
#
# Tokens: RS256, iss = the URL, aud = "<name>-loadtest", lifetime 1 h, buyer only (the booking
# API forces the buyer role whatever the token says). Cost: Lambda/SSM free tier, the secret
# $0.40/month prorated (deleted with no recovery window when switched off).
# ---------------------------------------------------------------------------
locals {
  tags     = merge(var.tags, { Component = "loadtest" })
  audience = "${var.name}-loadtest"
}

resource "aws_secretsmanager_secret" "key" {
  name                    = "${var.secrets_prefix}/loadtest/issuer-key"
  description             = "Load-test issuer private key (demo, test window only). Value put by tests/load/demo_loadtest.py keygen."
  recovery_window_in_days = 0 # removed at once after the test, no 7-day leftover
  tags                    = local.tags
}

resource "aws_ssm_parameter" "jwks" {
  name        = "/${var.secrets_prefix}/loadtest/jwks"
  description = "Load-test issuer public key (JWKS); written by demo_loadtest.py keygen"
  type        = "String"
  value       = jsonencode({ keys = [] })
  tags        = local.tags

  lifecycle {
    ignore_changes = [value] # the keygen step writes the real public key
  }
}

# --- Issuer Lambda (public half only) --------------------------------------------------------
data "archive_file" "issuer" {
  type             = "zip"
  source_file      = "${var.source_dir}/sg_queue/loadtest_issuer.py"
  output_path      = "${path.module}/.build/loadtest_issuer.zip"
  output_file_mode = "0644"
}

data "aws_iam_policy_document" "lambda_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "issuer" {
  name               = "${var.name}-loadtest-issuer"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
  tags               = local.tags
}

data "aws_iam_policy_document" "issuer" {
  statement {
    sid       = "ReadPublicKeyOnly" # no access to the private key secret
    actions   = ["ssm:GetParameter"]
    resources = [aws_ssm_parameter.jwks.arn]
  }
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.issuer.arn}:*"]
  }
}

resource "aws_iam_role_policy" "issuer" {
  name   = "issuer"
  role   = aws_iam_role.issuer.id
  policy = data.aws_iam_policy_document.issuer.json
}

resource "aws_cloudwatch_log_group" "issuer" {
  name              = "/aws/lambda/${var.name}-loadtest-issuer"
  retention_in_days = 3
  tags              = local.tags
}

resource "aws_lambda_function" "issuer" {
  function_name    = "${var.name}-loadtest-issuer"
  description      = "Load-test issuer: OpenID discovery + JWKS (public key only). Demo test window only."
  role             = aws_iam_role.issuer.arn
  runtime          = "python3.12"
  architectures    = ["arm64"]
  handler          = "loadtest_issuer.handler"
  filename         = data.archive_file.issuer.output_path
  source_code_hash = data.archive_file.issuer.output_base64sha256
  timeout          = 5
  memory_size      = 128

  environment {
    variables = {
      JWKS_PARAM = aws_ssm_parameter.jwks.name
    }
  }

  logging_config {
    log_format = "JSON"
    log_group  = aws_cloudwatch_log_group.issuer.name
  }

  tags       = local.tags
  depends_on = [aws_iam_role_policy.issuer]
}

# Public by design: JWT checkers (API Gateway, the booking API) fetch the public key anonymously.
resource "aws_lambda_function_url" "issuer" {
  function_name      = aws_lambda_function.issuer.function_name
  authorization_type = "NONE"
}

resource "aws_lambda_permission" "url" {
  statement_id           = "PublicFunctionUrl"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = aws_lambda_function.issuer.function_name
  principal              = "*"
  function_url_auth_type = "NONE"
}

resource "aws_lambda_permission" "url_invoke" {
  statement_id             = "PublicFunctionUrlInvoke"
  action                   = "lambda:InvokeFunction"
  function_name            = aws_lambda_function.issuer.function_name
  principal                = "*"
  invoked_via_function_url = true # only through the URL, not a direct Invoke
}

# --- k6 pods: the ONLY reader of the private key (they mint their own 1-hour tokens) ---------
data "aws_iam_policy_document" "pods_trust" {
  statement {
    actions = ["sts:AssumeRole", "sts:TagSession"]
    principals {
      type        = "Service"
      identifiers = ["pods.eks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "k6" {
  name               = "${var.name}-loadtest-k6"
  description        = "k6 load-generator pods: read the load-test issuer key (demo, test window only)"
  assume_role_policy = data.aws_iam_policy_document.pods_trust.json
  tags               = local.tags
}

data "aws_iam_policy_document" "k6" {
  statement {
    sid       = "ReadIssuerKey"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.key.arn]
  }
}

resource "aws_iam_role_policy" "k6" {
  name   = "issuer-key"
  role   = aws_iam_role.k6.id
  policy = data.aws_iam_policy_document.k6.json
}

resource "aws_eks_pod_identity_association" "k6" {
  cluster_name    = var.cluster_name
  namespace       = var.k6_namespace
  service_account = var.k6_service_account
  role_arn        = aws_iam_role.k6.arn
  tags            = local.tags
}
