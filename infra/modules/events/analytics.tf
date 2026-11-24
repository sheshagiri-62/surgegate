# analytics consumer (Day 8 Task 3b, lean): sale events -> S3 gzip JSON lines -> Glue table
# (partition projection, no crawler) -> Athena workgroup with a per-query scan limit.
# Pay per use only: S3 storage, Athena ($5/TB scanned; capped at 100 MB per query here).

locals {
  glue_db = replace("${var.name}_analytics", "-", "_")
}

resource "aws_lambda_event_source_mapping" "analytics" {
  count                              = local.stream
  event_source_arn                   = aws_kinesis_stream.this[0].arn
  function_name                      = aws_lambda_function.consumer["analytics"].arn
  starting_position                  = "TRIM_HORIZON" # back-fill what the stream still holds (24 h)
  batch_size                         = 500
  maximum_batching_window_in_seconds = 60 # fewer, larger objects; analytics needn't be live
  parallelization_factor             = 1
  bisect_batch_on_function_error     = true
  maximum_retry_attempts             = 3
  # -1: keep records as long as the stream does (24 h). A back-fill from TRIM_HORIZON needs old
  # records; 3600 (copied from the live dashboard) discarded them as RecordAgeExceeded.
  maximum_record_age_in_seconds = -1
  function_response_types       = ["ReportBatchItemFailures"]

  destination_config {
    on_failure {
      destination_arn = aws_sqs_queue.consumers_failed.arn
    }
  }

  tags = local.tags
}

resource "aws_glue_catalog_database" "analytics" {
  name        = local.glue_db
  description = "SurgeGate sale analytics (Athena)"
}

resource "aws_glue_catalog_table" "sale_events" {
  name          = "sale_events"
  database_name = aws_glue_catalog_database.analytics.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    classification                = "json"
    compressionType               = "gzip"
    "projection.enabled"          = "true"
    "projection.dt.type"          = "date"
    "projection.dt.format"        = "yyyy-MM-dd"
    "projection.dt.range"         = "2026-11-01,NOW"
    "projection.dt.interval"      = "1"
    "projection.dt.interval.unit" = "DAYS"
    "projection.hour.type"        = "integer"
    "projection.hour.range"       = "0,23"
    "projection.hour.digits"      = "2"
    "storage.location.template"   = "s3://${var.analytics_bucket_name}/events/dt=$${dt}/hour=$${hour}/"
  }

  partition_keys {
    name = "dt"
    type = "string"
  }
  partition_keys {
    name = "hour"
    type = "string"
  }

  storage_descriptor {
    location      = "s3://${var.analytics_bucket_name}/events/"
    input_format  = "org.apache.hadoop.mapred.TextInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"

    ser_de_info {
      serialization_library = "org.openx.data.jsonserde.JsonSerDe"
    }

    dynamic "columns" {
      for_each = {
        id  = "string", type = "string", sale_event_id = "string", at = "string", seq = "string",
        sub = "string", seats = "int", amount_paise = "bigint", data = "string",
      }
      content {
        name = columns.key
        type = columns.value
      }
    }
  }
}

resource "aws_athena_workgroup" "analytics" {
  name          = "${var.name}-analytics"
  description   = "Sale analytics; results KMS-encrypted; 100 MB scan limit per query"
  force_destroy = true

  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true
    bytes_scanned_cutoff_per_query     = 104857600

    result_configuration {
      output_location = "s3://${var.analytics_bucket_name}/athena-results/"
      encryption_configuration {
        encryption_option = "SSE_KMS"
        kms_key_arn       = var.kms_key_arn
      }
    }
  }

  tags = local.tags
}

resource "aws_athena_named_query" "sales_per_minute" {
  name        = "sales-per-minute"
  workgroup   = aws_athena_workgroup.analytics.name
  database    = aws_glue_catalog_database.analytics.name
  description = "Seats sold and revenue per minute for one sale (duplicates removed by message id)"
  query       = <<-SQL
    -- Replace the sale id. Rows are de-duplicated by id (a retried batch may repeat records).
    WITH e AS (
      SELECT DISTINCT id, type, sale_event_id, from_iso8601_timestamp(at) AS t, seats, amount_paise
      FROM sale_events
      WHERE dt >= '2026-11-01' AND sale_event_id = '<sale id>' AND type = 'order_paid'
    )
    SELECT date_trunc('minute', t) AS minute, sum(seats) AS seats_sold,
           sum(amount_paise) / 100.0 AS revenue_inr, count(*) AS orders
    FROM e GROUP BY 1 ORDER BY 1
  SQL
}

resource "aws_athena_named_query" "funnel" {
  name        = "queue-to-purchase-funnel"
  workgroup   = aws_athena_workgroup.analytics.name
  database    = aws_glue_catalog_database.analytics.name
  description = "Joined -> admitted -> held -> paid, per sale (duplicates removed by message id)"
  query       = <<-SQL
    WITH e AS (SELECT DISTINCT id, type, sale_event_id FROM sale_events WHERE dt >= '2026-11-01')
    SELECT sale_event_id,
           count_if(type = 'joined')     AS joined,
           count_if(type = 'admitted')   AS admitted,
           count_if(type = 'seat_held')  AS holds,
           count_if(type = 'order_paid') AS paid,
           round(100.0 * count_if(type = 'order_paid') / nullif(count_if(type = 'joined'), 0), 1) AS joined_to_paid_pct
    FROM e GROUP BY sale_event_id ORDER BY joined DESC
  SQL
}
