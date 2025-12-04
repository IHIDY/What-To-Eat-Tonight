output "layer_arn" {
  value       = aws_lambda_layer_version.python_deps.arn
  description = "ARN of the Python dependencies Lambda Layer"
}

output "layer_version" {
  value       = aws_lambda_layer_version.python_deps.version
  description = "Version of the Lambda Layer"
}