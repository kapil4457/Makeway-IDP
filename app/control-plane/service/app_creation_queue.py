import json
import os

import boto3


class AppCreationQueue:

    def __init__(self):
        self.queue_url = os.environ[
            "APP_CREATION_QUEUE_URL"
        ]

        region = (
            os.environ.get("SQS_REGION")
            or os.environ.get("AWS_REGION")
            or os.environ.get("AWS_DEFAULT_REGION")
            or "ap-south-1"
        )

        endpoint_url = os.environ.get("SQS_ENDPOINT_URL") or None

        self.client = boto3.client(
            "sqs",
            region_name=region,
            endpoint_url=endpoint_url,
        )

    def publish(
        self,
        *,
        request_id: int,
        job_id: int,
    ) -> str:

        response = self.client.send_message(
            QueueUrl=self.queue_url,
            MessageBody=json.dumps(
                {
                    "request_id": request_id,
                    "job_id": job_id,
                }
            ),
        )

        return response["MessageId"]