variable "region" {
  description = "AWS region for the GitHub Actions OIDC identity."
  type        = string
  default     = "ap-south-1"
}

variable "github_actions_role_name" {
  description = "Name of the IAM role GitHub Actions assumes via OIDC."
  type        = string
  default     = "github-actions-terraform"
}

variable "github_org" {
  description = "GitHub owner (organization or user) that holds the repository."
  type        = string
  default     = "kapil4457"
}

variable "github_repo" {
  description = "GitHub repository name (without the owner)."
  type        = string
  default     = "Makeway-IDP"
}

variable "github_owner_id" {
  description = "Numeric ID of the GitHub owner. Part of the immutable OIDC subject claim."
  type        = string
}

variable "github_repo_id" {
  description = "Numeric ID of the GitHub repository. Part of the immutable OIDC subject claim."
  type        = string
}

variable "github_deploy_environment" {
  description = "GitHub Actions environment whose jobs assume the role."
  type        = string
  default     = "makeway-infra-deploy"
}

variable "github_branch" {
  description = "Branch allowed to assume the GitHub Actions role."
  type        = string
  default     = "main"
}

variable "github_actions_policy_arns" {
  description = "IAM policy ARNs attached to the GitHub Actions role."
  type        = list(string)
  default     = ["arn:aws:iam::aws:policy/AdministratorAccess"]
}
