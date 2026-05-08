terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.region
}

module "s3" {
  source                       = "./modules/s3"
  bucket_name                  = "${var.project_name}-recipes"
  vision_processor_lambda_arn  = module.lambda.vision_processor_function_arn
}

module "iam" {
  source                       = "./modules/iam"
  project_name                 = var.project_name
  s3_bucket_arn                = module.s3.bucket_arn
  vision_processor_lambda_arn  = module.lambda.vision_processor_function_arn
}

module "lambda_layer" {
  source       = "./modules/lambda-layer"
  project_name = var.project_name
}

module "lambda" {
  source               = "./modules/lambda"
  project_name         = var.project_name
  lambda_role_arn      = module.iam.lambda_role_arn
  s3_bucket_name       = module.s3.bucket_name
  lambda_layer_arn     = module.lambda_layer.layer_arn
  opensearch_endpoint  = module.opensearch.domain_endpoint
  hashed_password      = var.hashed_password
  openai_api_key       = var.openai_api_key
}

module "opensearch" {
  source            = "./modules/opensearch"
  project_name      = var.project_name
  lambda_role_arn   = module.iam.lambda_role_arn
}

module "dynamodb" {
  source       = "./modules/dynamodb"
  project_name = var.project_name
}

module "apigw" {
  source                        = "./modules/apigw"
  project_name                  = var.project_name
  lambda_function_name          = module.lambda.lambda_function_name
  lambda_invoke_arn             = module.lambda.lambda_invoke_arn
  lambda_uploader_function_name = module.lambda.uploader_function_name
  lambda_uploader_invoke_arn    = module.lambda.uploader_invoke_arn
  recipe_search_function_name   = module.lambda.recipe_search_function_name
  recipe_search_invoke_arn      = module.lambda.recipe_search_invoke_arn
  login_function_name           = module.lambda.login_function_name
  login_invoke_arn              = module.lambda.login_invoke_arn
}
