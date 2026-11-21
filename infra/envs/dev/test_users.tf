# ---------------------------------------------------------------------------
# dev-only test users (never in demo): two organisers in DIFFERENT tenants and one buyer.
# Used by integration checks (cross-tenant test) and scripts. Passwords are random and kept in
# Secrets Manager (surgegate/dev/test-users); emails use the reserved .test domain and Cognito
# sends nothing (password set by admin, email marked verified).
# ---------------------------------------------------------------------------
locals {
  test_users = {
    organiser_a = { email = "organiser-a@surgegate.test", group = "organiser", tenant = "a" }
    organiser_b = { email = "organiser-b@surgegate.test", group = "organiser", tenant = "b" }
    buyer_1     = { email = "buyer-1@surgegate.test", group = "buyer", tenant = null }
  }
}

resource "random_uuid" "test_tenant" {
  for_each = toset(["a", "b"])
}

resource "random_password" "test_user" {
  for_each    = local.test_users
  length      = 24
  min_upper   = 2
  min_lower   = 2
  min_numeric = 2
  special     = false
}

resource "aws_cognito_user" "test" {
  for_each     = local.test_users
  user_pool_id = module.identity.user_pool_id
  username     = each.value.email
  password     = random_password.test_user[each.key].result # permanent password, no email
  attributes = merge(
    { email = each.value.email, email_verified = "true" },
    each.value.tenant == null ? {} : { tenant_id = random_uuid.test_tenant[each.value.tenant].result },
  )
}

resource "aws_cognito_user_in_group" "test" {
  for_each     = local.test_users
  user_pool_id = module.identity.user_pool_id
  group_name   = each.value.group
  username     = aws_cognito_user.test[each.key].username
}

resource "aws_secretsmanager_secret" "test_users" {
  name                    = "${var.project}/${local.env}/test-users"
  description             = "dev test users (email, password, group, tenant_id) for scripts and tests"
  recovery_window_in_days = 7
  tags                    = { Component = "identity" }
}

resource "aws_secretsmanager_secret_version" "test_users" {
  secret_id = aws_secretsmanager_secret.test_users.id
  secret_string = jsonencode({
    client_id = module.identity.client_ids["test"]
    users = { for k, u in local.test_users : k => {
      email     = u.email
      password  = random_password.test_user[k].result
      group     = u.group
      tenant_id = u.tenant == null ? null : random_uuid.test_tenant[u.tenant].result
    } }
  })
}
