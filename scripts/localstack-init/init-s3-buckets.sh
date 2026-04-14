#!/bin/bash
# LocalStack S3 bucket initialization script
# This script runs automatically when LocalStack starts (mounted to /etc/localstack/init/ready.d/)

echo "Creating S3 buckets for User Behavior Analytics..."

# Create silver layer bucket
awslocal s3 mb s3://user-behavior-analytics-silver
echo "Created bucket: user-behavior-analytics-silver"

# Create gold layer bucket
awslocal s3 mb s3://user-behavior-analytics-gold
echo "Created bucket: user-behavior-analytics-gold"

# List all buckets to verify
echo "Verifying buckets..."
awslocal s3 ls

echo "S3 bucket initialization complete!"
