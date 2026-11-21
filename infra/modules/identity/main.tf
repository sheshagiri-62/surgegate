# Cognito: buyer and organiser accounts, JWTs with role (cognito:groups) and tenant (tenant_id).
# Persistent: no hourly cost. Essentials tier (needed for email OTP sign-in and access-token
# customisation) is free up to 10,000 monthly active users; Cognito's own email sender is free
# (50 emails/day), enough for dev.

data "aws_caller_identity" "current" {}

locals {
  tags = merge(var.tags, { Component = "identity" })
}

resource "aws_cognito_user_pool" "this" {
  name                = var.name
  user_pool_tier      = "ESSENTIALS"
  deletion_protection = var.deletion_protection ? "ACTIVE" : "INACTIVE"

  # Sign in with the email address; it must be verified (one-time code by email).
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]
  username_configuration {
    case_sensitive = false
  }

  # Passwordless "email + OTP" (blueprint feature 1); password kept for scripts and tests.
  sign_in_policy {
    allowed_first_auth_factors = ["EMAIL_OTP", "PASSWORD"]
  }

  password_policy {
    minimum_length                   = 12
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = false
    temporary_password_validity_days = 3
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  email_configuration {
    email_sending_account = "COGNITO_DEFAULT" # switch to SES on Day 8 (ticket emails)
  }

  # Buyers may sign up themselves; organisers are created by an admin (they join a tenant).
  admin_create_user_config {
    allow_admin_create_user_only = false
  }

  # Tenant of an organiser. Only admins can set it: no app client gets write access.
  schema {
    name                     = "tenant_id"
    attribute_data_type      = "String"
    mutable                  = true
    developer_only_attribute = false
    required                 = false
    string_attribute_constraints {
      min_length = 36
      max_length = 36 # a UUID
    }
  }

  lambda_config {
    pre_token_generation_config {
      lambda_arn     = aws_lambda_function.pre_token.arn
      lambda_version = "V2_0" # V2 can add claims to the ACCESS token
    }
  }

  tags = local.tags

  lifecycle {
    # Cognito does not allow changing a custom attribute after creation.
    ignore_changes = [schema]
  }
}

# Roles. Group membership is set only by an admin, so a buyer cannot make themselves an organiser.
resource "aws_cognito_user_group" "buyer" {
  name         = "buyer"
  user_pool_id = aws_cognito_user_pool.this.id
  description  = "Fans buying tickets"
  precedence   = 20
}

resource "aws_cognito_user_group" "organiser" {
  name         = "organiser"
  user_pool_id = aws_cognito_user_pool.this.id
  description  = "Organisers managing their tenant's events"
  precedence   = 10
}

# --- App clients ------------------------------------------------------------------
# Browser apps are public clients (no secret; a secret cannot be kept in a browser).
# Read-only access to custom:tenant_id; write access only to standard profile attributes.
locals {
  web_clients = {
    buyer_web     = "${var.name}-buyer-web"
    organiser_web = "${var.name}-organiser-web"
  }
}

resource "aws_cognito_user_pool_client" "web" {
  for_each     = local.web_clients
  name         = each.value
  user_pool_id = aws_cognito_user_pool.this.id

  generate_secret               = false
  explicit_auth_flows           = ["ALLOW_USER_AUTH", "ALLOW_USER_SRP_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"]
  prevent_user_existence_errors = "ENABLED"
  enable_token_revocation       = true
  auth_session_validity         = 5 # minutes to enter the email code

  access_token_validity  = 60
  id_token_validity      = 60
  refresh_token_validity = 7
  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }

  read_attributes  = ["email", "email_verified", "name", "custom:tenant_id"]
  write_attributes = ["email", "name"]
}

# Dev-only client for scripts, integration checks and load tests: username + password.
resource "aws_cognito_user_pool_client" "test" {
  count        = var.enable_test_client ? 1 : 0
  name         = "${var.name}-test"
  user_pool_id = aws_cognito_user_pool.this.id

  generate_secret               = false
  explicit_auth_flows           = ["ALLOW_USER_PASSWORD_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"]
  prevent_user_existence_errors = "ENABLED"
  enable_token_revocation       = true

  access_token_validity  = 60
  id_token_validity      = 60
  refresh_token_validity = 1
  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }

  read_attributes  = ["email", "email_verified", "name", "custom:tenant_id"]
  write_attributes = ["name"]
}

# --- Pre-token-generation Lambda (adds tenant_id to the access token) ---------------
data "archive_file" "pre_token" {
  type        = "zip"
  source_file = "${path.module}/lambda/pre_token.py"
  output_path = "${path.module}/.build/pre_token.zip"
  # Fixed file mode: otherwise Windows and Linux (CI) build different zips -> perpetual diff.
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

resource "aws_iam_role" "pre_token" {
  name               = "${var.name}-cognito-pre-token"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
  tags               = local.tags
}

resource "aws_cloudwatch_log_group" "pre_token" {
  name              = "/aws/lambda/${var.name}-cognito-pre-token"
  retention_in_days = 7
  tags              = local.tags
}

data "aws_iam_policy_document" "pre_token_logs" {
  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.pre_token.arn}:*"]
  }
}

resource "aws_iam_role_policy" "pre_token_logs" {
  name   = "logs"
  role   = aws_iam_role.pre_token.id
  policy = data.aws_iam_policy_document.pre_token_logs.json
}

resource "aws_lambda_function" "pre_token" {
  function_name    = "${var.name}-cognito-pre-token"
  description      = "Cognito pre-token-generation V2: tenant_id claim"
  role             = aws_iam_role.pre_token.arn
  runtime          = "python3.12"
  architectures    = ["arm64"]
  handler          = "pre_token.handler"
  filename         = data.archive_file.pre_token.output_path
  source_code_hash = data.archive_file.pre_token.output_base64sha256
  memory_size      = 128
  timeout          = 3

  logging_config {
    log_format = "JSON"
    log_group  = aws_cloudwatch_log_group.pre_token.name
  }

  tags       = local.tags
  depends_on = [aws_iam_role_policy.pre_token_logs]
}

resource "aws_lambda_permission" "cognito" {
  statement_id   = "AllowCognitoInvoke"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.pre_token.function_name
  principal      = "cognito-idp.amazonaws.com"
  source_arn     = aws_cognito_user_pool.this.arn
  source_account = data.aws_caller_identity.current.account_id
}
