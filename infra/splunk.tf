# Integración opcional con un HEC existente. No administra el servidor Splunk.
resource "aws_secretsmanager_secret" "splunk" {
  count                   = local.splunk_enabled ? 1 : 0
  name_prefix             = "${local.name}-splunk-"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "splunk" {
  count                    = local.splunk_enabled ? 1 : 0
  secret_id                = aws_secretsmanager_secret.splunk[0].id
  secret_string_wo         = jsonencode({ hec_token = var.splunk_hec_token })
  secret_string_wo_version = var.secret_revision
}

resource "aws_s3_bucket" "audit" {
  count         = local.firehose_enabled ? 1 : 0
  bucket_prefix = "${local.name}-audit-"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "audit" {
  count                   = local.firehose_enabled ? 1 : 0
  bucket                  = aws_s3_bucket.audit[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "audit" {
  count  = local.firehose_enabled ? 1 : 0
  bucket = aws_s3_bucket.audit[0].id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_policy" "audit" {
  count  = local.firehose_enabled ? 1 : 0
  bucket = aws_s3_bucket.audit[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource  = [aws_s3_bucket.audit[0].arn, "${aws_s3_bucket.audit[0].arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
}

resource "aws_cloudwatch_log_group" "delivery" {
  count             = local.firehose_enabled ? 1 : 0
  name              = "/lab/${local.name}/firehose"
  retention_in_days = 7
}

resource "aws_cloudwatch_log_stream" "delivery" {
  count          = local.firehose_enabled ? 1 : 0
  name           = "delivery"
  log_group_name = aws_cloudwatch_log_group.delivery[0].name
}

resource "aws_iam_role" "firehose" {
  count       = local.firehose_enabled ? 1 : 0
  name_prefix = "${local.name}-firehose-"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "firehose.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "firehose" {
  count = local.firehose_enabled ? 1 : 0
  role  = aws_iam_role.firehose[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetBucketLocation", "s3:ListBucket", "s3:ListBucketMultipartUploads"]
        Resource = aws_s3_bucket.audit[0].arn
      },
      {
        Effect   = "Allow"
        Action   = ["s3:AbortMultipartUpload", "s3:GetObject", "s3:PutObject"]
        Resource = "${aws_s3_bucket.audit[0].arn}/*"
      },
      {
        Effect   = "Allow"
        Action   = ["logs:PutLogEvents"]
        Resource = aws_cloudwatch_log_stream.delivery[0].arn
      },
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = aws_secretsmanager_secret.splunk[0].arn
      }
    ]
  })
}

resource "aws_kinesis_firehose_delivery_stream" "splunk" {
  count       = local.firehose_enabled ? 1 : 0
  name        = "${local.name}-splunk"
  destination = "splunk"

  server_side_encryption {
    enabled  = true
    key_type = "AWS_OWNED_CMK"
  }

  splunk_configuration {
    hec_endpoint               = trimsuffix(var.splunk_hec_endpoint, "/")
    hec_endpoint_type          = "Raw"
    hec_acknowledgment_timeout = 180
    buffering_interval         = 60
    buffering_size             = 1
    retry_duration             = 300
    s3_backup_mode             = "AllEvents"

    secrets_manager_configuration {
      enabled    = true
      secret_arn = aws_secretsmanager_secret.splunk[0].arn
      role_arn   = aws_iam_role.firehose[0].arn
    }

    processing_configuration {
      enabled = true
      processors {
        type = "Decompression"
        parameters {
          parameter_name  = "CompressionFormat"
          parameter_value = "GZIP"
        }
      }
      processors {
        type = "CloudWatchLogProcessing"
        parameters {
          parameter_name  = "DataMessageExtraction"
          parameter_value = "true"
        }
      }
    }

    cloudwatch_logging_options {
      enabled         = true
      log_group_name  = aws_cloudwatch_log_group.delivery[0].name
      log_stream_name = aws_cloudwatch_log_stream.delivery[0].name
    }

    s3_configuration {
      role_arn           = aws_iam_role.firehose[0].arn
      bucket_arn         = aws_s3_bucket.audit[0].arn
      prefix             = "audit/"
      compression_format = "GZIP"
    }
  }

  depends_on = [
    aws_iam_role_policy.firehose,
    aws_secretsmanager_secret_version.splunk,
    aws_s3_bucket_public_access_block.audit,
    aws_s3_bucket_server_side_encryption_configuration.audit,
    aws_s3_bucket_policy.audit,
  ]
}

resource "aws_iam_role" "logs_delivery" {
  count       = local.firehose_enabled ? 1 : 0
  name_prefix = "${local.name}-logs-"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "logs.${var.aws_region}.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = {
        StringLike = {
          "aws:SourceArn" = "arn:${local.partition}:logs:${var.aws_region}:${var.aws_account_id}:*"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "logs_delivery" {
  count = local.firehose_enabled ? 1 : 0
  role  = aws_iam_role.logs_delivery[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["firehose:PutRecord", "firehose:PutRecordBatch"]
      Resource = aws_kinesis_firehose_delivery_stream.splunk[0].arn
    }]
  })
}

resource "aws_cloudwatch_log_subscription_filter" "audit" {
  count           = local.firehose_enabled ? 1 : 0
  name            = "${local.name}-audit"
  log_group_name  = aws_cloudwatch_log_group.agents.name
  filter_pattern  = "{ $.run_id = * && $.evento = * }"
  destination_arn = aws_kinesis_firehose_delivery_stream.splunk[0].arn
  role_arn        = aws_iam_role.logs_delivery[0].arn
  depends_on      = [aws_iam_role_policy.logs_delivery]
}
