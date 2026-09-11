# Cost guardrail: this account has twice run a billed-by-the-hour resource
# for weeks without noticing (the OpenSearch domain, then a stray API Gateway
# cache in ca-central-1). $20/month is well above what the current
# pay-per-use architecture should ever cost, so any alert here means
# something is misconfigured, not just "a busy day".
resource "aws_budgets_budget" "monthly_cost_guardrail" {
  name         = "${var.project_name}-monthly-cost-guardrail"
  budget_type  = "COST"
  limit_amount = "20"
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.budget_alert_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.budget_alert_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.budget_alert_email]
  }
}
