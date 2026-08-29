variable "name" {
  description = "Prefix for the Lambda / IAM resources this module creates."
  type        = string
}

variable "queue_arn" {
  description = "ARN of the SQS queue the consumer watches."
  type        = string
}

variable "state_machine_arn" {
  description = "ARN of the Step Functions state machine triggered per message. Leave empty until the state machine exists."
  type        = string
  default     = ""
}

variable "handler_source_file" {
  description = "Path to the consumer handler.py packaged into the Lambda. Resolved relative to the terraform root where plan/apply run — e.g. \"../workers/sqs_consumer/handler.py\" (works on the CI Linux runner)."
  type        = string
}

variable "max_concurrency" {
  description = "Max number of concurrent Lambda invocations (the consumer pool size)."
  type        = number
  default     = 5
}

variable "batch_size" {
  description = "Number of SQS messages Lambda receives per invocation."
  type        = number
  default     = 1
}

variable "lambda_timeout_seconds" {
  description = "Lambda function timeout. Keep <= SQS visibility timeout (60s) so messages aren't redelivered mid-processing."
  type        = number
  default     = 30
}