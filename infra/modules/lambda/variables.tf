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
