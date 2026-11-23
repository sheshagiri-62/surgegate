"""Sale events: one record per first join / first admission, partitioned by sale; never fatal."""

import json
import time

import boto3
import pytest

from sg_queue import admit, join, sale_events, sequencer, tokens
from tests.conftest import TEST_KEY, api_event, drain, open_queue


@pytest.fixture
def stream(aws, monkeypatch):
    k = boto3.client("kinesis", region_name="ap-south-1")
    k.create_stream(StreamName="sale-events", ShardCount=1)
    monkeypatch.setenv("SALE_EVENTS_STREAM", "sale-events")
    sale_events._kinesis.cache_clear()
    yield k
    sale_events._kinesis.cache_clear()


def records(k):
    shard = k.describe_stream(StreamName="sale-events")["StreamDescription"]["Shards"][0]["ShardId"]
    it = k.get_shard_iterator(
        StreamName="sale-events", ShardId=shard, ShardIteratorType="TRIM_HORIZON"
    )["ShardIterator"]
    out = k.get_records(ShardIterator=it)["Records"]
    return [(r["PartitionKey"], json.loads(r["Data"])) for r in out]


def test_each_new_place_publishes_one_joined_event_keyed_by_sale(aws, stream):
    ev = open_queue(aws["table"])
    for sub in ["a", "b", "a"]:  # "a" twice: one place, one event
        join.handler(api_event(ev, sub=sub), None)
    sequencer.handler(drain(aws["queue_url"]), None)
    recs = records(stream)
    assert sorted(r[1]["data"]["sub"] for r in recs) == ["a", "b"]
    assert {pk for pk, _ in recs} == {ev}
    assert {r[1]["type"] for r in recs} == {"joined"}
    assert len({r[1]["id"] for r in recs}) == 2  # unique ids for de-duplication


def test_first_admission_publishes_admitted_once(aws, stream, monkeypatch):
    sm = boto3.client("secretsmanager", region_name="ap-south-1")
    sm.create_secret(Name="pass-key", SecretString=json.dumps({"kid": "p", "key": "p" * 64}))
    monkeypatch.setenv("PASS_KEY_SECRET", "pass-key")
    ev = open_queue(aws["table"], serving_up_to=5)
    aws["table"].put_item(
        Item={
            "PK": f"EVENT#{ev}",
            "SK": "USER#me",
            "request_id": "r",
            "joined_at": "2026-01-01T00:00:00+00:00",
            "position": 3,
        }
    )
    now = int(time.time())
    qt = tokens.sign(
        {"typ": "queue", "ev": ev, "sub": "me", "pos": 3, "iat": now, "exp": now + 60}, TEST_KEY
    )
    for _ in range(2):
        r = admit.handler(api_event(ev, sub="me", body=json.dumps({"queue_token": qt})), None)
        assert r["statusCode"] == 200
    assert [r[1]["type"] for r in records(stream)] == ["admitted"]


def test_stream_down_never_breaks_the_caller(aws, monkeypatch):
    monkeypatch.setenv("SALE_EVENTS_STREAM", "does-not-exist")
    sale_events._kinesis.cache_clear()
    ev = open_queue(aws["table"])
    join.handler(api_event(ev, sub="x"), None)
    out = sequencer.handler(drain(aws["queue_url"]), None)
    assert out == {"batchItemFailures": []}  # place claimed and numbered anyway
    assert sale_events.publish([sale_events.envelope("joined", ev, {})]) == 0
