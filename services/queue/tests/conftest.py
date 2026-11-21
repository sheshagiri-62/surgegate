"""moto stands in for DynamoDB and SQS; the Lambda modules use them through boto3."""

import json
import os
import uuid

import boto3
import pytest
from moto import mock_aws

os.environ.setdefault("AWS_DEFAULT_REGION", "ap-south-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")

TEST_KEY = {"kid": "test-1", "key": "x" * 64}


@pytest.fixture
def aws(monkeypatch):
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="ap-south-1")
        ddb.create_table(
            TableName="queue",
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
                {"AttributeName": "active", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "active-queues",
                    "KeySchema": [{"AttributeName": "active", "KeyType": "HASH"}],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
        )
        sqs = boto3.client("sqs", region_name="ap-south-1")
        url = sqs.create_queue(QueueName="joins")["QueueUrl"]
        sm = boto3.client("secretsmanager", region_name="ap-south-1")
        sm.create_secret(Name="token-key", SecretString=json.dumps(TEST_KEY))
        monkeypatch.setenv("QUEUE_TABLE", "queue")
        monkeypatch.setenv("JOIN_QUEUE_URL", url)
        monkeypatch.setenv("TOKEN_KEY_SECRET", "token-key")
        from sg_queue import common, tokens

        common.table.cache_clear()
        common.sqs.cache_clear()
        common._meta_cache.clear()
        tokens._secrets.cache_clear()
        tokens._keys.clear()
        yield {"table": ddb.Table("queue"), "queue_url": url}


def open_queue(table, event_id=None, **overrides):
    event_id = event_id or str(uuid.uuid4())
    item = {
        "PK": f"EVENT#{event_id}",
        "SK": "META",
        "status": "open",
        "sale_starts_at": "2026-01-01T00:00:00+00:00",
        "admission_rate": 125,
        "next_position": 0,
        "serving_up_to": 0,
        "active": "1",
    }
    table.put_item(Item=item | overrides)
    return event_id


def api_event(event_id, sub="buyer-1", groups="[buyer]", **extra):
    """An API Gateway HTTP API (payload v2.0) event after the JWT authorizer."""
    jwt = {"claims": {"sub": sub, "cognito:groups": groups}}
    return {
        "pathParameters": {"event": event_id},
        "requestContext": {"authorizer": {"jwt": jwt}},
    } | extra


def body(resp):
    return json.loads(resp["body"])


def drain(queue_url):
    """Read every join message from (moto) SQS, as the Lambda event source mapping would."""
    sqs = boto3.client("sqs", region_name="ap-south-1")
    records = []
    while True:
        msgs = sqs.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=10).get("Messages", [])
        if not msgs:
            return {"Records": records}
        for m in msgs:
            records.append({"messageId": m["MessageId"], "body": m["Body"]})
            sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=m["ReceiptHandle"])
