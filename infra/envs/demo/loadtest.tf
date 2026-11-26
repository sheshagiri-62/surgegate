# ---------------------------------------------------------------------------
# Load-test token issuer (Day 10 Task 4): demo ONLY, test window ONLY (enable_loadtest).
# 50k virtual fans need 50k signed-in buyers; real Cognito users would be ~$600 of monthly
# active users. Instead a test issuer signs 1-hour buyer tokens that ONLY demo trusts:
#   - demo queue API (JWT authorizer: module.queue loadtest_issuer in main.tf)
#   - demo booking API (deploy/helm/booking-api/values-demo.yaml: auth.loadtestIssuer)
# dev never references this module. After the test, enable_loadtest = false removes the issuer,
# its key and the k6 role, and both checkers go back to Cognito only.
# ---------------------------------------------------------------------------
module "loadtest_issuer" {
  source = "../../modules/loadtest_issuer"
  count  = var.enable_loadtest ? 1 : 0

  name           = local.name
  secrets_prefix = "${var.project}/${local.env}"
  source_dir     = "${path.root}/../../../services/queue/src"
  cluster_name   = module.eks[0].cluster_name
}
