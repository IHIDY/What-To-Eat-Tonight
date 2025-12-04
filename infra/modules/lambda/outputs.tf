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
