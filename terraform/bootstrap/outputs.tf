output "github_actions_role_arn" {
  description = "ARN of the GitHub Actions OIDC role. Set this as the AWS_ROLE_ARN GitHub secret."
  value       = module.oidc_github_actions.role_arn
}

output "github_actions_role_name" {
  description = "Name of the GitHub Actions OIDC role."
  value       = module.oidc_github_actions.role_name
}
