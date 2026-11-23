"""A committed hold publishes one seat_held event (partition key = sale); failures are harmless."""

import json

import boto3
import pytest
from tests.test_holds import hold, open_event

from app import sale_events

pytestmark = pytest.mark.integration


@pytest.fixture
def stream(queue_table, monkeypatch):  # queue_table: runs inside moto's mock_aws
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
    return [
        (r["PartitionKey"], json.loads(r["Data"]))
        for r in k.get_records(ShardIterator=it)["Records"]
    ]


def test_hold_publishes_seat_held(api, stream):
    event_id, seats = open_event(api)
    assert hold(api, event_id, seats[:2]).status_code == 201
    ((pk, e),) = records(stream)
    assert pk == event_id and e["type"] == "seat_held" and e["sale_event_id"] == event_id
    assert len(e["data"]["seats"]) == 2 and e["data"]["amount_paise"] == 200000


def test_failed_hold_publishes_nothing(api, stream):
    event_id, seats = open_event(api)
    hold(api, event_id, seats[:1])
    assert hold(api, event_id, seats[:1]).status_code == 409  # taken
    assert [e["type"] for _, e in records(stream)] == ["seat_held"]  # only the first


def test_stream_down_does_not_break_the_hold(api, monkeypatch):
    monkeypatch.setenv("SALE_EVENTS_STREAM", "no-such-stream")
    sale_events._kinesis.cache_clear()
    event_id, seats = open_event(api)
    assert hold(api, event_id, seats[:1]).status_code == 201
