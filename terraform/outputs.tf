output "github_actions_role_arn" {
  description = "ARN of the GitHub Actions OIDC role. Use this as the AWS_ROLE_ARN GitHub secret."
  value       = module.oidc_github_actions.role_arn
}

output "app_creation_queue_url" {
  description = "URL of the app-creation SQS queue."
  value       = module.sqs.url
}

output "app_creation_queue_arn" {
  description = "ARN of the app-creation SQS queue."
  value       = module.sqs.arn
}