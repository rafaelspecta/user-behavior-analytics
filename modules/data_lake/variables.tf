variable "environment" {
  description = "Environment name (e.g., dev, prod)"
  type        = string
}

variable "project_name" {
  description = "Name of the project"
  type        = string
}

variable "bronze_bucket_name" {
  description = "Name of the bronze layer S3 bucket"
  type        = string
}

variable "silver_bucket_name" {
  description = "Name of the silver layer S3 bucket"
  type        = string
}

variable "gold_bucket_name" {
  description = "Name of the gold layer S3 bucket"
  type        = string
}

variable "enable_redshift" {
  description = "Whether to enable Redshift cluster"
  type        = bool
  default     = false
}

variable "redshift_config" {
  description = "Configuration for Redshift cluster"
  type = object({
    master_username = string
    master_password = string
    node_type       = string
    nodes           = number
  })
  default = {
    master_username = "admin"
    master_password = "ChangeMe123!"
    node_type       = "dc2.large"
    nodes           = 2
  }
} 