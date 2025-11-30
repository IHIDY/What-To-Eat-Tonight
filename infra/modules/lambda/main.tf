resource "aws_lambda_function" "demo" {
  function_name = "${var.project_name}-lambda"
  handler       = "index.handler"
  runtime       = "python3.12"
  role          = var.lambda_role_arn

  filename = "${path.module}/lambda.zip"
}
