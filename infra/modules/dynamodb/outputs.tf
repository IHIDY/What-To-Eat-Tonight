output "table_name" {
  value       = aws_dynamodb_table.api_stats.name
  description = "DynamoDB table name"
}

output "table_arn" {
  value       = aws_dynamodb_table.api_stats.arn
  description = "DynamoDB table ARN"
}