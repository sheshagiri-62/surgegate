"""Publish sale events from the booking API to Kinesis `sale-events` (ADR 002).

Same envelope as the queue Lambdas: {id, type, sale_event_id, at, data}, partition key = sale
event id (ordered per sale). Called only AFTER the database commit, and best-effort: the stream
being down (dev: outside work sessions) never fails a hold. No-op when SALE_EVENTS_STREAM is unset.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import UTC, datetime
from functools import lru_cache

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _kinesis():
    import boto3
    from botocore.config import Config

    return boto3.client(
        "kinesis",
        region_name=os.getenv("AWS_REGION", "ap-south-1"),
        config=Config(connect_timeout=1, read_timeout=2, retries={"max_attempts": 2}),
    )


def publish(kind: str, sale_event_id: str, data: dict) -> bool:
    stream = os.getenv("SALE_EVENTS_STREAM")
    if not stream:
        return False
    event = {
        "id": str(uuid.uuid4()),
        "type": kind,
        "sale_event_id": sale_event_id,
        "at": datetime.now(UTC).isoformat(),
        "data": data,
    }
    try:
        _kinesis().put_record(
            StreamName=stream, Data=json.dumps(event).encode(), PartitionKey=sale_event_id
        )
        return True
    except Exception as exc:  # never fail the request because of the event stream
        log.warning("sale event %s not published: %s", kind, type(exc).__name__)
        return False
