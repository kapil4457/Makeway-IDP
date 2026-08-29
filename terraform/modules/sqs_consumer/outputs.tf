output "function_arn" {
  description = "ARN of the SQS consumer Lambda."
  value       = aws_lambda_function.consumer.arn
}

output "function_name" {
  description = "Name of the SQS consumer Lambda."
  value       = aws_lambda_function.consumer.function_name
}

output "role_arn" {
  description = "ARN of the Lambda execution role."
  value       = aws_iam_role.consumer.arn
}