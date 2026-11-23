# ---------------------------------------------------------------------------
# mock-pay pods (ADR 004: Razorpay-shaped mock payment provider, dev only) -> AWS through EKS
# Pod Identity. One right: read the payment keys (to check API keys and sign webhooks).
# IAM is free; the role and association follow enable_eks like the booking API's.
# ---------------------------------------------------------------------------
resource "aws_iam_role" "mock_pay" {
  count              = var.enable_eks ? 1 : 0
  name               = "${local.name}-mock-pay"
  description        = "mock-pay pods (EKS Pod Identity), ADR 004"
  assume_role_policy = data.aws_iam_policy_document.booking_api_trust.json # pods.eks.amazonaws.com
  tags               = { Component = "mock-pay" }
}

data "aws_iam_policy_document" "mock_pay" {
  statement {
    sid       = "ReadPaymentKeys"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [module.data.razorpay_secret_arn]
  }
}

resource "aws_iam_role_policy" "mock_pay" {
  count  = var.enable_eks ? 1 : 0
  name   = "mock-pay"
  role   = aws_iam_role.mock_pay[0].id
  policy = data.aws_iam_policy_document.mock_pay.json
}

resource "aws_eks_pod_identity_association" "mock_pay" {
  count           = var.enable_eks ? 1 : 0
  cluster_name    = module.eks[0].cluster_name
  namespace       = "mock-pay"
  service_account = "mock-pay"
  role_arn        = aws_iam_role.mock_pay[0].arn
  tags            = { Component = "mock-pay" }
}
