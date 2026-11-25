"""GET /queue/{event}/position — your place in line, with a signed queue token (blueprint step 4).

The place is found by the signed-in account (Cognito sub), so refreshing the page or joining
again keeps the same place. Answers:

  joining    the join is accepted but not sequenced yet (seconds)      -> poll again
  pre-queue  you have a place; numbers are given at sale start         -> poll again
  queued     your position, "now serving", people ahead, estimated wait, and a queue token
             (signed, bound to you and this event) to swap for a booking pass when admitted
"""

from __future__ import annotations

import math
import time

from sg_queue import tokens
from sg_queue.common import META, claims, edge_only, pk, response, table, user_sk, valid_event_id

TOKEN_SECONDS = 6 * 3600


def estimated_wait_seconds(ahead: int, rate_per_minute: int) -> int | None:
    if ahead <= 0:
        return 0
    if rate_per_minute <= 0:
        return None  # paused: no estimate
    return math.ceil(ahead / rate_per_minute) * 60


@edge_only
def handler(event, context):
    event_id = (event.get("pathParameters") or {}).get("event")
    if not valid_event_id(event_id):
        return response(404, {"detail": "event not found"})
    sub = claims(event)["sub"]
    meta = table().get_item(Key={"PK": pk(event_id), "SK": META}).get("Item")
    if meta is None:
        return response(404, {"detail": "no waiting room for this event"})
    entry = table().get_item(Key={"PK": pk(event_id), "SK": user_sk(sub)}).get("Item")

    if entry is None:
        if (event.get("queryStringParameters") or {}).get("req"):
            return response(202, {"status": "joining"})  # accepted, not sequenced yet
        return response(404, {"detail": "you are not in this queue"})

    base = {"status_of_queue": meta["status"], "sale_starts_at": meta["sale_starts_at"]}
    if "position" not in entry:
        return response(200, base | {"status": "pre-queue"})

    position = int(entry["position"])
    serving = int(meta.get("serving_up_to", 0))
    rate = int(meta.get("admission_rate", 0)) if meta["status"] != "paused" else 0
    now = int(time.time())
    token = tokens.sign(
        {
            "typ": "queue",
            "ev": event_id,
            "sub": sub,
            "pos": position,
            "iat": now,
            "exp": now + TOKEN_SECONDS,
        },
        tokens.signing_key(),
    )
    return response(
        200,
        base
        | {
            "status": "admitted" if position <= serving else "queued",
            "position": position,
            "serving_up_to": serving,
            "ahead": max(position - serving - 1, 0),
            "estimated_wait_seconds": estimated_wait_seconds(position - serving, rate),
            "queue_token": token,
        },
    )
