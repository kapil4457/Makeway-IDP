output "arn" {
  description = "ALB ARN."
  value       = aws_lb.this.arn
}

output "dns_name" {
  description = "DNS name of the load balancer (point your domain/CNAME here)."
  value       = aws_lb.this.dns_name
}

output "zone_id" {
  description = "Route 53 hosted zone ID of the load balancer."
  value       = aws_lb.this.zone_id
}

output "name" {
  description = "ALB name."
  value       = aws_lb.this.name
}

output "target_group_arn" {
  description = "ARN of the target group the ECS tasks register against."
  value       = aws_lb_target_group.this.arn
}

output "security_group_id" {
  description = "Security group of the load balancer."
  value       = aws_security_group.lb.id
}