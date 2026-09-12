variable "name" {
  description = "Prefix for all ALB resources."
  type        = string
}

variable "vpc_id" {
  description = "VPC to place the load balancer in."
  type        = string
}

variable "public_subnet_ids" {
  description = "Public subnets for the internet-facing load balancer."
  type        = list(string)
}

variable "container_port" {
  description = "Port the ECS tasks listen on (target group + ALB->task route)."
  type        = number
  default     = 8000
}

variable "target_group_name" {
  description = "Name of the target group (unique per region). Defaults to the load balancer name; set a distinct name so a port change can recreate it without a name collision."
  type        = string
  default     = null
}

variable "listeners" {
  description = "Ingress ports to open on the load balancer SG (e.g. [\"80\"])."
  type        = list(string)
  default     = ["80"]
}

variable "health_check_path" {
  description = "Path the ALB probes to mark tasks healthy."
  type        = string
  default     = "/docs"
}

variable "health_check_interval" {
  description = "Health check interval in seconds."
  type        = number
  default     = 30
}

variable "health_check_timeout" {
  description = "Health check timeout in seconds (must be < interval)."
  type        = number
  default     = 5
}

variable "health_check_healthy_threshold" {
  description = "Consecutive successes before a target is healthy."
  type        = number
  default     = 2
}

variable "health_check_unhealthy_threshold" {
  description = "Consecutive failures before a target is unhealthy."
  type        = number
  default     = 3
}

variable "health_check_matcher" {
  description = "HTTP codes counted as healthy."
  type        = string
  default     = "200,301,302,307,404"
}