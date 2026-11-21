"""Admission valve: every minute, let the next `admission_rate` people in (blueprint step 6).

For each active queue that is OPEN:

    serving_up_to = min(serving_up_to + admission_rate, next_position)

so "now serving" never runs ahead of the people actually in line. Pausing the queue (organiser)
stops it: paused, pre-queue and closed queues are left alone. The admission rate, not the crowd
size, therefore sets the load on the booking API and the database.

Each tick is conditional on the minute (`last_tick < this minute`) and on the old value, so a
retried or duplicate invocation can never admit twice.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from botocore.exceptions import ClientError

from sg_queue.common import META, pk, table
from sg_queue.starter import active_queues

log = logging.getLogger()
log.setLevel(logging.INFO)


def tick(meta: dict, minute: str) -> dict | None:
    """Advance one queue for `minute` (e.g. "2026-11-21T18:05"). Returns what changed."""
    if meta.get("status") != "open":
        return None
    old = int(meta.get("serving_up_to", 0))
    rate = int(meta.get("admission_rate", 0))
    in_line = int(meta.get("next_position", 0))
    new = min(old + rate, in_line)
    if meta.get("last_tick", "") >= minute:
        return None  # this minute was already done
    try:
        table().update_item(
            Key={"PK": meta["PK"], "SK": META},
            UpdateExpression="SET serving_up_to = :new, last_tick = :minute",
            ConditionExpression="#s = :open AND serving_up_to = :old AND "
            "(attribute_not_exists(last_tick) OR last_tick < :minute)",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":new": new,
                ":old": old,
                ":minute": minute,
                ":open": "open",
            },
        )
    except ClientError as err:
        if err.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return None  # paused meanwhile, or another tick won: nothing to do
        raise
    return {"event": meta["PK"].removeprefix("EVENT#"), "from": old, "to": new, "rate": rate}


def handler(event, context):
    minute = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M")
    moved = [m for meta in active_queues() if (m := tick(meta, minute))]
    log.info(json.dumps({"minute": minute, "advanced": moved}))
    return {"minute": minute, "advanced": moved}


def queue_state(event_id: str) -> dict | None:
    """Helper for tests and tools."""
    return table().get_item(Key={"PK": pk(event_id), "SK": META}).get("Item")
