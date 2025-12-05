output "domain_endpoint" {
  value       = aws_opensearch_domain.recipes.endpoint
  description = "OpenSearch domain endpoint"
}

output "domain_arn" {
  value       = aws_opensearch_domain.recipes.arn
  description = "OpenSearch domain ARN"
}

output "domain_id" {
  value       = aws_opensearch_domain.recipes.domain_id
  description = "OpenSearch domain ID"
}

output "kibana_endpoint" {
  value       = aws_opensearch_domain.recipes.dashboard_endpoint
  description = "OpenSearch Dashboards endpoint"
}