output "id" {
  description = "Bucket ID."
  value       = aws_s3_bucket.this.id
}

output "arn" {
  description = "Bucket ARN."
  value       = aws_s3_bucket.this.arn
}

output "name" {
  description = "Bucket name."
  value       = aws_s3_bucket.this.bucket
}

output "regional_domain_name" {
  description = "Regional S3 domain name."
  value       = aws_s3_bucket.this.bucket_regional_domain_name
}