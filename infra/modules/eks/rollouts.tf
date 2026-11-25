# ---------------------------------------------------------------------------
# Argo Rollouts (Day 10 Task 2): the booking API is released as a canary. Each step's
# AnalysisRun reads the booking-api target group's CloudWatch metrics (5xx rate, p95); two
# failed measurements abort the rollout and the stable version takes all the traffic again.
# The controller's only AWS permission: cloudwatch:GetMetricData (Pod Identity).
# ---------------------------------------------------------------------------
module "rollouts_pod_identity" {
  source  = "terraform-aws-modules/eks-pod-identity/aws"
  version = "~> 2.11"
  count   = var.enable_argo_rollouts ? 1 : 0

  name                 = "${var.name}-argo-rollouts"
  attach_custom_policy = true
  policy_statements = [{
    sid       = "ReadMetricsForAnalysis" # GetMetricData has no resource-level permissions
    actions   = ["cloudwatch:GetMetricData"]
    resources = ["*"]
  }]

  associations = {
    controller = {
      cluster_name    = module.eks.cluster_name
      namespace       = "argo-rollouts"
      service_account = "argo-rollouts"
    }
  }

  tags = local.tags
}

resource "helm_release" "argo_rollouts" {
  count            = var.enable_argo_rollouts ? 1 : 0
  name             = "argo-rollouts"
  repository       = "https://argoproj.github.io/argo-helm"
  chart            = "argo-rollouts"
  version          = var.argo_rollouts_chart_version
  namespace        = "argo-rollouts"
  create_namespace = true

  values = [yamlencode({
    installCRDs = true
    controller = {
      replicas = 1
      resources = {
        requests = { cpu = "25m", memory = "64Mi" }
        limits   = { memory = "256Mi" }
      }
    }
    serviceAccount = { create = true, name = "argo-rollouts" }
    dashboard      = { enabled = false } # kubectl argo rollouts get rollout ... instead
    notifications  = { secret = { create = false } }
  })]

  wait    = true
  timeout = 600

  depends_on = [module.eks, helm_release.lbc, module.rollouts_pod_identity]
}
