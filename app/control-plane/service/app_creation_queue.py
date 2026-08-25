import json
import os

import boto3


class AppCreationQueue:

    def __init__(self):
        self.queue_url = os.environ[
            "APP_CREATION_QUEUE_URL"
        ]

        self.client = boto3.client(
            "sqs",
            region_name=os.environ.get(
                "AWS_REGION",
                "ap-south-1",
            ),
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