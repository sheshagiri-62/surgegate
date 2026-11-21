data "aws_caller_identity" "current" {}

locals {
  tags       = merge(var.tags, { Component = "data" })
  compute    = var.compute_enabled ? 1 : 0
  restoring  = var.restore_snapshot_id != ""
  client_sgs = var.compute_enabled ? var.client_security_group_ids : []
}

# ===========================================================================
# PERSISTENT (free or cents/month): KMS key, S3, secrets, subnet groups, SGs, parameter group
# ===========================================================================

# One customer-managed key for data at rest (RDS, its master secret, ElastiCache, S3).
resource "aws_kms_key" "data" {
  description             = "${var.name} data at rest (RDS, ElastiCache, S3)"
  enable_key_rotation     = true
  deletion_window_in_days = 7
  tags                    = local.tags
}

resource "aws_kms_alias" "data" {
  name          = "alias/${var.name}-data"
  target_key_id = aws_kms_key.data.key_id
}

# --- S3 buckets (tickets PDFs, uploaded seat maps) -------------------------
resource "aws_s3_bucket" "this" {
  for_each = toset(var.buckets)
  bucket   = "${var.name}-${each.key}-${data.aws_caller_identity.current.account_id}"
  tags     = merge(local.tags, { Name = "${var.name}-${each.key}" })
}

