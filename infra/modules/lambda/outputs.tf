output "lambda_function_name" {
  value = aws_lambda_function.demo.function_name
}

output "lambda_invoke_arn" {
  value = aws_lambda_function.demo.invoke_arn
}

output "lambda_function_arn" {
  value = aws_lambda_function.demo.arn
}

output "uploader_function_name" {
  value = aws_lambda_function.uploader.function_name
}

output "uploader_invoke_arn" {
  value = aws_lambda_function.uploader.invoke_arn
}

output "uploader_function_arn" {
  value = aws_lambda_function.uploader.arn
}

output "vision_processor_function_name" {
  value = aws_lambda_function.vision_processor.function_name
}

output "vision_processor_function_arn" {
  value = aws_lambda_function.vision_processor.arn
}

output "vision_processor_dlq_arn" {
  value = aws_sqs_queue.vision_processor_dlq.arn
}

output "vision_processor_dlq_url" {
  value = aws_sqs_queue.vision_processor_dlq.url
}

output "recipe_search_function_name" {
  value = aws_lambda_function.recipe_search.function_name
}

output "recipe_search_invoke_arn" {
  value = aws_lambda_function.recipe_search.invoke_arn
}

output "recipe_search_function_arn" {
  value = aws_lambda_function.recipe_search.arn
}

output "login_function_name" {
  value = aws_lambda_function.login.function_name
}

output "login_invoke_arn" {
  value = aws_lambda_function.login.invoke_arn
}

output "login_function_arn" {
  value = aws_lambda_function.login.arn
}
