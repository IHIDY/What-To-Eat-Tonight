resource "aws_dynamodb_table" "api_stats" {
  name           = "${var.project_name}-api-stats"
  billing_mode   = "PAY_PER_REQUEST"  # On-demand pricing
  hash_key       = "metric_type"
  range_key      = "metric_id"

  attribute {
    name = "metric_type"
    type = "S"
  }

  attribute {
    name = "metric_id"
    type = "S"
  }

  # Enable TTL for automatic cleanup (optional)
  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  # Enable point-in-time recovery (recommended for production)
  point_in_time_recovery {
    enabled = true
  }

  tags = {
    Name        = "${var.project_name}-api-stats"
    Environment = "production"
  }
}