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

# --- Step 2 (Crossplane infra provisioning) ---------------------------------

variable "step2_name" {
  description = "Name of the Step-2 (Crossplane Provisioning) Lambda."
  type        = string
  default     = "makeway-app-creation-step2"
}

variable "step2_handler_source_dir" {
  description = "Directory containing the Step-2 handler.py and its claim_templates/ folder. Zipped with the templates at the zip root (the handler resolves them relative to __file__)."
  type        = string
}

variable "step2_timeout_seconds" {
  description = "Step-2 Lambda timeout (applies Claims, reads connection Secrets, provisions IAM + Secrets Manager, commits gitops)."
  type        = number
  default     = 900
}

variable "step2_memory_mb" {
  description = "Step-2 Lambda memory (stdlib-only + boto3 — modest footprint)."
  type        = number
  default     = 256
}

variable "kube_api_endpoint" {
  description = "Base URL of the (exposed) cluster kube-apiserver the Step-2 Lambda reaches, e.g. https://k8s.makeway.dev (pinggy/ngrok/ingress in front of the local cluster)."
  type        = string
}

variable "kube_ca_cert" {
  description = "Base64 CA bundle of the exposed cluster (KUBE_CA_CERT). Empty disables TLS verification — required for a raw-TCP tunnel (e.g. pinggy), where the apiserver's self-signed cert can't match the tunnel hostname."
  type        = string
  default     = ""
  sensitive   = true
}

variable "kube_token" {
  description = "Bearer token for a 'makeway-worker' ServiceAccount on the cluster, scoped to create Claims / read Secrets in app namespaces."
  type        = string
  sensitive   = true
}

variable "secrets_prefix" {
  description = "Prefix (no leading/trailing slash) of Secrets Manager secret names the Step-2 Lambda writes, e.g. 'makeway'. Secrets are named {prefix}/{app}/{env}/{capability-slug}."
  type        = string
  default     = "makeway"
}

variable "step2_wait_seconds" {
  description = "Pause between Claim checks in the state-machine Wait/Check/Choice loop (RDS can take 10-15 min)."
  type        = number
  default     = 30
}

variable "step2_max_attempts" {
  description = "Budget of Check iterations before the Step-2 flow fails (max_attempts * wait_seconds ≈ total infra budget)."
  type        = number
  default     = 30
}

variable "rds_publicly_accessible" {
  description = "Local-cluster seam: expose RDS publicly (pods run off-VPC). Set false on managed EKS."
  type        = bool
  default     = true
}

variable "rds_ingress_cidr" {
  description = "CIDR allowed inbound on 5432 for RDS. Local cluster: the machine's public IP. Managed EKS: the worker-node / VPC CIDR."
  type        = string
  default     = "0.0.0.0/0"
}