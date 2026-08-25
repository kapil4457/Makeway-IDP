variable "name" {
  description = "CloudFront distribution name."
  type        = string
}

variable "s3_bucket_id" {
  description = "S3 bucket ID/name."
  type        = string
}

variable "s3_bucket_arn" {
  description = "S3 bucket ARN."
  type        = string
}

variable "s3_bucket_regional_domain_name" {
  description = "S3 regional domain name."
  type        = string
}