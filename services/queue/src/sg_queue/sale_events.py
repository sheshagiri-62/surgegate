"""Publish sale events to Kinesis `sale-events` (ADR 002).

Envelope (one JSON record):
    {"id": <uuid, unique per event: consumers drop duplicates>, "type": "joined" | "admitted" | ...,
     "sale_event_id": <event id>, "at": <ISO time>, "data": {...}}

Partition key = sale event id, so all records of one sale stay in order on one shard.

Best-effort on purpose: a join, a position or an admission must never fail because the event
stream is down (in dev it only exists during work sessions). Failures are logged and counted.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import UTC, datetime
from functools import lru_cache

import boto3
from botocore.config import Config

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _kinesis():
    # Short timeouts, few retries: publishing must not slow the request down.
    return boto3.client(
        "kinesis",
        config=Config(connect_timeout=1, read_timeout=2, retries={"max_attempts": 2}),
    )


def envelope(kind: str, sale_event_id: str, data: dict) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "type": kind,
        "sale_event_id": sale_event_id,
        "at": datetime.now(UTC).isoformat(),
        "data": data,
    }


def publish(events: list[dict]) -> int:
    """Put events on the stream in one call (up to 500). Returns how many were accepted."""
    stream = os.getenv("SALE_EVENTS_STREAM")
    if not stream or not events:
        return 0
    try:
        out = _kinesis().put_records(
            StreamName=stream,
            Records=[
                {"Data": json.dumps(e).encode(), "PartitionKey": e["sale_event_id"]}
                for e in events[:500]
            ],
        )
    except Exception as exc:  # stream down, throttled, network: never fail the caller
        log.warning(
            json.dumps(
                {"sale_events": "publish_failed", "count": len(events), "error": type(exc).__name__}
            )
        )
        return 0
    failed = out.get("FailedRecordCount", 0)
    if failed:
        log.warning(json.dumps({"sale_events": "partially_failed", "failed": failed}))
    return len(events[:500]) - failed
