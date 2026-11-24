"""Shared helpers for the sale-events consumers (blueprint "Sale events").

Every record on the Kinesis stream is the envelope {id, type, sale_event_id, at, data}
(partition key = sale event id, so all records of one sale are in order on one shard).

Rules for every consumer (blueprint): process in order per shard; report the FIRST failed
record's sequence number (Lambda checkpoints before it and retries from there); ignore
duplicates by the envelope's message id (a retried batch or a replay delivers them again).
"""

from __future__ import annotations

import base64
import json
import os
from functools import cache


def records(event: dict) -> list[tuple[str, dict]]:
    """[(sequence number, envelope)] from a Kinesis event-source batch."""
    out = []
    for r in event.get("Records", []):
        k = r["kinesis"]
        out.append((k["sequenceNumber"], json.loads(base64.b64decode(k["data"]))))
    return out


def failure(sequence_number: str) -> dict:
    """ReportBatchItemFailures for a stream: Lambda retries from this record onwards."""
    return {"batchItemFailures": [{"itemIdentifier": sequence_number}]}


OK: dict = {"batchItemFailures": []}


@cache
def client(name: str, **kw):
    import boto3

    return boto3.client(name, region_name=os.getenv("AWS_REGION", "ap-south-1"), **kw)
