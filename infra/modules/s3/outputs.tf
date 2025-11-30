output "bucket_name" {
  value = aws_s3_bucket.recipes.bucket
}

output "bucket_arn" {
  value = aws_s3_bucket.recipes.arn
}
