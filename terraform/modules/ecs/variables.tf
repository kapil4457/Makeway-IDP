variable "name" {
  description = "Cluster name, used as the prefix for every resource this module creates."
  type        = string
}

variable "service_name" {
  description = "Name of the ECS service."
  type        = string
  default     = "app"
}

variable "region" {
  description = "AWS region (used by the awslogs driver)."
  type        = string
}

variable "vpc_id" {
  description = "VPC the container instances and tasks run in."
  type        = string
}

variable "subnet_ids" {
  description = "Subnets for the Auto Scaling group and task ENIs (private preferred)."
  type        = list(string)
}

variable "container_image" {
  description = "Container image to run (ECR or Docker Hub)."
  type        = string
}

variable "container_port" {
  description = "Port the container listens on."
  type        = number
  default     = 8000
}

variable "container_memory" {
  description = "Hard memory limit for the container (MiB). EC2 launch type requires memory or memoryReservation."
  type        = number
  default     = 512
}

variable "desired_count" {
  description = "Number of tasks to run."
  type        = number
  default     = 1
}

variable "instance_type" {
  description = "EC2 instance type for the container instances."
  type        = string
  default     = "t3.micro"
}

variable "min_size" {
  description = "Minimum Auto Scaling group size (0 lets the cluster scale to zero)."
  type        = number
  default     = 0
}

variable "max_size" {
  description = "Maximum Auto Scaling group size."
  type        = number
  default     = 2
}

# No desired_capacity variable: the ASG's size is owned by the ECS capacity
# provider's managed scaling (see the aws_autoscaling_group resource in
# main.tf). Pinning it made Terraform fight the provider on every apply.

variable "environment" {
  description = "Environment variables passed to the container."
  type        = map(string)
  default     = {}
}

variable "task_role_policy_arns" {
  description = "IAM policy ARNs attached to the task role (what the app itself may call)."
  type        = list(string)
  default     = []
}

variable "target_group_arn" {
  description = "ALB target group to register the tasks against (ip target type). Leave null for no load balancer."
  type        = string
  default     = null
}

variable "service_registry_arn" {
  description = "Cloud Map service registry ARN to register the tasks into (null = none). Lets in-cluster callers resolve the tasks by DNS name even as task ENI IPs churn."
  type        = string
  default     = null
}

variable "ui_container_image" {
  description = "Platform-UI container image (nginx serving the built SPA). Empty string disables the UI task definition and service."
  type        = string
  default     = ""
}

variable "ui_service_name" {
  description = "Name of the ECS service running the platform UI."
  type        = string
  default     = "frontend"
}

variable "ui_desired_count" {
  description = "Number of UI tasks to run."
  type        = number
  default     = 1
}

variable "ui_container_port" {
  description = "Port the UI container listens on (nginx)."
  type        = number
  default     = 80
}

variable "ui_container_memory_reservation" {
  description = "Soft memory reservation (MiB) for the UI container. No hard limit, so UI + control plane fit one t3.micro."
  type        = number
  default     = 128
}

variable "ui_target_group_arn" {
  description = "ALB target group to register the UI tasks against (ip target type). Required when ui_container_image is set."
  type        = string
  default     = null
}