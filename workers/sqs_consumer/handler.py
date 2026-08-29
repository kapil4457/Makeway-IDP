import json
import logging
import os

import boto3


logger = logging.getLogger()
logger.setLevel(logging.INFO)


step_functions = boto3.client(
    "stepfunctions",
    region_name=os.environ.get("AWS_REGION", "ap-south-1"),
)

STATE_MACHINE_ARN = os.environ.get(
    "APP_CREATION_STATE_MACHINE_ARN",
    "",
)


def handler(event, context):

    for record in event["Records"]:

        body = json.loads(
            record["body"]
        )

        if not STATE_MACHINE_ARN:
            logger.warning(
                "Skip triggering state machine: APP_CREATION_STATE_MACHINE_ARN not set. body=%s",
                body,
            )
            continue

        # Deterministic execution name so at-least-once SQS delivery can't spin
        # up two overlapping executions for the same request. Step Functions
        # allows a new execution with the same name once the previous one has
        # completed, so genuine retries after a failure still start fresh.
        execution_name = "app-creation-{}-{}".format(
            body.get("request_id") or "unknown",
            body.get("job_id") or 0,
        )

        step_functions.start_execution(
            stateMachineArn=STATE_MACHINE_ARN,
            name=execution_name,
            input=json.dumps(body),
        )

    return {
        "status": "ok"
    }