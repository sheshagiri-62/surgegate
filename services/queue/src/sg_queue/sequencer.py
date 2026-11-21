"""Sequencer: SQS join messages -> queue positions in DynamoDB (blueprint step 2).

For each batch (up to 100 messages): per event, ONE atomic counter update reserves a block of
positions (`ADD next_position :n`), instead of one counter write per person; that avoids a hot
counter item. Then each entry is written with its position. Joins within a batch are ordered
by joined_at, so later arrivals stand behind earlier ones.

A failed message is reported back to SQS (ReportBatchItemFailures) and retried on its own;
after 5 failures it moves to the dead-letter queue.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict

from sg_queue.common import META, pk, table, user_sk

log = logging.getLogger()
log.setLevel(logging.INFO)


def reserve_positions(event_id: str, count: int) -> int:
    """Atomically reserve `count` positions; returns the first one."""
    out = table().update_item(
        Key={"PK": pk(event_id), "SK": META},
        UpdateExpression="ADD next_position :n",
        ConditionExpression="attribute_exists(PK)",
        ExpressionAttributeValues={":n": count},
        ReturnValues="UPDATED_NEW",
    )
    last = int(out["Attributes"]["next_position"])
    return last - count + 1


def write_entry(join: dict, position: int) -> None:
    table().put_item(
        Item={
            "PK": pk(join["event_id"]),
            "SK": user_sk(join["sub"]),
            "request_id": join["request_id"],
            "joined_at": join["joined_at"],
            "position": position,
        }
    )


def handler(event, context):
    by_event: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    failures: list[dict] = []
    for record in event.get("Records", []):
        try:
            join = json.loads(record["body"])
            by_event[join["event_id"]].append((record["messageId"], join))
        except (KeyError, ValueError):
            log.error("bad join message %s", record.get("messageId"))
            failures.append({"itemIdentifier": record["messageId"]})

    placed = 0
    for event_id, joins in by_event.items():
        joins.sort(key=lambda j: j[1]["joined_at"])
        try:
            first = reserve_positions(event_id, len(joins))
        except Exception:
            log.exception("could not reserve positions for event %s", event_id)
            failures.extend({"itemIdentifier": mid} for mid, _ in joins)
            continue
        for offset, (message_id, join) in enumerate(joins):
            try:
                write_entry(join, first + offset)
                placed += 1
            except Exception:
                log.exception("could not write entry %s", message_id)
                failures.append({"itemIdentifier": message_id})

    log.info(json.dumps({"placed": placed, "failed": len(failures), "events": len(by_event)}))
    return {"batchItemFailures": failures}
