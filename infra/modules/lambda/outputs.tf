output "lambda_function_name" {
  value = aws_lambda_function.demo.function_name
}

output "lambda_invoke_arn" {
  value = aws_lambda_function.demo.invoke_arn
}

output "lambda_function_arn" {
  value = aws_lambda_function.demo.arn
}
