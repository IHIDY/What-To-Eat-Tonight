resource "aws_lambda_function" "demo" {
  function_name = "${var.project_name}-lambda"
  handler       = "index.handler"
  runtime       = "python3.12"
  role          = var.lambda_role_arn

  filename = "${path.module}/lambda.zip"
}

resource "aws_lambda_function" "uploader" {
  function_name = "${var.project_name}-uploader"
  handler       = "app.handler"
  runtime       = "python3.12"
  role          = var.lambda_role_arn
  filename      = "${path.module}/uploader.zip"

  # Increase timeout for batch uploads (default is 3 seconds)
  timeout = 60  # 60 seconds (1 minute)

  # Increase memory for faster processing
  memory_size = 512  # MB (default is 128)

  environment {
    variables = {
      S3_BUCKET_NAME = var.s3_bucket_name
    }
  }
}

