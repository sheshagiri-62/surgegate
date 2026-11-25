# ---------------------------------------------------------------------------
# Account security (Day 10 Task 3), one region (ap-south-1):
#   CloudTrail  - one multi-region trail, management events only (the first copy is free),
#                 log-file validation, S3 (SSE-S3), 90-day lifecycle. Always on.
#   GuardDuty   - threat detection; 30-day free trial. EKS audit logs + S3 data events on;
#                 Runtime Monitoring, malware scans, RDS and Lambda protection off.
#   Security Hub - CSPM with the AWS Foundational Security Best Practices standard only;
#                 30-day free trial.
#   AWS Config  - the recorder Security Hub needs: ONLY the resource types FSBP checks here
#                 (not "all resources"), one recorder, no periodic snapshots. Not in the trial:
#                 ~$0.003 per configuration item recorded.
# enable_paid_services = false (make security-off) removes GuardDuty, Security Hub and the
# Config recorder before the free trials end (~26 Dec 2026); the trail stays (free).
# ---------------------------------------------------------------------------
data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  tags    = merge(var.tags, { Component = "security" })
  account = data.aws_caller_identity.current.account_id
  region  = data.aws_region.current.region
  paid    = var.enable_paid_services ? 1 : 0
}

# --- CloudTrail ------------------------------------------------------------------------------
resource "aws_s3_bucket" "trail" {
  bucket        = "${var.name}-cloudtrail-${local.account}"
  force_destroy = false # audit logs: never deleted by a terraform destroy by accident
  tags          = local.tags
}

resource "aws_s3_bucket_public_access_block" "trail" {
  bucket                  = aws_s3_bucket.trail.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "trail" {
  bucket = aws_s3_bucket.trail.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "trail" {
  bucket = aws_s3_bucket.trail.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "trail" {
  bucket = aws_s3_bucket.trail.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "trail" {
  bucket = aws_s3_bucket.trail.id
  rule {
    id     = "expire"
    status = "Enabled"
    filter {}
    expiration {
      days = var.trail_retention_days
    }
    noncurrent_version_expiration {
      noncurrent_days = 7
    }
  }
}

data "aws_iam_policy_document" "trail_bucket" {
  statement {
    sid       = "CloudTrailAclCheck"
    actions   = ["s3:GetBucketAcl"]
    resources = [aws_s3_bucket.trail.arn]
    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceArn"
      values   = ["arn:aws:cloudtrail:${local.region}:${local.account}:trail/${var.name}"]
    }
  }
  statement {
    sid       = "CloudTrailWrite"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.trail.arn}/AWSLogs/${local.account}/*"]
    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceArn"
      values   = ["arn:aws:cloudtrail:${local.region}:${local.account}:trail/${var.name}"]
    }
  }
  statement {
    sid       = "ConfigAclCheck"
    actions   = ["s3:GetBucketAcl", "s3:ListBucket"]
    resources = [aws_s3_bucket.trail.arn]
    principals {
      type        = "Service"
      identifiers = ["config.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account]
    }
  }
  statement {
    sid       = "ConfigWrite"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.trail.arn}/config/AWSLogs/${local.account}/Config/*"]
    principals {
      type        = "Service"
      identifiers = ["config.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account]
    }
  }
  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.trail.arn,
      "${aws_s3_bucket.trail.arn}/*",
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

resource "aws_s3_bucket_policy" "trail" {
  bucket     = aws_s3_bucket.trail.id
  policy     = data.aws_iam_policy_document.trail_bucket.json
  depends_on = [aws_s3_bucket_public_access_block.trail]
}

resource "aws_cloudtrail" "this" {
  name                          = var.name
  s3_bucket_name                = aws_s3_bucket.trail.id
  is_multi_region_trail         = true
  include_global_service_events = true
  enable_log_file_validation    = true
  tags                          = local.tags

  event_selector {
    read_write_type           = "All"
    include_management_events = true # management events only: the first copy is free
  }

  depends_on = [aws_s3_bucket_policy.trail]
}

# --- GuardDuty -------------------------------------------------------------------------------
resource "aws_guardduty_detector" "this" {
  count                        = local.paid
  enable                       = true
  finding_publishing_frequency = "SIX_HOURS"
  tags                         = local.tags
}

resource "aws_guardduty_detector_feature" "this" {
  for_each = var.enable_paid_services ? {
    EKS_AUDIT_LOGS         = "ENABLED"
    S3_DATA_EVENTS         = "ENABLED"
    EBS_MALWARE_PROTECTION = "DISABLED"
    RDS_LOGIN_EVENTS       = "DISABLED"
    LAMBDA_NETWORK_LOGS    = "DISABLED"
    RUNTIME_MONITORING     = "DISABLED" # would add an agent to every node
  } : {}
  detector_id = aws_guardduty_detector.this[0].id
  name        = each.key
  status      = each.value
}

# --- AWS Config (only what FSBP checks) ------------------------------------------------------
data "aws_iam_policy_document" "config_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["config.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "config" {
  count              = local.paid
  name               = "${var.name}-config-recorder"
  assume_role_policy = data.aws_iam_policy_document.config_trust.json
  tags               = local.tags
}

resource "aws_iam_role_policy_attachment" "config" {
  count      = local.paid
  role       = aws_iam_role.config[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWS_ConfigRole"
}

resource "aws_config_configuration_recorder" "this" {
  count    = local.paid
  name     = var.name
  role_arn = aws_iam_role.config[0].arn

  recording_group {
    all_supported                 = false
    include_global_resource_types = false
    recording_strategy {
      use_only = "INCLUSION_BY_RESOURCE_TYPES"
    }
    resource_types = var.config_resource_types
  }

  recording_mode {
    recording_frequency = "CONTINUOUS"
  }
}

resource "aws_config_delivery_channel" "this" {
  count          = local.paid
  name           = var.name
  s3_bucket_name = aws_s3_bucket.trail.id
  s3_key_prefix  = "config"
  # no snapshot_delivery_properties: no periodic configuration snapshots
  depends_on = [aws_config_configuration_recorder.this, aws_s3_bucket_policy.trail]
}

resource "aws_config_configuration_recorder_status" "this" {
  count      = local.paid
  name       = aws_config_configuration_recorder.this[0].name
  is_enabled = true
  depends_on = [aws_config_delivery_channel.this]
}

# --- Security Hub (CSPM, FSBP only) ----------------------------------------------------------
resource "aws_securityhub_account" "this" {
  count                     = local.paid
  enable_default_standards  = false # only FSBP below (CIS etc. would add checks)
  control_finding_generator = "SECURITY_CONTROL"
  auto_enable_controls      = true
  depends_on                = [aws_config_configuration_recorder_status.this]
}

resource "aws_securityhub_standards_subscription" "fsbp" {
  count         = local.paid
  standards_arn = "arn:aws:securityhub:${local.region}::standards/aws-foundational-security-best-practices/v/1.0.0"
  depends_on    = [aws_securityhub_account.this]
}
