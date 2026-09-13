#
# App-creation Step Functions workflow — Step 1 (GitHub Setup) and Step 2
# (Crossplane infra provisioning) plus their Lambdas.
#
# The SQS consumer fans each {request_id, job_id} message into this state
# machine:
#   Step 1 (GitHub Setup)  scaffolds the services monorepo + argocd/apps/<app>/
#                          gitops, reports IN_PROGRESS/SUCCESS/FAILED.
#   Step 2 (Provisioning)  applies Crossplane Claims (apply), polls Ready+Synced
#                          (Wait -> check -> Choice loop), then extracts the
#                          connection Secrets into AWS Secrets Manager, creates
#                          a scoped IAM user/keys for AWS-API capabilities, and
#                          commits ExternalSecrets into gitops (extract).
# Each worker reports FAILED itself and then raises, so the state machine only
# drives the invocation and turns the raise into an execution failure.
#
# Step 2 reaches each environment's cluster (ArgoCD + Crossplane) through the
# exposed kube-apiserver, resolved per capability from the Cluster registry;
# KUBE_* env vars are the fallback default cluster. The Crossplane ProviderConfig
# on each cluster and these Lambdas must target the same AWS account.

# --- Lambda packages ----------------------------------------------------------
# Both handlers resolve templates/ claim_templates/ relative to __file__, so each
# folder must sit beside the handler at the zip root — hence source_dir.
data "archive_file" "step1" {
  type        = "zip"
  source_dir  = var.handler_source_dir
  output_path = "${path.module}/dist/${var.name}.zip"
  excludes    = ["__pycache__/**", "__pycache__", "*.pyc"]
}

data "archive_file" "step2" {
  type        = "zip"
  source_dir  = var.step2_handler_source_dir
  output_path = "${path.module}/dist/${var.step2_name}.zip"
  excludes    = ["__pycache__/**", "__pycache__", "*.pyc"]
}

