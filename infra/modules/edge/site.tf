# ---------------------------------------------------------------------------
# Buyer site: static files (Next.js export) in a private S3 bucket, served by the SAME
# CloudFront distribution as the API (one origin for browsers: no CORS, one URL for the demo).
# CloudFront reads the bucket through an origin access control (OAC); the bucket is never public.
# No hourly cost: S3 storage (a few MB) + CloudFront requests. Not affected by make down, so the
# site stays up while dev is down (its API calls then get the origin-down 503).
# ---------------------------------------------------------------------------
data "aws_caller_identity" "current" {}

locals {
  site = var.cloudfront_enabled && var.buyer_site_enabled ? 1 : 0
}

resource "aws_s3_bucket" "site" {
  count         = local.site
  bucket        = "${var.name}-buyer-site-${data.aws_caller_identity.current.account_id}"
  force_destroy = true # build output only; CI re-uploads it on every deploy
  tags          = merge(local.tags, { Name = "${var.name}-buyer-site" })
}

resource "aws_s3_bucket_public_access_block" "site" {
  count                   = local.site
  bucket                  = aws_s3_bucket.site[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "site" {
  count  = local.site
  bucket = aws_s3_bucket.site[0].id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "site" {
  count  = local.site
  bucket = aws_s3_bucket.site[0].id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256" # SSE-S3: free; KMS would add a request charge per object read
    }
  }
}

resource "aws_cloudfront_origin_access_control" "site" {
  count                             = local.site
  name                              = "${var.name}-buyer-site"
  description                       = "CloudFront -> buyer site bucket (SigV4)"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# Only THIS distribution may read. ListBucket makes a missing page a 404 (not a 403).
data "aws_iam_policy_document" "site" {
  count = local.site
  statement {
    sid       = "CloudFrontReadsTheSite"
    actions   = ["s3:GetObject", "s3:ListBucket"]
    resources = [aws_s3_bucket.site[0].arn, "${aws_s3_bucket.site[0].arn}/*"]
    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.api[0].arn]
    }
  }
  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.site[0].arn,
      "${aws_s3_bucket.site[0].arn}/*",
    ]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "site" {
  count      = local.site
  bucket     = aws_s3_bucket.site[0].id
  policy     = data.aws_iam_policy_document.site[0].json
  depends_on = [aws_s3_bucket_public_access_block.site]
}

resource "aws_cloudfront_function" "site_rewrite" {
  count   = local.site
  name    = "${var.name}-site-rewrite"
  runtime = "cloudfront-js-2.0"
  comment = "Buyer site: /x/ -> /x/index.html"
  publish = true
  code    = file("${path.module}/functions/site_rewrite.js")
}

# Static files: honour the Cache-Control the deploy sets (HTML 60 s, hashed /_next/static 1 year).
data "aws_cloudfront_cache_policy" "optimized" {
  name = "Managed-CachingOptimized"
}

data "aws_cloudfront_response_headers_policy" "security" {
  name = "Managed-SecurityHeadersPolicy" # HSTS, nosniff, frame-options, referrer-policy, XSS
}