resource "aws_s3_bucket_ownership_controls" "this" {
  for_each = aws_s3_bucket.this
  bucket   = each.value.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "this" {
  for_each                = aws_s3_bucket.this
  bucket                  = each.value.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "this" {
  for_each = aws_s3_bucket.this
  bucket   = each.value.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  for_each = aws_s3_bucket.this
  bucket   = each.value.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.data.arn
    }
    bucket_key_enabled = true # far fewer KMS requests (cost)
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "this" {
  for_each = aws_s3_bucket.this
  bucket   = each.value.id

  rule {
    id     = "tidy"
    status = "Enabled"
    filter {}

    noncurrent_version_expiration {
      noncurrent_days = var.bucket_noncurrent_days
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  depends_on = [aws_s3_bucket_versioning.this]
}

data "aws_iam_policy_document" "bucket_tls_only" {
  for_each = aws_s3_bucket.this
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [each.value.arn, "${each.value.arn}/*"]
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

resource "aws_s3_bucket_policy" "this" {
  for_each   = aws_s3_bucket.this
  bucket     = each.value.id
  policy     = data.aws_iam_policy_document.bucket_tls_only[each.key].json
  depends_on = [aws_s3_bucket_public_access_block.this]
}

# --- Secrets ---------------------------------------------------------------
# Redis AUTH token: generated once, kept across sessions.
resource "random_password" "redis_auth" {
  length  = 48
  special = false # ElastiCache AUTH tokens allow only a few special characters
}

resource "aws_secretsmanager_secret" "redis_auth" {
  name                    = "${var.secrets_prefix}/data/redis-auth"
  description             = "ElastiCache Redis AUTH token"
  recovery_window_in_days = 7
  tags                    = local.tags
}

resource "aws_secretsmanager_secret_version" "redis_auth" {
  secret_id     = aws_secretsmanager_secret.redis_auth.id
  secret_string = random_password.redis_auth.result
}

# Razorpay test keys: only the container is created here; the value is set by hand later
# (aws secretsmanager put-secret-value …), never in Git or Terraform.
resource "aws_secretsmanager_secret" "razorpay" {
  name                    = "${var.secrets_prefix}/data/razorpay"
  description             = "Razorpay TEST key id and secret (JSON). Value set manually; not managed by Terraform."
  recovery_window_in_days = 7
  tags                    = local.tags
}

# --- Network plumbing ------------------------------------------------------
resource "aws_db_subnet_group" "this" {
  name       = "${var.name}-data"
  subnet_ids = var.data_subnet_ids
  tags       = local.tags
}

resource "aws_elasticache_subnet_group" "this" {
  name       = "${var.name}-data"
  subnet_ids = var.data_subnet_ids
  tags       = local.tags
}

resource "aws_security_group" "postgres" {
  name        = "${var.name}-postgres"
  description = "PostgreSQL: 5432 from app security groups only"
  vpc_id      = var.vpc_id
  tags        = merge(local.tags, { Name = "${var.name}-postgres" })
}

resource "aws_security_group" "redis" {
  name        = "${var.name}-redis"
  description = "Redis: 6379 from app security groups only"
  vpc_id      = var.vpc_id
  tags        = merge(local.tags, { Name = "${var.name}-redis" })
}

resource "aws_vpc_security_group_ingress_rule" "postgres_from_clients" {
  count                        = length(local.client_sgs)
  security_group_id            = aws_security_group.postgres.id
  description                  = "PostgreSQL from app"
  referenced_security_group_id = local.client_sgs[count.index]
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}

resource "aws_vpc_security_group_ingress_rule" "redis_from_clients" {
  count                        = length(local.client_sgs)
  security_group_id            = aws_security_group.redis.id
  description                  = "Redis from app"
  referenced_security_group_id = local.client_sgs[count.index]
  ip_protocol                  = "tcp"
  from_port                    = 6379
  to_port                      = 6379
}

resource "aws_db_parameter_group" "postgres" {
  name        = "${var.name}-pg${var.pg_engine_version}"
  family      = "postgres${var.pg_engine_version}"
  description = "${var.name} PostgreSQL ${var.pg_engine_version}"

  parameter {
    name         = "rds.force_ssl"
    value        = "1"              # TLS required for every connection
    apply_method = "pending-reboot" # static parameter; set at instance creation (no perpetual diff)
  }

  parameter {
    name  = "log_min_duration_statement"
    value = "500" # log queries slower than the 500 ms booking SLO
  }

  tags = local.tags
}

resource "aws_elasticache_parameter_group" "redis" {
  name        = "${var.name}-redis7"
  family      = "redis7"
  description = "${var.name} Redis 7: cache semantics"

  parameter {
    name  = "maxmemory-policy"
    value = "allkeys-lru" # it's a cache: evict the least recently used key instead of refusing writes
  }

  tags = local.tags
}

# ===========================================================================
# HOURLY (compute_enabled): RDS PostgreSQL and ElastiCache Redis
# ===========================================================================

# New random suffix for every instance lifetime, so each make down writes a new,
# uniquely named final snapshot.
resource "random_id" "final_snapshot" {
  count       = local.compute
  byte_length = 4
}

resource "aws_db_instance" "postgres" {
  count = local.compute

  identifier     = "${var.name}-pg"
  engine         = "postgres"
  engine_version = var.pg_engine_version
  instance_class = var.pg_instance_class

  # Restore from the newest final snapshot (make up); otherwise a new empty database.
  snapshot_identifier = local.restoring ? var.restore_snapshot_id : null
  db_name             = local.restoring ? null : "surgegate"
  username            = local.restoring ? null : "surgegate_admin"

  # Password generated, stored and rotated by RDS in Secrets Manager (never in state or Git).
  manage_master_user_password   = true
  master_user_secret_kms_key_id = aws_kms_key.data.arn

  allocated_storage      = var.pg_allocated_storage_gb
  storage_type           = "gp3"
  storage_encrypted      = true
  kms_key_id             = aws_kms_key.data.arn
  multi_az               = var.pg_multi_az
  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [aws_security_group.postgres.id]
  publicly_accessible    = false
  parameter_group_name   = aws_db_parameter_group.postgres.name

  backup_retention_period    = var.pg_backup_retention_days
  backup_window              = "20:00-20:30" # UTC (01:30 IST)
  maintenance_window         = "sun:21:00-sun:21:30"
  auto_minor_version_upgrade = true
  copy_tags_to_snapshot      = true
  delete_automated_backups   = true # the final snapshot is what we keep

  skip_final_snapshot       = false
  final_snapshot_identifier = "${var.name}-pg-final-${random_id.final_snapshot[0].hex}"
  deletion_protection       = false # dev is destroyed every session; demo keeps its own setting

  performance_insights_enabled = false
  apply_immediately            = true

  tags = local.tags

  lifecycle {
    # Which snapshot an existing instance came from doesn't matter after creation.
    ignore_changes = [snapshot_identifier]
  }
}

resource "aws_elasticache_replication_group" "redis" {
  count = local.compute

  replication_group_id = "${var.name}-redis"
  description          = "${var.name} seat-map cache and rate limits"
  engine               = "redis"
  engine_version       = var.redis_engine_version
  node_type            = var.redis_node_type
  num_cache_clusters   = 1 + var.redis_replicas
  port                 = 6379
  parameter_group_name = aws_elasticache_parameter_group.redis.name
  subnet_group_name    = aws_elasticache_subnet_group.this.name
  security_group_ids   = [aws_security_group.redis.id]

  at_rest_encryption_enabled = true
  kms_key_id                 = aws_kms_key.data.arn
  transit_encryption_enabled = true
  auth_token                 = random_password.redis_auth.result

  automatic_failover_enabled = var.redis_replicas > 0
  multi_az_enabled           = var.redis_replicas > 0
  snapshot_retention_limit   = 0 # cache only; nothing to keep (blueprint: "Redis lost → reads fall back")
  maintenance_window         = "sun:21:30-sun:22:30"
  apply_immediately          = true

  tags = local.tags
}

# ===========================================================================
# PERSISTENT: DynamoDB queue table (waiting room). On-demand = no hourly cost; kept between
# sessions like the RDS snapshot (plan: "Data between sessions: RDS snapshot + DynamoDB tables").
#   PK = EVENT#<id>, SK = META        queue state
#   PK = EVENT#<id>, SK = USER#<sub>  queue entry
# ===========================================================================
resource "aws_dynamodb_table" "queue" {
  name                        = "${var.name}-queue"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "PK"
  range_key                   = "SK"
  deletion_protection_enabled = var.queue_table_deletion_protection

  attribute {
    name = "PK"
    type = "S"
  }

  attribute {
    name = "SK"
    type = "S"
  }

  attribute {
    name = "active"
    type = "S"
  }

  # Sparse index of active queues: only META items of queues still running carry `active`, so
  # the starter and valve find them without scanning queue entries.
  global_secondary_index {
    name            = "active-queues"
    hash_key        = "active"
    projection_type = "ALL"
  }

  # Queue entries carry expires_at (epoch seconds); DynamoDB deletes them for free afterwards.
  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = var.queue_table_pitr
  }

  # Encrypted at rest with the AWS-owned key (free; no KMS calls from every Lambda).
  server_side_encryption {
    enabled = false
  }

  tags = merge(local.tags, { Name = "${var.name}-queue" })
}
