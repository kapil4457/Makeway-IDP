terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  backend "s3" {
    bucket       = "makeway-terraform-state"
    key          = "platform/clusters/qa/terraform.tfstate"
    region       = "ap-south-1"
    use_lockfile = true
    encrypt      = true
  }
}

provider "aws" {
  region = var.region
}

data "terraform_remote_state" "network" {
  backend = "s3"

  config = {
    bucket = "makeway-terraform-state"
    key    = "platform/network/terraform.tfstate"
    region = "ap-south-1"
  }
}

module "eks" {
  source = "../../modules/eks"

  cluster_name    = var.cluster_name
  cluster_version = var.cluster_version

  vpc_id = data.terraform_remote_state.network.outputs.vpc_id

  subnet_ids = data.terraform_remote_state.network.outputs.private_subnet_ids

  node_groups = var.node_groups
}