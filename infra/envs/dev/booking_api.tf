# ---------------------------------------------------------------------------
# booking-api pods → AWS (EKS Pod Identity). No access keys anywhere: the EKS Pod Identity
# agent hands the pod short-lived credentials for this role. IAM is free; the role and its
# association follow enable_eks because the association needs the cluster.
# ---------------------------------------------------------------------------
locals {
  booking_namespace = "booking"
  booking_sa        = "booking-api"
  db_instance_arn   = "arn:aws:rds:${var.region}:${local.account_id}:db:${local.name}-pg"
}

data "aws_iam_policy_document" "booking_api_trust" {
  statement {
    actions = ["sts:AssumeRole", "sts:TagSession"]
    principals {
      type        = "Service"
      identifiers = ["pods.eks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "booking_api" {
  count              = var.enable_eks ? 1 : 0
  name               = "${local.name}-booking-api"
  description        = "booking-api pods (EKS Pod Identity)"
  assume_role_policy = data.aws_iam_policy_document.booking_api_trust.json
  tags               = { Component = "booking-api" }
}

data "aws_iam_policy_document" "booking_api" {
  # Find the database: endpoint, port, name and the ARN of its RDS-managed master secret
  # (that ARN changes every time make up restores from a snapshot).
  statement {
    sid       = "DescribeOwnDatabase"
    actions   = ["rds:DescribeDBInstances"]
    resources = [local.db_instance_arn]
  }

  # Only the secret RDS manages for THIS instance: RDS tags it with the instance ARN.
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

  # Redis AUTH token (seat-map cache). Encrypted with the AWS-managed Secrets Manager key.
  statement {
    sid       = "ReadRedisAuthToken"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [module.data.redis_auth_secret_arn]
  }

  # Organiser waiting-room controls (open / pause / resume / rate): the queue's META items.
  statement {
    sid       = "WaitingRoomControls"
    actions   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem"]
    resources = [module.data.queue_table_arn]
  }

  # The master secret is encrypted with the data KMS key; decrypt only through Secrets Manager.
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

resource "aws_iam_role_policy" "booking_api" {
  count  = var.enable_eks ? 1 : 0
  name   = "booking-api"
  role   = aws_iam_role.booking_api[0].id
  policy = data.aws_iam_policy_document.booking_api.json
}

resource "aws_eks_pod_identity_association" "booking_api" {
  count           = var.enable_eks ? 1 : 0
  cluster_name    = module.eks[0].cluster_name
  namespace       = local.booking_namespace
  service_account = local.booking_sa
  role_arn        = aws_iam_role.booking_api[0].arn
  tags            = { Component = "booking-api" }
}
