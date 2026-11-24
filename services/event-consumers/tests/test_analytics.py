"""analytics consumer: deterministic S3 objects, flat rows, retry-safe (moto S3)."""

import base64
import gzip
import json
import uuid

import boto3
import pytest
from moto import mock_aws

from sg_consumers import analytics, common

EV = "9abf74ae-c14f-46e1-9e8f-8ee9872b7995"


def rec(env, seq, shard="shardId-000000000000"):
    return {
        "eventID": f"{shard}:{seq}",
        "kinesis": {
            "sequenceNumber": seq,
            "data": base64.b64encode(json.dumps(env).encode()).decode(),
        },
    }


def env(kind, data, at="2026-11-24T18:10:55Z"):
    return {"id": str(uuid.uuid4()), "type": kind, "sale_event_id": EV, "at": at, "data": data}


@pytest.fixture
def s3(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("ANALYTICS_BUCKET", "analytics-test")
    common.client.cache_clear()
    with mock_aws():
        c = boto3.client("s3", region_name="ap-south-1")
        c.create_bucket(
            Bucket="analytics-test", CreateBucketConfiguration={"LocationConstraint": "ap-south-1"}
        )
        yield c
    common.client.cache_clear()


def read(c, key):
    return [
        json.loads(x)
        for x in gzip.decompress(
            c.get_object(Bucket="analytics-test", Key=key)["Body"].read()
        ).splitlines()
    ]


def keys(c):
    return sorted(o["Key"] for o in c.list_objects_v2(Bucket="analytics-test").get("Contents", []))


def test_batch_becomes_one_object_per_hour_with_flat_rows(s3):
    e1 = env("seat_held", {"seats": ["A-1-1", "A-1-2"], "amount_paise": 300000})
    e2 = env("order_paid", {"seats": ["A-1-1", "A-1-2"], "amount_paise": 300000, "late": False})
    e3 = env("joined", {"sub": "b1"}, at="2026-11-24T19:00:01Z")  # next hour
    out = analytics.handler({"Records": [rec(e1, "10"), rec(e2, "11"), rec(e3, "12")]}, None)
    assert out == {"batchItemFailures": []}
    assert keys(s3) == [
        "events/dt=2026-11-24/hour=18/shardId-000000000000-10-11.json.gz",
        "events/dt=2026-11-24/hour=19/shardId-000000000000-12-12.json.gz",
    ]
    rows = read(s3, keys(s3)[0])
    assert rows[1] | {"data": None} == {
        "id": e2["id"],
        "type": "order_paid",
        "sale_event_id": EV,
        "at": e2["at"],
        "seq": "11",
        "sub": None,
        "seats": 2,
        "amount_paise": 300000,
        "data": None,
    }
    assert json.loads(rows[1]["data"])["late"] is False


def test_retry_overwrites_the_same_object_no_copies(s3):
    batch = {"Records": [rec(env("joined", {"sub": "x"}), "20")]}
    analytics.handler(batch, None)
    first = s3.get_object(Bucket="analytics-test", Key=keys(s3)[0])["Body"].read()
    analytics.handler(batch, None)  # Lambda retried the same batch
    assert len(keys(s3)) == 1
    assert s3.get_object(Bucket="analytics-test", Key=keys(s3)[0])["Body"].read() == first


def test_s3_failure_retries_the_whole_batch(s3, monkeypatch):
    monkeypatch.setenv("ANALYTICS_BUCKET", "no-such-bucket")
    out = analytics.handler(
        {"Records": [rec(env("joined", {}), "30"), rec(env("joined", {}), "31")]}, None
    )
    assert out == {"batchItemFailures": [{"itemIdentifier": "30"}]}