# --- GitHub PAT (Secrets Manager) --------------------------------------------
# Read by the Step-1 Lambda at runtime — never baked into images or repos, and
# deliberately NOT put through CI or tfvars: Terraform owns the secret
# CONTAINER only. Populate the VALUE once, out-of-band (rotate by re-running):
#
#   aws secretsmanager put-secret-value \
#     --secret-id <var.github_token_secret_name> \
#     --secret-string "ghp_..."
#
# Until then GitHub calls fail loudly (401 / missing secret) rather than
# silently misbehaving. A terraform-managed empty version is impossible anyway
# — the API rejects a PutSecretValue with neither SecretString nor SecretBinary.
resource "aws_secretsmanager_secret" "github_pat" {
  name        = var.github_token_secret_name
  description = "GitHub PAT used by the Makeway Step-1 worker (repo creation + gitops PRs)."
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

# VPC-attached Lambdas create/delete their own ENIs (Hyperplane) on invoke.
resource "aws_iam_role_policy_attachment" "step1_vpc" {
  role       = aws_iam_role.step1.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
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

  # In-VPC: the control plane is fully private (Cloud Map resolves in-VPC only)
  # and the workers report to its internal API; NAT gives GitHub/AWS egress.
  vpc_config {
    subnet_ids         = var.subnet_ids
    security_group_ids = var.security_group_ids
  }

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

# --- IAM — Step-2 Lambda ------------------------------------------------------
# Reaches the cluster over HTTPS (no VPC/EC2 IAM needed). Needs Secrets Manager
# (mirror credentials + read the PAT), IAM (scoped per-capability users/keys),
# and STS (resolve its own account for ARNs).

data "aws_region" "current" {}

data "aws_caller_identity" "current" {}

resource "aws_iam_role" "step2" {
  name               = "${var.step2_name}-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "step2_permissions" {
  statement {
    sid       = "ReadGithubPat"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.github_pat.arn]
  }

  statement {
    sid = "MirrorCapabilitySecrets"
    actions = [
      "secretsmanager:CreateSecret",
      "secretsmanager:DescribeSecret",
      "secretsmanager:GetSecretValue",
      "secretsmanager:PutSecretValue",
    ]
    # Secret ARNs carry a random 6-char suffix after the name, hence the
    # trailing wildcard. Restricted to the makeway prefix.
    resources = [
      "arn:aws:secretsmanager:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:secret:${var.secrets_prefix}/*",
    ]
  }

  statement {
    sid = "ProvisionAwsIdentityUsers"
    actions = [
      "iam:CreateUser",
      "iam:DeleteUser",
      "iam:GetUser",
      "iam:CreateAccessKey",
      "iam:DeleteAccessKey",
      "iam:ListAccessKeys",
      "iam:PutUserPolicy",
      "iam:DeleteUserPolicy",
      "iam:TagUser",
    ]
    resources = [
      "arn:aws:iam::${data.aws_caller_identity.current.account_id}:user/makeway-*",
    ]
  }

  statement {
    sid       = "ResolveAccount"
    actions   = ["sts:GetCallerIdentity"]
    resources = ["*"]
  }

  # Platform VPC facts for claim rendering (vpcId, subnetIds, cidr) — published
  # by the platform root, read per apply (cached per warm container).
  statement {
    sid       = "ReadPlatformVpcFacts"
    actions   = ["ssm:GetParameter"]
    resources = ["arn:aws:ssm:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:parameter${var.platform_vpc_parameter_name}"]
  }
}

resource "aws_iam_policy" "step2" {
  name   = "${var.step2_name}-permissions"
  policy = data.aws_iam_policy_document.step2_permissions.json
}

resource "aws_iam_role_policy_attachment" "step2_permissions" {
  role       = aws_iam_role.step2.name
  policy_arn = aws_iam_policy.step2.arn
}

resource "aws_iam_role_policy_attachment" "step2_logs" {
  role       = aws_iam_role.step2.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Same VPC attachment as Step 1 (private control plane + NAT egress for the
# kube endpoints and AWS APIs).
resource "aws_iam_role_policy_attachment" "step2_vpc" {
  role       = aws_iam_role.step2.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

# --- Step-2 Lambda -------------------------------------------------------------

resource "aws_lambda_function" "step2" {
  function_name    = var.step2_name
  role             = aws_iam_role.step2.arn
  runtime          = "python3.12"
  handler          = "handler.handler"
  filename         = data.archive_file.step2.output_path
  source_code_hash = data.archive_file.step2.output_base64sha256

  timeout     = var.step2_timeout_seconds
  memory_size = var.step2_memory_mb

  # In-VPC: same reason as Step 1 — private control plane + NAT egress.
  vpc_config {
    subnet_ids         = var.subnet_ids
    security_group_ids = var.security_group_ids
  }

  environment {
    variables = {
      CONTROL_PLANE_URL      = var.control_plane_url
      INTERNAL_API_KEY       = var.internal_api_key
      GITHUB_OWNER           = var.github_owner
      GITHUB_TOKEN_SECRET_ID = aws_secretsmanager_secret.github_pat.name
      MAKEWAY_PLATFORM_REPO  = var.makeway_platform_repo
      # Fallback cluster only — per-env endpoint/token/CA come from the
      # Cluster registry via get_request_details.
      KUBE_API_ENDPOINT       = var.kube_api_endpoint
      KUBE_CA_CERT            = var.kube_ca_cert
      KUBE_TOKEN              = var.kube_token
      SECRETS_PREFIX          = var.secrets_prefix
      PLATFORM_VPC_PARAMETER  = var.platform_vpc_parameter_name
      RDS_PUBLICLY_ACCESSIBLE = tostring(var.rds_publicly_accessible)
      RDS_INGRESS_CIDR        = var.rds_ingress_cidr
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
    actions = ["lambda:InvokeFunction"]
    resources = [
      aws_lambda_function.step1.arn,
      aws_lambda_function.step2.arn,
    ]
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
    Comment = "Makeway app-creation workflow. Step 1 (GitHub Setup) scaffolds the services monorepo + argocd/apps/<app> gitops. Step 2 (Crossplane Provisioning) applies Claims into {app}-{env}, polls Ready+Synced (Wait/check/Choice, capped by the attempt budget), then extracts connection Secrets into Secrets Manager, provisions a scoped IAM user/keys for AWS-API capabilities, and commits ExternalSecrets into gitops. Workers report FAILED themselves then raise."
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
        # The lambda:invoke SDK integration returns the raw InvokeResponse
        # ({ExecutedVersion, Payload, SdkHttpMetadata, ...}) — the worker's
        # actual return dict is nested under Payload. OutputPath unwraps it so
        # the next state's input is the handler's payload itself (the contract
        # every Parameters template below assumes: $.request_id / $.job_id /
        # $.ready / $.attempt refer to handler return keys, not SDK fields).
        OutputPath = "$.Payload"
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
        Next = "Step2 Apply"
      }

      "Step2 Apply" = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.step2.arn
          Payload = {
            "action"          = "apply"
            "request_id.$"    = "$.request_id"
            "job_id.$"        = "$.job_id"
            "execution_arn.$" = "$$.Execution.Id"
          }
        }
        # Unwrap the SDK InvokeResponse — see Step1 GitHub Setup.
        OutputPath = "$.Payload"
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
        Next = "Step2 Wait"
      }

      "Step2 Wait" = {
        Type    = "Wait"
        Seconds = var.step2_wait_seconds
        Next    = "Step2 Check"
      }

      "Step2 Check" = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.step2.arn
          Payload = {
            "action"          = "check"
            "request_id.$"    = "$.request_id"
            "job_id.$"        = "$.job_id"
            "execution_arn.$" = "$$.Execution.Id"
            "attempt.$"       = "$.attempt"
          }
        }
        # Unwrap the SDK InvokeResponse — see Step1 GitHub Setup. The Ready? /
        # Attempt? Choices and the Retry Pass read $.ready / $.attempt /
        # $.request_id / $.job_id straight off this payload.
        OutputPath = "$.Payload"
        Retry = [
          {
            ErrorEquals     = ["Lambda.ServiceException", "Lambda.AWSLambdaException", "Lambda.SdkClientException", "States.Timeout"]
            IntervalSeconds = 10
            MaxAttempts     = 2
            BackoffRate     = 2
          }
        ]
        Catch = [
          {
            ErrorEquals = ["States.ALL"]
            Next        = "Fail"
          }
        ]
        Next = "Step2 Ready?"
      }

      "Step2 Ready?" = {
        Type = "Choice"
        Choices = [
          {
            Variable      = "$.ready"
            BooleanEquals = true
            Next          = "Step2 Extract"
          }
        ]
        Default = "Step2 Attempt?"
      }

      "Step2 Attempt?" = {
        Type = "Choice"
        Choices = [
          {
            Variable                 = "$.attempt"
            NumericGreaterThanEquals = var.step2_max_attempts
            Next                     = "Step2 TimedOut"
          }
        ]
        Default = "Step2 Retry"
      }

      "Step2 Retry" = {
        Type = "Pass"
        Parameters = {
          "request_id.$" = "$.request_id"
          "job_id.$"     = "$.job_id"
          "attempt.$"    = "States.MathAdd($.attempt, 1)"
        }
        Next = "Step2 Wait"
      }

      "Step2 Extract" = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.step2.arn
          Payload = {
            "action"          = "extract"
            "request_id.$"    = "$.request_id"
            "job_id.$"        = "$.job_id"
            "execution_arn.$" = "$$.Execution.Id"
          }
        }
        # Unwrap the SDK InvokeResponse — see Step1 GitHub Setup.
        OutputPath = "$.Payload"
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
        Next = "Success"
      }

      "Step2 TimedOut" = {
        Type  = "Fail"
        Error = "Step2Timeout"
        Cause = "Crossplane Claims did not reach Ready+Synced within the attempt budget."
      }

      "Success" = {
        Type = "Succeed"
      }

      "Fail" = {
        Type  = "Fail"
        Error = "StepFailed"
        Cause = "A worker raised after reporting FAILED to the control plane."
      }
    }
  })
}
