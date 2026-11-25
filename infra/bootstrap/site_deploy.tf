# ---------------------------------------------------------------------------
# site-deploy role: used by build-deploy-buyer.yml on main to upload the buyer site's static
# export to S3 and invalidate the CloudFront cache. Nothing else.
# ---------------------------------------------------------------------------
locals {
  # Buckets are created in infra/envs/<env> (edge module); referenced by name so bootstrap has no
  # dependency on them.
  site_bucket_arns = [
    for e in var.site_deploy_envs :
    "arn:aws:s3:::${var.project}-${e}-buyer-site-${local.account_id}"
  ]
}

data "aws_iam_policy_document" "site_deploy_trust" {
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

resource "aws_iam_role" "site_deploy" {
  name                 = "${var.project}-gha-site-deploy"
  description          = "GitHub Actions build-deploy-buyer: upload the buyer site + invalidate, main only"
  assume_role_policy   = data.aws_iam_policy_document.site_deploy_trust.json
  max_session_duration = 3600
}

data "aws_iam_policy_document" "site_deploy" {
  statement {
    sid       = "ListTheSiteBuckets" # aws s3 sync compares with what is there
    actions   = ["s3:ListBucket"]
    resources = local.site_bucket_arns
  }

  statement {
    sid       = "WriteTheSiteFiles"
    actions   = ["s3:PutObject", "s3:DeleteObject", "s3:GetObject"]
    resources = [for b in local.site_bucket_arns : "${b}/*"]
  }

  statement {
    sid     = "InvalidateTheSiteCache"
    actions = ["cloudfront:CreateInvalidation", "cloudfront:GetInvalidation"]
    resources = [
      for d in var.site_distribution_ids : "arn:aws:cloudfront::${local.account_id}:distribution/${d}"
    ]
  }
}

resource "aws_iam_role_policy" "site_deploy" {
  name   = "site-deploy"
  role   = aws_iam_role.site_deploy.id
  policy = data.aws_iam_policy_document.site_deploy.json
}

output "site_deploy_role_arn" {
  description = "Role for build-deploy-buyer.yml (main branch, buyer-site upload + invalidation only)."
  value       = aws_iam_role.site_deploy.arn
}
