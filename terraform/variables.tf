variable "region" {
  description = "AWS region for shared platform infrastructure."
  type        = string
  default     = "ap-south-1"
}

variable "sqs_queue_name" {
  description = "Name of the SQS queue used for the app-creation request pipeline."
  type        = string
  default     = "makeway-requests"
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
  default     = "Forge-IDP"
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