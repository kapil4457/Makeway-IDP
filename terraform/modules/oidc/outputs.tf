output "role_arn" {
  description = "ARN of the GitHub Actions OIDC role. Set this as the AWS_ROLE_ARN secret."
  value       = aws_iam_role.github_actions.arn
}

output "role_name" {
  description = "Name of the GitHub Actions OIDC role."
  value       = aws_iam_role.github_actions.name
}