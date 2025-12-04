resource "aws_lambda_layer_version" "python_deps" {
  filename            = "${path.module}/python-deps.zip"
  layer_name          = "${var.project_name}-python-deps"
  source_code_hash    = filebase64sha256("${path.module}/python-deps.zip")
  compatible_runtimes = ["python3.12"]

  description = "Python dependencies layer (openai and dependencies)"
}