resource "aws_s3_bucket" "bronze" {
  bucket = var.bronze_bucket_name
  acl    = "private"

  versioning {
    enabled = true
  }

  server_side_encryption_configuration {
    rule {
      apply_server_side_encryption_by_default {
        sse_algorithm = "AES256"
      }
    }
  }

  lifecycle_rule {
    id      = "transition_to_ia"
    enabled = true

    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }
  }

  tags = {
    Environment = var.environment
    Project     = var.project_name
    Layer       = "bronze"
  }
}

resource "aws_s3_bucket" "silver" {
  bucket = var.silver_bucket_name
  acl    = "private"

  versioning {
    enabled = true
  }

  server_side_encryption_configuration {
    rule {
      apply_server_side_encryption_by_default {
        sse_algorithm = "AES256"
      }
    }
  }

  tags = {
    Environment = var.environment
    Project     = var.project_name
    Layer       = "silver"
  }
}

resource "aws_s3_bucket" "gold" {
  bucket = var.gold_bucket_name
  acl    = "private"

  versioning {
    enabled = true
  }

  server_side_encryption_configuration {
    rule {
      apply_server_side_encryption_by_default {
        sse_algorithm = "AES256"
      }
    }
  }

  tags = {
    Environment = var.environment
    Project     = var.project_name
    Layer       = "gold"
  }
}

# Optional Redshift cluster
resource "aws_redshift_cluster" "analytics" {
  count = var.enable_redshift ? 1 : 0

  cluster_identifier = "${var.project_name}-${var.environment}"
  database_name     = "analytics"
  master_username   = var.redshift_config.master_username
  master_password   = var.redshift_config.master_password
  node_type         = var.redshift_config.node_type
  number_of_nodes   = var.redshift_config.nodes

  skip_final_snapshot = true

  tags = {
    Environment = var.environment
    Project     = var.project_name
  }
} 