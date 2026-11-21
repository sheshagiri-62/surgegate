"""Starter: opens each queue at its sale start and shuffles the pre-queue (blueprint step 3).

Runs every minute (EventBridge Scheduler). For each active queue still in PRE-QUEUE whose
sale_starts_at has passed:

  1. pre-queue -> shuffling   (conditional update: exactly one starter does it)
  2. number every waiting place: people who joined BEFORE the start in random order, then
     later arrivals in join order
  3. shuffling -> open
  4. sweep: number anyone a sequencer claimed during steps 1-3 (in join order)

Active queues are found through a sparse index (only META items carry `active`), so the
starter never scans queue entries.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from sg_queue import positions
from sg_queue.common import META, parse_iso, pk, table

log = logging.getLogger()
log.setLevel(logging.INFO)

ACTIVE_INDEX = os.getenv("ACTIVE_INDEX", "active-queues")


def active_queues() -> list[dict]:
    items, kwargs = [], {"IndexName": ACTIVE_INDEX, "KeyConditionExpression": Key("active").eq("1")}
    while True:
        page = table().query(**kwargs)
        items.extend(page["Items"])
        if "LastEvaluatedKey" not in page:
            return items
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def _set_status(event_id: str, old: str, new: str) -> bool:
    try:
        table().update_item(
            Key={"PK": pk(event_id), "SK": META},
            UpdateExpression="SET #s = :new",
            ConditionExpression="#s = :old",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":old": old, ":new": new},
        )
        return True
    except ClientError as err:
        if err.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


def start_sale(event_id: str, sale_starts_at: str) -> dict:
    """Open one queue. Safe to call again: only the call that wins step 1 shuffles."""
    if not _set_status(event_id, "pre-queue", "shuffling"):
        return {"event": event_id, "started": False}
    waiting = positions.unpositioned(event_id)
    shuffled = positions.assign(event_id, positions.shuffle_order(waiting, sale_starts_at))
    _set_status(event_id, "shuffling", "open")
    late = positions.unpositioned(event_id)  # claimed while we were shuffling
    swept = positions.assign(event_id, positions.shuffle_order(late, sale_starts_at))
    result = {"event": event_id, "started": True, "shuffled": shuffled, "swept": swept}
    log.info(json.dumps(result))
    return result


def handler(event, context):
    now = datetime.now(UTC)
    results = []
    for meta in active_queues():
        event_id = meta["PK"].removeprefix("EVENT#")
        if meta.get("status") == "pre-queue" and parse_iso(meta["sale_starts_at"]) <= now:
            results.append(start_sale(event_id, meta["sale_starts_at"]))
        elif meta.get("status") == "shuffling":
            # A starter died mid-shuffle: finish the job (numbers only go to unnumbered places).
            late = positions.unpositioned(event_id)
            positions.assign(event_id, positions.shuffle_order(late, meta["sale_starts_at"]))
            _set_status(event_id, "shuffling", "open")
    return {"started": results}
