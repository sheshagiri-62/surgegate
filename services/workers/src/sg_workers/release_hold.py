"""Hold timer, step 2 (Step Functions, after waiting 10 minutes): release the hold's seats.

Blueprint: "release the seats ONLY if they are still held by that same hold. A paid order
changes them to `sold` first, so the release does nothing."

One transaction:
  UPDATE seats SET status='available', hold_id=NULL, held_until=NULL
   WHERE hold_id = :hold AND status = 'held'          -- never touches sold or re-held seats
  UPDATE holds SET status='released' WHERE id = :hold AND status = 'active'

Idempotent: running it twice releases nothing the second time. A `hold_released` sale event is
published when seats were actually released (best-effort).

Input (from the state machine): {"hold_id": "...", "event_id": "..."}
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import UTC, datetime

from sg_workers.db import connect

log = logging.getLogger()
log.setLevel(logging.INFO)


def release(hold_id: str) -> dict:
    conn = connect()
    try:
        conn.run("BEGIN")
        seats = conn.run(
            "UPDATE seats SET status = 'available', hold_id = NULL, held_until = NULL "
            "WHERE hold_id = CAST(:hold AS uuid) AND status = 'held' RETURNING label",
            hold=hold_id,
        )
        hold = conn.run(
            "UPDATE holds SET status = 'released' "
            "WHERE id = CAST(:hold AS uuid) AND status = 'active' RETURNING event_id::text",
            hold=hold_id,
        )
        conn.run("COMMIT")
    except Exception:
        conn.run("ROLLBACK")
        raise
    finally:
        conn.close()
    return {
        "hold_id": hold_id,
        "released_seats": sorted(row[0] for row in seats),
        "hold_was_active": bool(hold),
    }


def publish(event_id: str, data: dict) -> None:
    stream = os.getenv("SALE_EVENTS_STREAM")
    if not stream:
        return
    try:
        import boto3

        record = {
            "id": str(uuid.uuid4()),
            "type": "hold_released",
            "sale_event_id": event_id,
            "at": datetime.now(UTC).isoformat(),
            "data": data,
        }
        boto3.client("kinesis").put_record(
            StreamName=stream, Data=json.dumps(record).encode(), PartitionKey=event_id
        )
    except Exception as exc:  # best-effort, like every producer
        log.warning("hold_released not published: %s", type(exc).__name__)


def handler(event, context):
    result = release(event["hold_id"])
    if result["released_seats"]:
        publish(event["event_id"], result)
    log.info(json.dumps({"release": result}))
    return result
