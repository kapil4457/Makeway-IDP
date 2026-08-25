output "id" {
  description = "SNS topic ID."
  value       = aws_sns_topic.this.id
}

output "arn" {
  description = "SNS topic ARN."
  value       = aws_sns_topic.this.arn
}

output "name" {
  description = "SNS topic name."
  value       = aws_sns_topic.this.name
}