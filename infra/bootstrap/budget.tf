# ---------------------------------------------------------------------------
# Monthly cost budget (CLAUDE.md: project budget under $50, alerts at $15 / $30 / $45).
# Created by hand on Day 1, imported here on 25 Nov. It now counts usage BEFORE credits:
# with credits included it showed $0.00 while real usage was ~$13, so no alert could ever fire.
# Recipients come only from the uncommitted budget.auto.tfvars (never in Git or a CI plan).
# ---------------------------------------------------------------------------
import {
  to = aws_budgets_budget.monthly
  id = "${local.account_id}:surgegate-monthly"
}

resource "aws_budgets_budget" "monthly" {
  name         = "surgegate-monthly"
  budget_type  = "COST"
  limit_amount = "45.0"
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  cost_types {
    include_credit             = false # track usage before credits (credits hide real spend)
    include_refund             = false
    include_discount           = true
    include_tax                = true
    include_subscription       = true
    include_support            = true
    include_other_subscription = true
    include_recurring          = true
    include_upfront            = true
    use_amortized              = false
    use_blended                = false
  }

  dynamic "notification" {
    for_each = toset(["15", "30", "45"])
    content {
      comparison_operator        = "GREATER_THAN"
      notification_type          = "ACTUAL"
      threshold                  = tonumber(notification.value)
      threshold_type             = "ABSOLUTE_VALUE"
      subscriber_email_addresses = var.budget_alert_emails
    }
  }

  # Early warning: the month is forecast to go over $45.
  notification {
    comparison_operator        = "GREATER_THAN"
    notification_type          = "FORECASTED"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    subscriber_email_addresses = var.budget_alert_emails
  }

  # CI plans without the uncommitted tfvars, so it would show (and post as a PR comment) a diff
  # removing the recipients. Notifications are applied by hand only: to change them, remove this
  # line for one local apply with budget.auto.tfvars present, then put it back.
  lifecycle {
    ignore_changes = [notification]
  }
}
