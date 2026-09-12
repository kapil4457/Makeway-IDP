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

# --- VPC ---
#
# Note: the GitHub Actions OIDC variables (role name, org/repo, owner/repo IDs,
# branch, environment, policy ARNs) moved to terraform/bootstrap/. So the role
# survives a platform `terraform destroy` and CI can always redeploy.

variable "vpc_cidr" {
  description = "CIDR block for the platform VPC."
  type        = string
  default     = "10.0.0.0/16"
}

variable "availability_zones" {
  description = "Availability zones to spread private/public subnets across (2+ required for RDS)."
  type        = list(string)
  default     = ["ap-south-1a", "ap-south-1b"]
}

variable "private_subnet_cidrs" {
  description = "CIDR blocks for the private subnets (one per availability zone)."
  type        = list(string)
  default     = ["10.0.1.0/24", "10.0.2.0/24"]
}

variable "public_subnet_cidrs" {
  description = "CIDR blocks for the public subnets (one per availability zone)."
  type        = list(string)
  default     = ["10.0.101.0/24", "10.0.102.0/24"]
}

# --- ECS (control plane hosting) ---

variable "ecs_cluster_name" {
  description = "Name of the ECS cluster that hosts the platform services."
  type        = string
  default     = "makeway"
}

variable "ecs_service_name" {
  description = "Name of the ECS service running the control plane."
  type        = string
  default     = "control-plane"
}

variable "ecs_image" {
  description = "Control-plane container image (Docker Hub or ECR)."
  type        = string
  default     = "kapil4457/makeway-control-plane:latest"
}

variable "app_secret_key" {
  description = "JWT signing secret for the control plane. Leave empty to auto-generate on apply (stored in encrypted state)."
  type        = string
  sensitive   = true
  default     = ""
}

# --- RDS (control plane database) ---

variable "rds_identifier" {
  description = "RDS instance identifier."
  type        = string
  default     = "makeway-db"
}

variable "rds_engine" {
  description = "RDS engine (postgres, mysql, aurora-postgresql, ...)."
  type        = string
  default     = "postgres"
}

variable "database_name" {
  description = "Initial database name in the RDS instance."
  type        = string
  default     = "makeway"
}

variable "db_username" {
  description = "RDS master username."
  type        = string
  default     = "postgres"
}

variable "db_password" {
  description = "RDS master password. Leave empty to auto-generate on apply (stored in encrypted state)."
  type        = string
  sensitive   = true
  default     = "password"
}

# --- ALB (platform front door) ---

variable "alb_name" {
  description = "Prefix for all ALB resources (load balancer, target group, security group)."
  type        = string
  default     = "makeway"
}

variable "alb_container_port" {
  description = "Port the platform-UI container listens on. The ALB forwards here and the task SG opens it from the ALB."
  type        = number
  default     = 80
}

variable "alb_listeners" {
  description = "Ingress ports to open on the ALB security group (internet-facing)."
  type        = list(string)
  default     = ["80"]
}

variable "alb_health_check_path" {
  description = "Path the ALB probes to mark the platform-UI tasks healthy."
  type        = string
  default     = "/"
}

variable "alb_health_check_matcher" {
  description = "HTTP status codes counted as healthy by the ALB health check."
  type        = string
  default     = "200,301,302,307,404"
}

variable "alb_target_group_name" {
  description = "Name of the ALB TG (unique per region). Distinct from the load balancer name so a port change can recreate the group without a name collision."
  type        = string
  default     = "makeway-ui"
}

variable "frontend_image" {
  description = "Platform-UI container image (nginx serving the built SPA). Empty string disables the ui_* resources in the ECS module."
  type        = string
  default     = "kapil4457/makeway-frontend:latest"
}

# --- App-creation workflow (Step 1 — GitHub Setup / GitOps) ---

variable "github_owner" {
  description = "GitHub organization/user that owns Makeway's platform repo and the generated app repos."
  type        = string
  default     = "kapil4457"
}

variable "github_pat" {
  description = "GitHub PAT (repo + workflow scopes) used to create app repos and open gitops PRs. Stored in Secrets Manager. Leave empty: the secret is created empty and must be set before first use."
  type        = string
  sensitive   = true
  default     = ""
}

variable "control_plane_url" {
  description = "Vestigial: workers now reach the control plane in-VPC via Cloud Map (http://control-plane.makeway.internal:8000), so this value is no longer consumed by any resource. Kept declared because CI still passes TF_VAR_control_plane_url (and the guards check it)."
  type        = string
}

variable "internal_api_key" {
  description = "Shared secret for the control-plane internal API (X-Internal-API-Key). Leave empty to auto-generate on apply (stored in encrypted state). Must stay in sync with the control plane."
  type        = string
  sensitive   = true
  default     = ""
}

variable "makeway_platform_repo" {
  description = "Makeway platform repository (hosts the platform code and argocd/ gitops configs)."
  type        = string
  default     = "Makeway-IDP"
}

# --- App-creation workflow (Step 2 — Crossplane infra provisioning) ---
#
# These three are the FALLBACK/default cluster access for the Step-2 Lambda
# (per-environment endpoint/token/CA now come from the control-plane Cluster
# registry — each env cluster is registered with its own exposed endpoint +
# makeway-worker token). The Step-2 worker uses these values only when a
# registered cluster row has no token; the health reporter uses them for its
# single-cluster sweep. The Crossplane ProviderConfig on each cluster and the
# Step-2 Lambda must target the same AWS account.

variable "kube_api_endpoint" {
  description = "Fallback default cluster kube-apiserver URL the Step-2 Lambda reaches, e.g. https://k8s.makeway.dev (pinggy/ingress in front of the cluster). Per-env endpoints come from the Cluster registry at runtime."
  type        = string
}

variable "kube_ca_cert" {
  description = "Fallback base64 CA bundle of the exposed cluster (KUBE_CA_CERT). Empty disables TLS verification — only for a local dev cluster behind a tunnel."
  type        = string
  sensitive   = true
  default     = ""
}

variable "kube_token" {
  description = "Fallback bearer token for a 'makeway-worker' ServiceAccount on the default cluster. Per-cluster tokens are registered on each Cluster row."
  type        = string
  sensitive   = true
}

variable "step2_max_attempts" {
  description = "Budget of Step-2 Claim checks before the flow times out (attempts * wait_seconds ≈ total infra budget; default 30x30s ≈ 15 min for RDS)."
  type        = number
  default     = 30
}

# --- ArgoCD health reporter ---
#
# Scheduled Lambda that mirrors live ArgoCD Applications into DeploymentSetup
# rows on the control plane (feeds GET /app/{app}/status). Uses the same
# KUBE_* access as Step 2.

variable "health_reporter_schedule" {
  description = "EventBridge rate/cron expression for the ArgoCD health sweep, e.g. 'rate(5 minutes)'."
  type        = string
  default     = "rate(5 minutes)"
}

# --- Bastion / SSM Session Manager ---

variable "bastion_ssh_public_key_path" {
  description = "Path to an SSH public key for the bastion host. Optional — the bastion is reached via SSM Session Manager (no key material needed), so leave empty to skip creating a key pair entirely."
  type        = string
  default     = ""
}