variable "bucket_name" {
  description = "Name of the S3 bucket used to store Terraform state."
  type        = string
}

variable "tags" {
  description = "Tags applied to the Terraform state bucket."
  type        = map(string)
  default     = {}
}