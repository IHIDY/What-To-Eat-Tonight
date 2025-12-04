resource "aws_s3_bucket" "recipes" {
  bucket = var.bucket_name
}

resource "aws_s3_bucket_versioning" "versioning" {
  bucket = aws_s3_bucket.recipes.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_cors_configuration" "recipes_cors" {
  bucket = aws_s3_bucket.recipes.id

  cors_rule {
    allowed_headers = ["*"]
    allowed_methods = ["GET", "PUT", "POST", "DELETE", "HEAD"]
    allowed_origins = ["*"]
    expose_headers  = ["ETag"]
    max_age_seconds = 3000
  }
}

# Lambda permission to allow S3 to invoke Vision Processor Lambda
resource "aws_lambda_permission" "allow_s3_invoke_vision_processor" {
  statement_id  = "AllowS3InvokeVisionProcessor"
  action        = "lambda:InvokeFunction"
  function_name = var.vision_processor_lambda_arn
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.recipes.arn
}

# S3 bucket notification to trigger Vision Processor Lambda
resource "aws_s3_bucket_notification" "bucket_notification" {
  bucket = aws_s3_bucket.recipes.id

  lambda_function {
    lambda_function_arn = var.vision_processor_lambda_arn
    events              = ["s3:ObjectCreated:*", "s3:ObjectRemoved:*"]
    filter_prefix       = "images/raw/"
  }

  depends_on = [aws_lambda_permission.allow_s3_invoke_vision_processor]
}
