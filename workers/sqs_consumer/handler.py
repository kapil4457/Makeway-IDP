import json
import os

import boto3


step_functions = boto3.client(
    "stepfunctions",
    region_name=os.environ["AWS_REGION"],
)

STATE_MACHINE_ARN = os.environ[
    "APP_CREATION_STATE_MACHINE_ARN"
]


def handler(event, context):

    for record in event["Records"]:

        body = json.loads(
            record["body"]
        )

        step_functions.start_execution(
            stateMachineArn=STATE_MACHINE_ARN,
            input=json.dumps(body),
        )

    return {
        "status": "ok"
    }