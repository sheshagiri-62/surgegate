# ---------------------------------------------------------------------------
# ecr-push role: used by build-deploy.yml on main to push images (nothing else)
# ---------------------------------------------------------------------------
locals {
  # Repository is created in infra/envs/shared; referenced by name so bootstrap has no dependency.
  ecr_push_repo_arns = [
    for r in var.ecr_push_repositories :
    "arn:aws:ecr:${var.region}:${local.account_id}:repository/${r}"
  ]
}

data "aws_iam_policy_document" "ecr_push_trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "${local.oidc_host}:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "${local.oidc_host}:sub"
      values   = ["${var.github_oidc_subject_prefix}:ref:refs/heads/main"]
    }
  }
}

resource "aws_iam_role" "ecr_push" {
  name                 = "${var.project}-gha-ecr-push"
  description          = "GitHub Actions build-deploy: push images to ECR from main only"
  assume_role_policy   = data.aws_iam_policy_document.ecr_push_trust.json
  max_session_duration = 3600
}

data "aws_iam_policy_document" "ecr_push" {
  statement {
    sid       = "EcrLogin" # registry-wide by design; grants no access to any repository
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid = "PushAndReadScanToTheseReposOnly"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:InitiateLayerUpload",
      "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload",
      "ecr:PutImage",
      "ecr:BatchGetImage",
      "ecr:DescribeImages",
      "ecr:DescribeImageScanFindings",
    ]
    resources = local.ecr_push_repo_arns
  }
}

resource "aws_iam_role_policy" "ecr_push" {
  name   = "ecr-push"
  role   = aws_iam_role.ecr_push.id
  policy = data.aws_iam_policy_document.ecr_push.json
}

output "ecr_push_role_arn" {
  description = "Role for build-deploy.yml (main branch, ECR push only)."
  value       = aws_iam_role.ecr_push.arn
}
