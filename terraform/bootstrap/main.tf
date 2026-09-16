# Bootstrap root: GitHub Actions OIDC identity ONLY.
#
# This lives in its own state (key "bootstrap/terraform.tfstate") so that a
# platform `terraform destroy` (terraform/) never removes the role that CI
# itself assumes to redeploy. Destroying the bootstrap root is deliberate and
# separate from destroying the platform.
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
  }

  backend "s3" {
    bucket       = "makeway-remote-backend"
    key          = "bootstrap/terraform.tfstate"
    region       = "us-east-1"
    use_lockfile = true
    encrypt      = true
  }
}

provider "aws" {
  region = var.region
}

module "oidc_github_actions" {
  source = "../modules/oidc"

  role_name                 = var.github_actions_role_name
  github_org                = var.github_org
  github_repo               = var.github_repo
  github_branch             = var.github_branch
  github_owner_id           = var.github_owner_id
  github_repo_id            = var.github_repo_id
  github_deploy_environment = var.github_deploy_environment
  attached_policy_arns      = var.github_actions_policy_arns
}

# --- Platform credential containers (Secrets Manager) -------------------------
# Same lifecycle rule as the OIDC identity above: these live HERE so a
# platform `terraform destroy` (terraform/) never removes them — destroying
# the platform used to schedule them for deletion, and AWS then rejects
# CreateSecret for a pending-deletion name, which blocked the next rebuild.
# The worker Lambdas reference them purely by name.
#
# Terraform owns the CONTAINERS only. Seed the VALUES once, out-of-band
# (rotate by re-running; nothing is ever baked into tfvars, CI, or git):
#
#   aws secretsmanager put-secret-value \
#     --secret-id <github_token_secret_name> \
#     --secret-string "ghp_..."
#
#   aws secretsmanager put-secret-value \
#     --secret-id <app_repo_ci_secret_name> \
#     --secret-string '{"dockerhub_image":"...","dockerhub_username":"...","dockerhub_token":"..."}'
#
# A terraform-managed empty version is impossible anyway — the API rejects a
# PutSecretValue with neither SecretString nor SecretBinary. Until a value is
# seeded the workers fail loudly / warn-and-continue, never silently.
resource "aws_secretsmanager_secret" "github_pat" {
  name        = var.github_token_secret_name
  description = "GitHub PAT used by the Makeway Step-1 worker (repo creation + gitops PRs)."
  # If this root is ever destroyed deliberately, delete immediately — a
  # pending-deletion zombie would block the next apply's CreateSecret.
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret" "app_repo_ci" {
  name        = var.app_repo_ci_secret_name
  description = "CI credentials (Docker Hub image/username/token) injected into app repos' GitHub Actions config by the Step-1 worker."
  # Same immediate-delete rationale as github_pat above.
  recovery_window_in_days = 0
}
