variable "bucket_name" {
  type = string
}

variable "vision_processor_lambda_arn" {
  type        = string
  description = "ARN of the Vision Processor Lambda function"
}
