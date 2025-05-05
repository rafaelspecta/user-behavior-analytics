terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 4.0"
    }
  }
  backend "s3" {
    bucket = "user-behavior-analytics-tfstate"
    key    = "dev/terraform.tfstate"
    region = "us-west-2"
  }
}

provider "aws" {
  region = var.aws_region
}

module "data_lake" {
  source = "../../modules/data_lake"

  environment = "dev"
  project_name = "user-behavior-analytics"
  
  # S3 bucket configurations
  bronze_bucket_name = "user-behavior-analytics-bronze"
  silver_bucket_name = "user-behavior-analytics-silver"
  gold_bucket_name   = "user-behavior-analytics-gold"
  
  # Optional Redshift configuration
  enable_redshift = true
  redshift_config = {
    node_type = "dc2.large"
    nodes     = 2
  }
}

module "kafka" {
  source = "../../modules/kafka"

  environment = "dev"
  project_name = "user-behavior-analytics"
  
  kafka_config = {
    instance_type = "kafka.m5.large"
    nodes         = 3
  }
}

module "iam" {
  source = "../../modules/iam"

  environment = "dev"
  project_name = "user-behavior-analytics"
  
  # S3 bucket ARNs for IAM policies
  bronze_bucket_arn = module.data_lake.bronze_bucket_arn
  silver_bucket_arn = module.data_lake.silver_bucket_arn
  gold_bucket_arn   = module.data_lake.gold_bucket_arn
} 