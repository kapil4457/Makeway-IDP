# GitHub Actions OIDC identity now lives in terraform/bootstrap/ (own state),
# so the platform root no longer owns this resource or its output. The role ARN
# is available from `terraform output github_actions_role_arn` in bootstrap/.

output "app_creation_queue_url" {
  description = "URL of the app-creation SQS queue."
  value       = module.sqs.url
}

output "app_creation_queue_arn" {
  description = "ARN of the app-creation SQS queue."
  value       = module.sqs.arn
}

output "ecs_cluster_name" {
  description = "ECS cluster hosting the control plane."
  value       = module.ecs.cluster_name
}

output "ecs_service_name" {
  description = "ECS service running the control plane."
  value       = module.ecs.service_name
}

output "ecs_task_role_arn" {
  description = "IAM role the control-plane tasks run as."
  value       = module.ecs.task_role_arn
}

output "app_security_group_id" {
  description = "Security group of the control-plane task ENIs (peer point for RDS)."
  value       = module.ecs.security_group_id
}

output "control_plane_db_endpoint" {
  description = "PostgreSQL endpoint of the control-plane database."
  value       = module.rds.endpoint
}

output "control_plane_db_name" {
  description = "Name of the control-plane database."
  value       = module.rds.database_name
}

output "alb_dns_name" {
  description = "DNS name of the control-plane ALB. Point your domain's CNAME here (or A record to the zone_id)."
  value       = module.alb.dns_name
}

output "alb_zone_id" {
  description = "Route 53 hosted zone ID of the control-plane ALB."
  value       = module.alb.zone_id
}