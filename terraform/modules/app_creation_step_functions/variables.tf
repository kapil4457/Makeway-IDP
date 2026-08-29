variable "name" {
  description = "Resource name prefix / Lambda function name for Step 1."
  type        = string
}

variable "handler_source_dir" {
  description = "Directory containing the Step-1 handler.py and its templates/ ci_templates/ gitops_templates/ folders. Zipped with the templates at the zip root (the handler resolves them relative to __file__)."
  type        = string
}

variable "github_owner" {
  description = "GitHub organization/user that owns the generated app repos and the PAT."
  type        = string
}

variable "github_pat" {
  description = "GitHub PAT (repo + workflow scopes) stored in Secrets Manager. Leave empty and set the secret value before first use."
  type        = string
  sensitive   = true
  default     = ""
}

variable "github_token_secret_name" {
  description = "Name of the Secrets Manager secret holding the GitHub PAT."
  type        = string
  default     = "makeway/github-pat"
}

variable "control_plane_url" {
  description = "Base URL of the control-plane internal API, reachable from the Step-1 Lambda (e.g. the ALB DNS name or a domain in front of it)."
  type        = string
}

variable "internal_api_key" {
  description = "Shared secret for the control-plane internal API (X-Internal-API-Key). Must match the control-plane's INTERNAL_API_KEY env var."
  type        = string
  sensitive   = true
}

variable "makeway_platform_repo" {
  description = "Repo in github_owner that hosts the Makeway platform code and argocd/ configs (GitOps is published into it)."
  type        = string
  default     = "Makeway-IDP"
}

variable "state_machine_name" {
  description = "Name of the app-creation Step Functions state machine."
  type        = string
  default     = "makeway-app-creation"
}

variable "lambda_timeout_seconds" {
  description = "Step-1 Lambda timeout (GitHub git-database API pushes can take a while)."
  type        = number
  default     = 900
}

variable "lambda_memory_mb" {
  description = "Step-1 Lambda memory (stdlib-only code — modest footprint)."
  type        = number
  default     = 256
}