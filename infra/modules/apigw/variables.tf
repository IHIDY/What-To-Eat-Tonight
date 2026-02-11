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

variable "lambda_uploader_function_name" {
  type = string
  description = "Uploader Lambda function name for permissions"
}

variable "lambda_uploader_invoke_arn" {
  type = string
  description = "Uploader Lambda invoke ARN for API Gateway integration"
}

variable "recipe_search_function_name" {
  type = string
  description = "Recipe search Lambda function name for permissions"
}

variable "recipe_search_invoke_arn" {
  type = string
  description = "Recipe search Lambda invoke ARN for API Gateway integration"
}

variable "login_function_name" {
  type        = string
  description = "Login Lambda function name for permissions"
}

variable "login_invoke_arn" {
  type        = string
  description = "Login Lambda invoke ARN for API Gateway integration"
}
