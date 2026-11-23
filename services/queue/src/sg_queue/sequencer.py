"""Sequencer: SQS join messages -> one place per account -> positions (blueprint steps 2-3).

Per batch (up to 100 messages), per event:
  1. claim each account's place with a conditional write (a second join of the same account
     is dropped: one place per account);
  2. if the queue is OPEN, give the new places positions with ONE counter update for the
     whole batch (`ADD next_position :n`), in join order;
     if it is still in PRE-QUEUE (before the sale starts), the places keep no position and a
     random shuffle key; the starter numbers them in random order at sale start.

Race with the starter: after claiming, the queue state is read again (strongly consistent).
If the sale opened meanwhile, this sequencer numbers its own places; if not, the starter's
final sweep (after it opens the queue) will. Nobody is left without a number.

A failed message is reported back to SQS (ReportBatchItemFailures) and retried alone; after 5
failures it moves to the dead-letter queue.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict

from sg_queue import positions, sale_events
from sg_queue.common import META, pk, table

log = logging.getLogger()
log.setLevel(logging.INFO)

NUMBERED_STATUSES = {"open", "paused"}  # paused: positions still given, nobody admitted


def queue_status(event_id: str) -> str | None:
    item = table().get_item(Key={"PK": pk(event_id), "SK": META}, ConsistentRead=True).get("Item")
    return item.get("status") if item else None


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

    stats = {"claimed": 0, "duplicates": 0, "placed": 0, "pre_queue": 0}
    for event_id, joins in by_event.items():
        joins.sort(key=lambda j: j[1]["joined_at"])
        try:
            status = queue_status(event_id)
            if status is None:
                raise LookupError(f"no queue for event {event_id}")
            pre_queue = status not in NUMBERED_STATUSES
            claimed = []
            joined_events = []
            for _message_id, join in joins:
                if positions.claim(join, pre_queue=pre_queue):
                    claimed.append(join["sub"])
                    joined_events.append(
                        sale_events.envelope(
                            "joined",
                            event_id,
                            {
                                "sub": join["sub"],
                                "request_id": join["request_id"],
                                "joined_at": join["joined_at"],
                                "pre_queue": pre_queue,
                            },
                        )
                    )
                else:
                    stats["duplicates"] += 1
            stats["claimed"] += len(claimed)
            if pre_queue and queue_status(event_id) in NUMBERED_STATUSES:
                pre_queue = False  # the sale opened while we were claiming: number them now
            if pre_queue:
                stats["pre_queue"] += len(claimed)
            else:
                stats["placed"] += positions.assign(event_id, claimed)
            stats["published"] = stats.get("published", 0) + sale_events.publish(joined_events)
        except Exception:
            log.exception("could not sequence joins for event %s", event_id)
            failures.extend({"itemIdentifier": mid} for mid, _ in joins)

    log.info(json.dumps(stats | {"failed": len(failures), "events": len(by_event)}))
    return {"batchItemFailures": failures}
