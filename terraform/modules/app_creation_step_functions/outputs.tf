output "state_machine_arn" {
  description = "ARN of the app-creation state machine (fed to the SQS consumer as APP_CREATION_STATE_MACHINE_ARN)."
  value       = aws_sfn_state_machine.app_creation.arn
}

output "step1_function_arn" {
  description = "ARN of the Step-1 (GitHub Setup) Lambda."
  value       = aws_lambda_function.step1.arn
}

output "step1_function_name" {
  description = "Name of the Step-1 (GitHub Setup) Lambda."
  value       = aws_lambda_function.step1.function_name
}

output "step1_zip_path" {
  description = "Path of the packaged Step-1 Lambda zip. Carried to the apply job as an artifact (the plan job builds it; apply runs on a fresh checkout)."
  value       = data.archive_file.step1.output_path
}

output "github_pat_secret_name" {
  description = "Name of the Secrets Manager secret holding the GitHub PAT."
  value       = aws_secretsmanager_secret.github_pat.name
}