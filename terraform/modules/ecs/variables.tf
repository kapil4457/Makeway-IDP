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

variable "desired_capacity" {
  description = "Start size of the Auto Scaling group; managed scaling adjusts from here."
  type        = number
  default     = 1
}

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

variable "ssh_source_security_group_id" {
  description = "Security group ID of the ECS Instance Connect Endpoint. When set, opens TCP/22 on the instance SG only from that SG (no effect when empty)."
  type        = string
  default     = ""
}