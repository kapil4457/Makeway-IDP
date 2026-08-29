#
# App-creation Step Functions workflow — Step 1 (GitHub Setup) and its Lambda.
#
# The SQS consumer fans each {request_id, job_id} message into this state
# machine. Step 1 runs the GitHub Setup worker, which:
#   - scaffolds the app's services monorepo (golden-path folders + CI),
#   - publishes argocd/apps/<appName>/ gitops into the platform repo (via PR),
#   - reports IN_PROGRESS / SUCCESS / FAILED through the control-plane internal
#     API.
# The handler reports FAILED itself and then raises, so the state machine only
# drives the invocation and turns the raise into an execution failure.
# Additional worker steps are appended to the States map as they land.

# --- Lambda package ----------------------------------------------------------
# The handler resolves templates/ ci_templates/ gitops_templates/ relative to
# __file__, so each folder must sit beside the handler at the zip root —
# hence source_dir (not source_file).
data "archive_file" "step1" {
  type        = "zip"
  source_dir  = var.handler_source_dir
  output_path = "${path.module}/dist/${var.name}.zip"
  excludes    = ["__pycache__/**", "__pycache__", "*.pyc"]
}

# --- GitHub PAT (Secrets Manager) --------------------------------------------
# Read by the Step-1 Lambda at runtime — never baked into images or repos.
# Supply var.github_pat with a real PAT (classic token, repo + workflow) in
# tfvars before first use; until then the secret holds an empty string and
# GitHub calls fail loudly (401) rather than silently misbehaving.
resource "aws_secretsmanager_secret" "github_pat" {
  name        = var.github_token_secret_name
  description = "GitHub PAT used by the Makeway Step-1 worker (repo creation + gitops PRs)."
}

resource "aws_secretsmanager_secret_version" "github_pat" {
  secret_id     = aws_secretsmanager_secret.github_pat.id
  secret_string = var.github_pat
}

# --- IAM — Step-1 Lambda ------------------------------------------------------

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "step1_read_secret" {
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.github_pat.arn]
  }
}

resource "aws_iam_role" "step1" {
  name               = "${var.name}-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_policy" "step1_read_secret" {
  name   = "${var.name}-read-secret"
  policy = data.aws_iam_policy_document.step1_read_secret.json
}

resource "aws_iam_role_policy_attachment" "step1_secret" {
  role       = aws_iam_role.step1.name
  policy_arn = aws_iam_policy.step1_read_secret.arn
}

resource "aws_iam_role_policy_attachment" "step1_logs" {
  role       = aws_iam_role.step1.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# --- Step-1 Lambda -------------------------------------------------------------

resource "aws_lambda_function" "step1" {
  function_name    = var.name
  role             = aws_iam_role.step1.arn
  runtime          = "python3.12"
  handler          = "handler.handler"
  filename         = data.archive_file.step1.output_path
  source_code_hash = data.archive_file.step1.output_base64sha256

  timeout     = var.lambda_timeout_seconds
  memory_size = var.lambda_memory_mb

  environment {
    variables = {
      GITHUB_OWNER           = var.github_owner
      GITHUB_TOKEN_SECRET_ID = aws_secretsmanager_secret.github_pat.name
      CONTROL_PLANE_URL      = var.control_plane_url
      INTERNAL_API_KEY       = var.internal_api_key
      MAKEWAY_PLATFORM_REPO  = var.makeway_platform_repo
    }
  }
}

# --- State machine -------------------------------------------------------------

data "aws_iam_policy_document" "sfn_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "sfn_invoke" {
  statement {
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.step1.arn]
  }
}

resource "aws_iam_role" "sfn" {
  name               = "${var.name}-sfn-role"
  assume_role_policy = data.aws_iam_policy_document.sfn_assume.json
}

resource "aws_iam_policy" "sfn_invoke" {
  name   = "${var.name}-sfn-invoke-lambda"
  policy = data.aws_iam_policy_document.sfn_invoke.json
}

resource "aws_iam_role_policy_attachment" "sfn_invoke" {
  role       = aws_iam_role.sfn.name
  policy_arn = aws_iam_policy.sfn_invoke.arn
}

resource "aws_sfn_state_machine" "app_creation" {
  name     = var.state_machine_name
  role_arn = aws_iam_role.sfn.arn

  definition = jsonencode({
    Comment = "Makeway app-creation workflow. Step 1 (GitHub Setup) scaffolds the services monorepo, publishes argocd/apps/<app> gitops into the platform repo, and reports request status via the control-plane internal API. The worker reports FAILED itself and then raises, so the state machine just surfaces the failure."
    StartAt = "Step1 GitHub Setup"
    States = {
      "Step1 GitHub Setup" = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.step1.arn
          Payload = {
            "request_id.$"    = "$.request_id"
            "job_id.$"        = "$.job_id"
            "execution_arn.$" = "$$.Execution.Id"
          }
        }
        Retry = [
          {
            ErrorEquals     = ["Lambda.ServiceException", "Lambda.AWSLambdaException", "Lambda.SdkClientException"]
            IntervalSeconds = 5
            MaxAttempts     = 3
            BackoffRate     = 2
          }
        ]
        Catch = [
          {
            ErrorEquals = ["States.ALL"]
            Next        = "Fail"
          }
        ]
        End = true
      }
      Fail = {
        Type  = "Fail"
        Error = "Step1Failed"
        Cause = "Step 1 (GitHub Setup) raised. The worker already reported FAILED to the control plane."
      }
    }
  })
}