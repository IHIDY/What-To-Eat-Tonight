variable "project_name" {
  type = string
}

variable "lambda_function_name" {
  type = string
  description = "Lambda function name for permissions"
}

variable "lambda_invoke_arn" {
  type = string
  description = "Lambda invoke ARN for API Gateway integration"
}
