resource "aws_s3_bucket" "recipes" {
  bucket = var.bucket_name
}

resource "aws_s3_bucket_versioning" "versioning" {
  bucket = aws_s3_bucket.recipes.id

  versioning_configuration {
    status = "Enabled"
  }
}
