variable "project_name" {
  type = string
}

variable "lambda_role_arn" {
  type = string
}

variable "s3_bucket_name" {
  type        = string
  description = "S3 bucket name for storing uploads"
}

variable "lambda_layer_arn" {
  type        = string
  description = "ARN of the Python dependencies Lambda Layer"
}

variable "opensearch_endpoint" {
  type        = string
  description = "OpenSearch domain endpoint"
}

variable "hashed_password" {
  type        = string
  description = "SHA-256 hash of the login password"
  sensitive   = true
}

variable "openai_api_key" {
  type        = string
  description = "OpenAI API key"
  sensitive   = true
}
