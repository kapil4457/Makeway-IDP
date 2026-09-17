output "vpc_id" {
  description = "VPC ID"
  value       = aws_vpc.main.id
}

output "private_subnet_ids" {
  description = "Private subnet IDs"
  value       = aws_subnet.private[*].id
}

output "public_subnet_ids" {
  description = "Public subnet IDs"
  value       = aws_subnet.public[*].id
}

# Private subnets in the AZs the public subnets (and therefore the ALB) cover.
# The ALB only health-checks and routes to targets in its own AZs, so
# ALB-fronted compute must place tasks/instances here — a target in any other
# AZ is never probed (Target.NotInUse) and fails ELB health checks in a loop.
output "alb_reachable_private_subnet_ids" {
  description = "Private subnet IDs in the ALB-covered AZs"
  value = [
    for s in aws_subnet.private : s.id
    if contains([for p in aws_subnet.public : p.availability_zone], s.availability_zone)
  ]
}