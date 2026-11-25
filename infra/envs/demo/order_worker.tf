# ---------------------------------------------------------------------------
# order-worker pods (Day 7 Task 4) -> AWS through EKS Pod Identity. Least privilege:
# read/delete payment messages, the database (RDS-managed secret), the payment keys (refunds)
# and publishing sale events. IAM is free; the role follows enable_eks like the others.
# ---------------------------------------------------------------------------
resource "aws_iam_role" "order_worker" {
  count              = var.enable_eks ? 1 : 0
  name               = "${local.name}-order-worker"
  description        = "order-worker pods (EKS Pod Identity)"
  assume_role_policy = data.aws_iam_policy_document.booking_api_trust.json # pods.eks.amazonaws.com
  tags               = { Component = "order-worker" }
}

data "aws_iam_policy_document" "order_worker" {
  statement {
    sid = "ConsumePaymentQueue"
    actions = [
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sqs:ChangeMessageVisibility",
      "sqs:GetQueueAttributes",
    ]
    resources = [module.async.payments_queue_arn]
  }

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
    sid       = "ReadPaymentKeys"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [module.data.razorpay_secret_arn]
  }

  statement {
    sid       = "PublishSaleEvents"
    actions   = ["kinesis:PutRecord", "kinesis:PutRecords"]
    resources = [module.events.stream_arn]
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

resource "aws_iam_role_policy" "order_worker" {
  count  = var.enable_eks ? 1 : 0
  name   = "order-worker"
  role   = aws_iam_role.order_worker[0].id
  policy = data.aws_iam_policy_document.order_worker.json
}

resource "aws_eks_pod_identity_association" "order_worker" {
  count           = var.enable_eks ? 1 : 0
  cluster_name    = module.eks[0].cluster_name
  namespace       = local.booking_namespace
  service_account = "order-worker"
  role_arn        = aws_iam_role.order_worker[0].arn
  tags            = { Component = "order-worker" }
}
