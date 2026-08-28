output "cluster_id" {
  description = "ECS cluster ID."
  value       = aws_ecs_cluster.this.id
}

output "cluster_name" {
  description = "ECS cluster name."
  value       = aws_ecs_cluster.this.name
}

output "service_name" {
  description = "ECS service name."
  value       = aws_ecs_service.this.name
}

output "task_definition_arn" {
  description = "Task definition ARN."
  value       = aws_ecs_task_definition.this.arn
}

output "security_group_id" {
  description = "Security group of the task ENIs. Peer it from other SGs (e.g. RDS 5432)."
  value       = aws_security_group.app.id
}

output "task_role_arn" {
  description = "ARN of the task IAM role."
  value       = aws_iam_role.task.arn
}

output "execution_role_arn" {
  description = "ARN of the task execution IAM role."
  value       = aws_iam_role.execution.arn
}

output "capacity_provider_name" {
  description = "Name of the EC2 capacity provider."
  value       = aws_ecs_capacity_provider.this.name
}