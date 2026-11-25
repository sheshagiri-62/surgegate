"""POST /queue/{event}/admit — swap your queue token for a 15-minute booking pass (blueprint 7).

Checks, in order:
  1. the queue token is genuine, unexpired, and for THIS signed-in user and THIS event
     (a token copied from someone else is useless: it names its owner);
  2. the place is really yours in the table and its number has been reached
     (position <= serving_up_to);
  3. issue a booking pass {typ: "pass", ev, sub, exp}, signed with the PASS key (a different
     key from queue tokens). The 15 minutes count from the FIRST admission (admitted_at is set
     once), so asking again returns a pass with the same expiry: it cannot be extended.

The booking API verifies the pass on every /book/{event}/... request (and, once CloudFront is
verified, a CloudFront Function will check it at the edge first).
"""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime

from sg_queue import sale_events, tokens
from sg_queue.common import META, claims, edge_only, pk, response, table, user_sk, valid_event_id

PASS_SECONDS = 15 * 60


@edge_only
def handler(event, context):
    event_id = (event.get("pathParameters") or {}).get("event")
    if not valid_event_id(event_id):
        return response(404, {"detail": "event not found"})
    sub = claims(event)["sub"]
    try:
        queue_token = json.loads(event.get("body") or "{}")["queue_token"]
    except (ValueError, KeyError, TypeError):
        return response(422, {"detail": 'send {"queue_token": "..."}'})

    try:
        token = tokens.verify(
            queue_token, tokens.signing_key(), typ="queue", sub=sub, event_id=event_id
        )
    except tokens.TokenError as err:
        return response(403, {"detail": f"invalid queue token: {err}"})

    meta = table().get_item(Key={"PK": pk(event_id), "SK": META}, ConsistentRead=True).get("Item")
    entry = table().get_item(Key={"PK": pk(event_id), "SK": user_sk(sub)}).get("Item")
    if meta is None or entry is None or int(entry.get("position", -1)) != int(token["pos"]):
        return response(403, {"detail": "invalid queue token: no such place"})
    serving = int(meta.get("serving_up_to", 0))
    if token["pos"] > serving:
        return response(
            409,
            {"detail": "not your turn yet", "position": token["pos"], "serving_up_to": serving},
        )

    now = datetime.now(UTC).isoformat()
    updated = table().update_item(
        Key={"PK": pk(event_id), "SK": user_sk(sub)},
        UpdateExpression="SET admitted_at = if_not_exists(admitted_at, :now)",
        ExpressionAttributeValues={":now": now},
        ReturnValues="ALL_NEW",
    )["Attributes"]
    admitted = int(datetime.fromisoformat(updated["admitted_at"]).timestamp())
    expires = admitted + PASS_SECONDS
    if expires <= time.time():
        return response(410, {"detail": "your booking window has ended"})

    if updated["admitted_at"] == now:  # first admission only (asking again is not an event)
        sale_events.publish(
            [sale_events.envelope("admitted", event_id, {"sub": sub, "position": token["pos"]})]
        )
    booking_pass = tokens.sign(
        {"typ": "pass", "ev": event_id, "sub": sub, "iat": admitted, "exp": expires},
        tokens.signing_key(os.environ["PASS_KEY_SECRET"]),
    )
    return response(
        200,
        {
            "booking_pass": booking_pass,
            "expires_at": datetime.fromtimestamp(expires, UTC).isoformat(),
            "header": "X-Booking-Pass",
        },
    )
