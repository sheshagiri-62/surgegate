# ---------------------------------------------------------------------------
# Container Insights (Day 9 Task 3): the amazon-cloudwatch-observability EKS add-on runs the
# CloudWatch agent (node + pod + container metrics, "enhanced observability", billed per
# observation: $0.21 per million in ap-south-1) and Fluent Bit (pod stdout -> CloudWatch Logs,
# $0.67/GB). Its OTLP receiver (4317 gRPC / 4318 HTTP) takes the booking API's OpenTelemetry
# traces and sends them to X-Ray.
# Switched OFF in the add-on because they bill extra and we don't use them: Application Signals
# (per signal), OTLP span metrics and profiles (custom metrics).
# ---------------------------------------------------------------------------
locals {
  # Kept whenever the add-on runs (empty log groups cost nothing; no data deleted on a switch).
  ci_log_groups = var.enable_container_insights ? toset(["application", "dataplane", "host", "performance"]) : toset([])
}

# Created here first so they get a retention: the add-on would create them with "never expire".
resource "aws_cloudwatch_log_group" "container_insights" {
  for_each          = local.ci_log_groups
  name              = "/aws/containerinsights/${var.name}/${each.key}"
  retention_in_days = var.container_log_retention_days
  tags              = local.tags
}

module "cloudwatch_pod_identity" {
  source  = "terraform-aws-modules/eks-pod-identity/aws"
  version = "~> 2.11"
  count   = var.enable_container_insights ? 1 : 0

  name = "${var.name}-cloudwatch-agent"
  # CloudWatchAgentServerPolicy + AWSXrayWriteOnlyAccess
  attach_aws_cloudwatch_observability_policy = true

  associations = {
    agent = {
      cluster_name    = module.eks.cluster_name
      namespace       = "amazon-cloudwatch"
      service_account = "cloudwatch-agent"
    }
  }

  tags = local.tags
}

resource "aws_eks_addon" "cloudwatch" {
  count                       = var.enable_container_insights ? 1 : 0
  cluster_name                = module.eks.cluster_name
  addon_name                  = "amazon-cloudwatch-observability"
  addon_version               = var.cloudwatch_addon_version
  resolve_conflicts_on_create = "OVERWRITE"
  resolve_conflicts_on_update = "OVERWRITE"

  configuration_values = jsonencode({
    # dev: false (traces only, ~$0.60/day saved); demo: true for the test window
    containerInsights  = { enabled = var.container_insights_metrics }
    containerLogs      = { enabled = var.container_insights_metrics }
    applicationSignals = { enabled = false }
    otlp = {
      enabled     = true
      spanMetrics = { enabled = false }
      profiles    = { enabled = false }
    }
  })

  tags = local.tags

  depends_on = [
    aws_cloudwatch_log_group.container_insights,
    module.cloudwatch_pod_identity,
    helm_release.lbc, # nodes and core add-ons are up
  ]
}
