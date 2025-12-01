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
  source      = "./modules/s3"
  bucket_name = "${var.project_name}-recipes"
}

module "iam" {
  source          = "./modules/iam"
  project_name    = var.project_name
  s3_bucket_arn   = module.s3.bucket_arn
}

module "lambda" {
  source          = "./modules/lambda"
  project_name    = var.project_name
  lambda_role_arn = module.iam.lambda_role_arn
  s3_bucket_name  = module.s3.bucket_name
}

module "apigw" {
  source                        = "./modules/apigw"
  project_name                  = var.project_name
  lambda_function_name          = module.lambda.lambda_function_name
  lambda_invoke_arn             = module.lambda.lambda_invoke_arn
  lambda_uploader_function_name = module.lambda.uploader_function_name
  lambda_uploader_invoke_arn    = module.lambda.uploader_invoke_arn
}
