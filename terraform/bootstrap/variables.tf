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

# Names of the platform credential containers owned by this root. The
# platform root's app_creation module defaults to the same names (see
# modules/app_creation_step_functions/variables.tf) and references them by
# name only — keep the two defaults in sync.
variable "github_token_secret_name" {
  description = "Name of the Secrets Manager secret holding the GitHub PAT."
  type        = string
  default     = "makeway/github-pat"
}

variable "app_repo_ci_secret_name" {
  description = "Name of the Secrets Manager secret holding app-repo CI credentials (Docker Hub image/username/token)."
  type        = string
  default     = "makeway/app-repo-ci"
}
