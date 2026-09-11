output "bucket_name" {
  value = module.s3.bucket_name
}

output "lambda_name" {
  value = module.lambda.lambda_function_name
}

output "api_url" {
  value = module.apigw.invoke_url
}

output "vision_processor_dlq_url" {
  value       = module.lambda.vision_processor_dlq_url
  description = "SQS queue holding failed vision-processor invocations - check here if a recipe never shows up after upload"
}
