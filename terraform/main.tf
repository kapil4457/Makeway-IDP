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
    bucket       = "makeway-terraform-state"
    key          = "platform/terraform.tfstate"
    region       = "ap-south-1"
    use_lockfile = true
    encrypt      = true
  }
}

provider "aws" {
  region = var.region
}

module "oidc_github_actions" {
  source = "./modules/oidc"

  role_name       = var.github_actions_role_name
  github_org      = var.github_org
  github_repo     = var.github_repo
  github_branch   = var.github_branch
  github_owner_id = var.github_owner_id
  github_repo_id  = var.github_repo_id
  attached_policy_arns = var.github_actions_policy_arns
}

module "sqs" {
  source = "./modules/sqs"

  name = var.sqs_queue_name
}