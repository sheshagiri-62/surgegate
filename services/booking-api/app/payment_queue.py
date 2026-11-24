"""SQS queue between the webhook endpoint and the order worker (blueprint "Payment intake").

The endpoint only verifies and enqueues (fast 200); the worker does the database work. The
message body is the RAW webhook body; attributes carry the provider's event id and type.
"""

from __future__ import annotations

import os
from functools import lru_cache


@lru_cache(maxsize=1)
def sqs():
    import boto3
    from botocore.config import Config

    return boto3.client(
        "sqs",
        region_name=os.getenv("AWS_REGION", "ap-south-1"),
        config=Config(connect_timeout=2, read_timeout=25, retries={"max_attempts": 3}),
    )


def queue_url() -> str:
    return os.environ["PAYMENTS_QUEUE_URL"]


def send(raw_body: bytes, event_id: str, event_type: str) -> None:
    sqs().send_message(
        QueueUrl=queue_url(),
        MessageBody=raw_body.decode(),
        MessageAttributes={
            "event_id": {"DataType": "String", "StringValue": event_id or "-"},
            "event": {"DataType": "String", "StringValue": event_type},
        },
    )
