#
# ArgoCD health reporter — a scheduled Lambda that mirrors the live ArgoCD
# Application inventory into the control plane's DeploymentSetup table so
# GET /app/{app}/status shows real service health.
#
# The Lambda has NO AWS API permissions beyond logging: it talks to the
# (exposed) cluster kube-apiserver over HTTPS and to the control-plane
# internal API — both with credentials supplied as env vars. EventBridge
# fires it on the schedule below.
#
# Requires the same exposed-cluster env as the Step-2 worker (KUBE_*).

# --- Lambda package ----------------------------------------------------------

data "archive_file" "health_reporter" {
  type        = "zip"
  source_dir  = var.handler_source_dir
  output_path = "${path.module}/dist/${var.name}.zip"
  excludes    = ["__pycache__/**", "__pycache__", "*.pyc"]
}

# --- IAM ----------------------------------------------------------------------

resource "aws_iam_role" "health_reporter" {
  name = var.name

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = "sts:AssumeRole"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "health_reporter_logs" {
  role       = aws_iam_role.health_reporter.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# --- Lambda -------------------------------------------------------------------

resource "aws_lambda_function" "health_reporter" {
  function_name    = var.name
  role             = aws_iam_role.health_reporter.arn
  runtime          = "python3.12"
  handler          = "handler.handler"
  filename         = data.archive_file.health_reporter.output_path
  source_code_hash = data.archive_file.health_reporter.output_base64sha256

  timeout     = var.timeout_seconds
  memory_size = var.memory_mb

  environment {
    variables = {
      CONTROL_PLANE_URL = var.control_plane_url
      INTERNAL_API_KEY  = var.internal_api_key
      KUBE_API_ENDPOINT = var.kube_api_endpoint
      KUBE_CA_CERT      = var.kube_ca_cert
      KUBE_TOKEN        = var.kube_token
      ARGOCD_NAMESPACE  = var.argocd_namespace
    }
  }
}

# --- Schedule (EventBridge) ---------------------------------------------------

resource "aws_cloudwatch_event_rule" "health_reporter" {
  name                = "${var.name}-schedule"
  schedule_expression = var.schedule_expression
}

resource "aws_cloudwatch_event_target" "health_reporter" {
  rule      = aws_cloudwatch_event_rule.health_reporter.name
  target_id = var.name
  arn       = aws_lambda_function.health_reporter.arn
}

resource "aws_lambda_permission" "health_reporter" {
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.health_reporter.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.health_reporter.arn
}