variable "role_name" {
  description = "Name of the IAM role assumed by GitHub Actions via OIDC."
  type        = string
}

variable "github_org" {
  description = "GitHub organization or owner that holds the repository."
  type        = string
}

variable "github_repo" {
  description = "GitHub repository name (without the owner)."
  type        = string
}

variable "github_branch" {
  description = "Branch that is allowed to assume this role."
  type        = string
  default     = "main"
}

variable "github_owner_id" {
  description = "Numeric ID of the GitHub owner. Part of the immutable OIDC subject claim."
  type        = string
}

variable "github_repo_id" {
  description = "Numeric ID of the GitHub repository. Part of the immutable OIDC subject claim."
  type        = string
}

variable "aws_region" {
  description = "AWS region the role/oidc provider is scoped to."
  type        = string
  default     = "ap-south-1"
}

variable "attached_policy_arns" {
  description = "IAM policy ARNs to attach to the role (e.g. AdministratorAccess for platform infra)."
  type        = list(string)
  default     = ["arn:aws:iam::aws:policy/AdministratorAccess"]
}