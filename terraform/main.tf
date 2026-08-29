terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
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

# Secrets are auto-generated on first apply when tfvars leaves them empty.
# Values persist in the encrypted remote state; supply them in tfvars to pin
# a known value instead.
resource "random_password" "db_password" {
  length  = 24
  special = false
}

resource "random_password" "app_secret_key" {
  length  = 48
  special = false
}

# Where each generated value is consumed (so the random resources aren't
# flagged as unused when both vars are supplied in tfvars):
#   local.db_password    -> aws_db_instance (RDS module), DATABASE_URL
#   local.app_secret_key -> SECRET_KEY

locals {
  db_password    = var.db_password != "" ? var.db_password : random_password.db_password.result
  app_secret_key = var.app_secret_key != "" ? var.app_secret_key : random_password.app_secret_key.result
}

# --- Bastion / SSM Session Manager ---
# Smallest feasible instance type (t4g.nano, ARM) relies on an arm64 AMI —
# Amazon Linux 2023 ARM64, latest GA.
data "aws_ami" "amazon_linux_2023_arm64" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-kernel-6.1-arm64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

module "vpc" {
  source               = "./modules/vpc"
  availability_zones   = var.availability_zones
  private_subnet_cidrs = var.private_subnet_cidrs
  public_subnet_cidrs  = var.public_subnet_cidrs
  vpc_cidr             = var.vpc_cidr
}

module "sqs" {
  source = "./modules/sqs"

  name = var.sqs_queue_name
}

# --- ALB (control-plane front door, public subnets) ---
# Internet -> ALB (public) -> ECS task ENIs (private). The app SG keeps the
# tasks unreachable from the internet; only the ALB can talk to them.

module "alb" {
  source = "./modules/alb"

  name                 = var.alb_name
  vpc_id               = module.vpc.vpc_id
  public_subnet_ids    = module.vpc.public_subnet_ids
  container_port       = var.alb_container_port
  listeners            = var.alb_listeners
  health_check_path    = var.alb_health_check_path
  health_check_matcher = var.alb_health_check_matcher
}

# The ECS tasks accept application traffic only from the ALB security group.
resource "aws_security_group_rule" "app_from_alb" {
  type                     = "ingress"
  from_port                = var.alb_container_port
  to_port                  = var.alb_container_port
  protocol                 = "tcp"
  security_group_id        = module.ecs.security_group_id
  source_security_group_id = module.alb.security_group_id
}

# --- RDS (control-plane database) ---
# The DB subnet group must span 2+ AZs; the RDS security group admits traffic
# only from the control-plane task security group (rule below).

resource "aws_db_subnet_group" "main" {
  name       = "makeway-db"
  subnet_ids = module.vpc.private_subnet_ids
}

resource "aws_security_group" "rds" {
  name        = "makeway-rds"
  description = "PostgreSQL access for the control plane"
  vpc_id      = module.vpc.vpc_id
}

module "rds" {
  source = "./modules/rds"

  name                 = var.rds_identifier
  engine               = var.rds_engine
  database_name        = var.database_name
  username             = var.db_username
  password             = local.db_password
  db_subnet_group_name = aws_db_subnet_group.main.name
  security_group_ids   = [aws_security_group.rds.id]
}

# --- Bastion / SSM Session Manager ---
# The ALB's security group is internet-facing (listeners 80), but the RDS SG
# admits traffic only from the ECS task SG. To reach RDS from your laptop
# (sQleur Electron) we route through a tiny bastion via SSM Session Manager
# port-forwarding. (EC2 Instance Connect Endpoint is not offered in ap-south-1,
# so SSM is the jump-host path.) The bastion carries the
# AmazonSSMManagedInstanceCore role below, which is what makes this work.

# Optional SSH key pair for the bastion (direct SSH is unnecessary — SSM
# brokers sessions and port-forwards without key material — so leave
# bastion_ssh_public_key_path empty to skip creating one entirely).
resource "aws_key_pair" "bastion" {
  count      = var.bastion_ssh_public_key_path == "" ? 0 : 1
  key_name   = "makeway-bastion"
  public_key = file(var.bastion_ssh_public_key_path)

  tags = {
    Name = "makeway-bastion"
  }
}

