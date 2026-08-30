output "lambda_arn" {
  description = "ARN of the health-reporter Lambda (for other modules / debugging)."
  value       = aws_lambda_function.health_reporter.arn
}

output "lambda_name" {
  description = "Name of the health-reporter Lambda."
  value       = aws_lambda_function.health_reporter.function_name
}

output "schedule_rule_arn" {
  description = "ARN of the EventBridge schedule rule."
  value       = aws_cloudwatch_event_rule.health_reporter.arn
}