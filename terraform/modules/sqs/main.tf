resource "aws_sqs_queue" "dlq" {
  name = "${var.name}-dlq"

  message_retention_seconds = 1209600
}

resource "aws_sqs_queue" "this" {
  name = var.name

  visibility_timeout_seconds = 60

  message_retention_seconds = 345600

  receive_wait_time_seconds = 20

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = 5
  })
}