resource "aws_security_group" "bastion" {
  name        = "makeway-bastion"
  # NOTE: do not change this description — `description` is ForceNew and would
  # force a full SG replacement (deadlock: old SG is attached to the instance,
  # and the same SG name can't be recreated until it's gone).
  description = "Security group for the Makeway bastion host"
  vpc_id      = module.vpc.vpc_id

  # No ingress rules: the bastion is reached only via SSM Session Manager,
  # which requires no inbound ports. Outbound (to the SSM endpoint and RDS)
  # is all-open below.
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_iam_role" "bastion" {
  name = "makeway-bastion"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "bastion_ssm" {
  role       = aws_iam_role.bastion.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "bastion" {
  name = "makeway-bastion"
  role = aws_iam_role.bastion.name
}

resource "aws_instance" "bastion" {
  ami                    = data.aws_ami.amazon_linux_2023_arm64.id
  instance_type          = "t4g.nano"
  subnet_id              = module.vpc.public_subnet_ids[0]
  vpc_security_group_ids = [aws_security_group.bastion.id]
  key_name               = length(aws_key_pair.bastion) > 0 ? aws_key_pair.bastion[0].key_name : null
  iam_instance_profile   = aws_iam_instance_profile.bastion.name
  user_data = base64encode(<<-EOF
    #!/bin/bash
    set -x
    sudo yum install -y postgresql15
  EOF
  )

  tags = {
    Name = "makeway-bastion"
  }
}

# --- ECS (control plane hosting, EC2 launch type) ---

# The task role needs to publish/consume the app-creation queue — same actions
# the local makeway-sa service account holds in the dev environment.
resource "aws_iam_policy" "control_plane_sqs" {
  name        = "makeway-control-plane-sqs"
  description = "Control-plane task role: publish/consume the app-creation queue."
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "sqs:SendMessage",
        "sqs:SendMessageBatch",
        "sqs:GetQueueUrl",
        "sqs:ReceiveMessage",
        "sqs:DeleteMessage",
        "sqs:ChangeMessageVisibility",
      ]
      Resource = [module.sqs.arn, module.sqs.dlq_arn]
    }]
  })
}

module "ecs" {
  source = "./modules/ecs"

  name             = var.ecs_cluster_name
  service_name     = var.ecs_service_name
  region           = var.region
  vpc_id           = module.vpc.vpc_id
  subnet_ids       = module.vpc.private_subnet_ids
  container_image  = var.ecs_image
  target_group_arn = module.alb.target_group_arn

  task_role_policy_arns = [aws_iam_policy.control_plane_sqs.arn]

  environment = {
    DATABASE_URL           = "postgresql://${var.db_username}:${local.db_password}@${module.rds.endpoint}:${module.rds.port}/${var.database_name}"
    APP_CREATION_QUEUE_URL = module.sqs.url
    SQS_REGION             = var.region
    AWS_REGION             = var.region
    AWS_DEFAULT_REGION     = var.region
    SECRET_KEY             = local.app_secret_key
    LOG_LEVEL              = "INFO"
  }
}

# PostgreSQL ingress only from the control-plane tasks.
resource "aws_security_group_rule" "rds_from_control_plane" {
  type                     = "ingress"
  from_port                = 5432
  to_port                  = 5432
  protocol                 = "tcp"
  security_group_id        = aws_security_group.rds.id
  source_security_group_id = module.ecs.security_group_id
}

# PostgreSQL ingress for the bastion, so sQleur Electron can reach RDS over
# an SSM Session Manager port-forward from the bastion.
resource "aws_security_group_rule" "rds_from_bastion" {
  type                     = "ingress"
  from_port                = 5432
  to_port                  = 5432
  protocol                 = "tcp"
  security_group_id        = aws_security_group.rds.id
  source_security_group_id = aws_security_group.bastion.id
}