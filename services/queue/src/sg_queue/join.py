"""POST /queue/{event}/join — join the waiting room (blueprint step 1).

Answers 202 at once: the join is only put on SQS here, so a burst of joins never waits on the
queue table. The sequencer Lambda gives out positions in batches.
"""

from __future__ import annotations

import json
import os
import uuid

from sg_queue.common import (
    BUYER,
    claims,
    edge_only,
    groups,
    now_iso,
    queue_meta,
    response,
    sqs,
    valid_event_id,
)

OPEN_STATUSES = {"pre-queue", "shuffling", "open", "paused"}  # paused: join yes, admit no


@edge_only
def handler(event, context):
    event_id = (event.get("pathParameters") or {}).get("event")
    if not valid_event_id(event_id):
        return response(404, {"detail": "event not found"})
    c = claims(event)
    if BUYER not in groups(c):
        return response(403, {"detail": "buyer role required"})

    meta = queue_meta(event_id)
    if meta is None:
        return response(404, {"detail": "no waiting room for this event"})
    if meta.get("status") not in OPEN_STATUSES:
        return response(409, {"detail": f"the queue is {meta.get('status')}"})

    request_id = str(uuid.uuid4())
    message = {
        "event_id": event_id,
        "sub": c["sub"],
        "request_id": request_id,
        "joined_at": now_iso(),
    }
    sqs().send_message(
        QueueUrl=os.environ["JOIN_QUEUE_URL"],
        MessageBody=json.dumps(message),
    )
    return response(202, {"request_id": request_id, "status": "joining"})
