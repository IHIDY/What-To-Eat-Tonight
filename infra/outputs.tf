output "bucket_name" {
  value = module.s3.bucket_name
}

output "lambda_name" {
  value = module.lambda.lambda_function_name
}

output "api_url" {
  value = module.apigw.invoke_url
}

output "opensearch_endpoint" {
  value = module.opensearch.domain_endpoint
  description = "OpenSearch domain endpoint"
}

output "opensearch_dashboard_url" {
  value = try("https://${module.opensearch.kibana_endpoint}", null)
  description = "OpenSearch Dashboards URL"
}
