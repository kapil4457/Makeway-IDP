#
# SQS consumer — app-creation request worker.
#
# A Lambda pool (capped at `max_concurrency` concurrent executions) that
# watches the app-creation SQS queue and fans each consumed message out to the
# Step Functions app-creation state machine.


data "archive_file" "consumer" {
  type        = "zip"
  source_file = var.handler_source_file
  output_path = "${path.module}/dist/${var.name}.zip"
}

#--- IAM -----------------------------------------------------------------------

data "aws_iam_policy_document" "assume_role" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

# Lambda polls the queue with its own execution role (SQS is a pull source —
# there is no push permission to grant the function here), and starts the
# state machine execution for each message.
data "aws_iam_policy_document" "consumer" {
  statement {
    actions = [
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sqs:GetQueueAttributes",
    ]
    resources = [var.queue_arn]
  }

  # Only grant states:StartExecution once the state machine ARN is known.
  dynamic "statement" {
    for_each = var.state_machine_arn != "" ? [1] : []
    content {
      actions   = ["states:StartExecution"]
      resources = [var.state_machine_arn]
    }
  }
}

resource "aws_iam_role" "consumer" {
  name               = "${var.name}-role"
  assume_role_policy = data.aws_iam_policy_document.assume_role.json
}

resource "aws_iam_role_policy" "consumer" {
  name   = "sqs-consumer"
  role   = aws_iam_role.consumer.id
  policy = data.aws_iam_policy_document.consumer.json
}

resource "aws_iam_role_policy_attachment" "consumer_logs" {
  role       = aws_iam_role.consumer.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

#--- Lambda --------------------------------------------------------------------

resource "aws_lambda_function" "consumer" {
  function_name    = var.name
  role             = aws_iam_role.consumer.arn
  runtime          = "python3.12"
  handler          = "handler.handler"
  filename         = data.archive_file.consumer.output_path
  source_code_hash = data.archive_file.consumer.output_base64sha256
  # The "pool": never more than `max_concurrency` Lambda invocations running
  # at once. SQS events queued beyond this wait for a free slot.
  reserved_concurrent_executions = var.max_concurrency

  timeout = var.lambda_timeout_seconds

  environment {
    variables = merge(
      { AWS_REGION = var.region },
      var.state_machine_arn != ""
      ? { APP_CREATION_STATE_MACHINE_ARN = var.state_machine_arn }
      : {},
    )
  }
}

#--- SQS trigger ("watcher") ---------------------------------------------------

resource "aws_lambda_event_source_mapping" "sqs" {
  event_source_arn = var.queue_arn
  function_name    = aws_lambda_function.consumer.arn

  batch_size = var.batch_size

  enabled = true
}