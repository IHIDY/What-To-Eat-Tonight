data "aws_region" "current" {}

resource "aws_lambda_function" "demo" {
  function_name = "${var.project_name}-lambda"
  handler       = "app.handler"
  runtime       = "python3.12"
  role          = var.lambda_role_arn
  filename      = "${path.module}/chat.zip"
  source_code_hash = filebase64sha256("${path.module}/chat.zip")

  # Use Lambda Layer for dependencies
  layers = [var.lambda_layer_arn]

  # Chat with LLM can take time
  timeout = 60  # 60 seconds (1 minute)
  memory_size = 1024  # MB

  environment {
    variables = {
      S3_BUCKET_NAME      = var.s3_bucket_name
      OPENSEARCH_ENDPOINT = var.opensearch_endpoint
      OPENAI_API_KEY      = var.openai_api_key
      DYNAMODB_TABLE_NAME = "${var.project_name}-api-stats"
    }
  }
}

resource "aws_lambda_function" "uploader" {
  function_name = "${var.project_name}-uploader"
  handler       = "app.handler"
  runtime       = "python3.12"
  role          = var.lambda_role_arn
  filename      = "${path.module}/uploader.zip"
  source_code_hash = filebase64sha256("${path.module}/uploader.zip")

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

resource "aws_lambda_function" "vision_processor" {
  function_name = "${var.project_name}-vision-processor"
  handler       = "app.handler"
  runtime       = "python3.12"
  role          = var.lambda_role_arn
  filename      = "${path.module}/vision-processor.zip"
  source_code_hash = filebase64sha256("${path.module}/vision-processor.zip")

  # Use Lambda Layer for dependencies
  layers = [var.lambda_layer_arn]

  # Vision processing with OpenAI can take time
  timeout = 120  # 120 seconds (2 minutes)

  # Need more memory for image processing
  memory_size = 2048  # MB

  environment {
    variables = {
      S3_BUCKET_NAME      = var.s3_bucket_name
      OPENAI_API_KEY      = var.openai_api_key
      OPENSEARCH_ENDPOINT = var.opensearch_endpoint
    }
  }
}

resource "aws_lambda_function" "recipe_search" {
  function_name = "${var.project_name}-recipe-search"
  handler       = "app.handler"
  runtime       = "python3.12"
  role          = var.lambda_role_arn
  filename      = "${path.module}/recipe-search.zip"
  source_code_hash = filebase64sha256("${path.module}/recipe-search.zip")

  # Use Lambda Layer for dependencies
  layers = [var.lambda_layer_arn]

  # Search should be fast
  timeout = 30  # 30 seconds
  memory_size = 512  # MB

  environment {
    variables = {
      S3_BUCKET_NAME      = var.s3_bucket_name
      OPENSEARCH_ENDPOINT = var.opensearch_endpoint
      DYNAMODB_TABLE_NAME = "${var.project_name}-api-stats"
    }
  }
}

resource "aws_lambda_function" "login" {
  function_name = "${var.project_name}-login"
  handler       = "app.handler"
  runtime       = "python3.12"
  role          = var.lambda_role_arn
  filename      = "${path.module}/login.zip"
  source_code_hash = filebase64sha256("${path.module}/login.zip")

  timeout     = 10
  memory_size = 128

  environment {
    variables = {
      HASHED_PASSWORD     = var.hashed_password
      DYNAMODB_TABLE_NAME = "${var.project_name}-api-stats"
    }
  }
}

