variable "project_name" {
  type = string
}

variable "lambda_role_arn" {
  type        = string
  description = "ARN of the Lambda execution role (used as OpenSearch master user)"
}