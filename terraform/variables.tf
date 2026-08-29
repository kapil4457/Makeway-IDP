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

# --- VPC ---

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

# --- ALB (control-plane front door) ---

variable "alb_name" {
  description = "Prefix for all ALB resources (load balancer, target group, security group)."
  type        = string
  default     = "makeway"
}

variable "alb_container_port" {
  description = "Port the control-plane container listens on. The ALB forwards here and the app SG opens it from the ALB."
  type        = number
  default     = 8000
}

variable "alb_listeners" {
  description = "Ingress ports to open on the ALB security group (internet-facing)."
  type        = list(string)
  default     = ["80"]
}

variable "alb_health_check_path" {
  description = "Path the ALB probes to mark the control-plane tasks healthy."
  type        = string
  default     = "/docs"
}

variable "alb_health_check_matcher" {
  description = "HTTP status codes counted as healthy by the ALB health check."
  type        = string
  default     = "200,301,302,307,404"
}

variable "ecs_ssh_source_security_group_id" {
  description = "Security group ID of the ECS Instance Connect Endpoint for SSH (TCP/22) into the container instances. Leave empty to use the built-in bastion EIC endpoint group."
  type        = string
  default     = ""
}

# --- Bastion / EC2 Instance Connect ---

variable "bastion_ssh_public_key_path" {
  description = "Path to an SSH public key for the bastion host. Leave empty to skip creating a key pair (Instance Connect brokers SSH without key material)."
  type        = string
  default     = ""
}