# ---------------------------------------------------------------------------
# prescaler CronJob (Day 10 Task 1) -> AWS through EKS Pod Identity. It only READS upcoming
# sales from the database (RDS-managed secret); it patches the booking-api HPA through
# Kubernetes RBAC (Helm chart), not through AWS. IAM is free; follows enable_eks.
# ---------------------------------------------------------------------------
resource "aws_iam_role" "prescaler" {
  count              = var.enable_eks ? 1 : 0
  name               = "${local.name}-prescaler"
  description        = "booking-api pre-scaler CronJob (EKS Pod Identity)"
  assume_role_policy = data.aws_iam_policy_document.booking_api_trust.json
  tags               = { Component = "prescaler" }
}

data "aws_iam_policy_document" "prescaler" {
  statement {
    sid       = "DescribeOwnDatabase"
    actions   = ["rds:DescribeDBInstances"]
    resources = [local.db_instance_arn]
  }

  statement {
    sid       = "ReadOwnDatabaseSecret"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = ["arn:aws:secretsmanager:${var.region}:${local.account_id}:secret:rds!db-*"]
    condition {
      test     = "StringEquals"
      variable = "secretsmanager:ResourceTag/aws:rds:primaryDBInstanceArn"
      values   = [local.db_instance_arn]
    }
  }

  statement {
    sid       = "DecryptSecretsViaSecretsManager"
    actions   = ["kms:Decrypt"]
    resources = [module.data.kms_key_arn]
    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["secretsmanager.${var.region}.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "prescaler" {
  count  = var.enable_eks ? 1 : 0
  name   = "prescaler"
  role   = aws_iam_role.prescaler[0].id
  policy = data.aws_iam_policy_document.prescaler.json
}

resource "aws_eks_pod_identity_association" "prescaler" {
  count           = var.enable_eks ? 1 : 0
  cluster_name    = module.eks[0].cluster_name
  namespace       = local.booking_namespace
  service_account = "booking-api-prescaler"
  role_arn        = aws_iam_role.prescaler[0].arn
  tags            = { Component = "prescaler" }
}
