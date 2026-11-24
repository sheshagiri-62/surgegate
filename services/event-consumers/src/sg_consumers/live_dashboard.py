"""live-dashboard consumer (Day 8 Task 3): sale events -> live counters -> WebSocket push.

Kinesis event source (in order per shard). For each record, ONE DynamoDB transaction:
    Put   DEDUP#<envelope id>  (attribute_not_exists, 24 h TTL)   <- a duplicate fails here
    Update SALE#<event> / STATS  ADD counters
so a retried batch or an archive replay never counts twice. After the batch, the new numbers
for every touched sale are pushed to the organisers subscribed to it (API Gateway WebSocket
PostToConnection; a gone connection is removed).

Table (STATS_TABLE, single table):
    SALE#<event> STATS            joined, admitted, held_seats, sold_seats, revenue_paise,
                                  orders_paid, released_seats, refunds, refunded_paise, tickets
    DEDUP#<envelope id> -         TTL `expires`
    SUBS#<event> <connection id>  who to push to (TTL)        \\ written by ws.py on $connect
    CONN#<connection id> -        which sale it watches (TTL) /
"""

from __future__ import annotations

import json
import logging
import os
import time
from decimal import Decimal

from sg_consumers.common import OK, client, failure, records

log = logging.getLogger()
log.setLevel(logging.INFO)

DEDUP_TTL_SECONDS = 24 * 3600  # Kinesis retention: a replay older than this can't happen


def deltas(envelope: dict) -> dict[str, int]:
    """What one sale event changes. Unknown types change nothing (but are still deduped)."""
    t, d = envelope.get("type"), envelope.get("data") or {}
    if t == "joined":
        return {"joined": 1}
    if t == "admitted":
        return {"admitted": 1}
    if t == "seat_held":
        return {"held_seats": len(d.get("seats", []))}
    if t == "hold_released":
        n = len(d.get("released_seats", []))
        return {"held_seats": -n, "released_seats": n}
    if t == "order_paid":
        n = len(d.get("seats", []))
        out = {"sold_seats": n, "orders_paid": 1, "revenue_paise": int(d.get("amount_paise", 0))}
        if not d.get("late"):
            out["held_seats"] = -n  # a late payment re-held seats the timer had already released
        return out
    if t == "payment_refunded":
        return {"refunds": 1, "refunded_paise": int(d.get("amount_paise", 0))}
    if t == "ticket_issued":
        return {"tickets": len(d.get("tickets", []))}
    return {}


def apply(envelope: dict, table: str, now: int | None = None) -> bool:
    """True if counted, False if it was a duplicate."""
    now = int(time.time()) if now is None else now
    ch = deltas(envelope)
    items = [
        {
            "Put": {
                "TableName": table,
                "Item": {
                    "PK": {"S": f"DEDUP#{envelope['id']}"},
                    "SK": {"S": "-"},
                    "expires": {"N": str(now + DEDUP_TTL_SECONDS)},
                },
                "ConditionExpression": "attribute_not_exists(PK)",
            }
        }
    ]
    if ch:
        names = {f"#{k}": k for k in ch}
        values = {f":{k}": {"N": str(v)} for k, v in ch.items()} | {
            ":at": {"S": envelope.get("at", "")}
        }
        items.append(
            {
                "Update": {
                    "TableName": table,
                    "Key": {"PK": {"S": f"SALE#{envelope['sale_event_id']}"}, "SK": {"S": "STATS"}},
                    "UpdateExpression": "ADD "
                    + ", ".join(f"#{k} :{k}" for k in ch)
                    + " SET updated_at = :at",
                    "ExpressionAttributeNames": names,
                    "ExpressionAttributeValues": values,
                }
            }
        )
    try:
        client("dynamodb").transact_write_items(TransactItems=items)
        return True
    except client("dynamodb").exceptions.TransactionCanceledException as exc:
        reasons = [r.get("Code") for r in exc.response.get("CancellationReasons", [])]
        if reasons and reasons[0] == "ConditionalCheckFailed":
            return False  # seen before: a retry or a replay
        raise


def snapshot(event_id: str) -> dict:
    """Current numbers for one sale (+ the waiting room's status and admission rate)."""
    ddb = client("dynamodb")
    item = ddb.get_item(
        TableName=os.environ["STATS_TABLE"],
        Key={"PK": {"S": f"SALE#{event_id}"}, "SK": {"S": "STATS"}},
    ).get("Item", {})
    n = {k: int(v["N"]) for k, v in item.items() if "N" in v}
    meta = {}
    if qt := os.getenv("QUEUE_TABLE"):
        meta = ddb.get_item(
            TableName=qt, Key={"PK": {"S": f"EVENT#{event_id}"}, "SK": {"S": "META"}}
        ).get("Item", {})
    return {
        "type": "stats",
        "event_id": event_id,
        "waiting": max(0, n.get("joined", 0) - n.get("admitted", 0)),
        "admitted": n.get("admitted", 0),
        "held_seats": max(0, n.get("held_seats", 0)),
        "sold_seats": n.get("sold_seats", 0),
        "orders_paid": n.get("orders_paid", 0),
        "revenue_paise": n.get("revenue_paise", 0),
        "refunds": n.get("refunds", 0),
        "tickets": n.get("tickets", 0),
        "queue_status": meta.get("status", {}).get("S"),
        "admission_rate": int(meta.get("admission_rate", {}).get("N", 0)),
        "updated_at": item.get("updated_at", {}).get("S"),
    }


def push(event_id: str) -> int:
    """Send the sale's numbers to every subscribed connection. Returns how many got it."""
    ddb, table = client("dynamodb"), os.environ["STATS_TABLE"]
    subs = ddb.query(
        TableName=table,
        KeyConditionExpression="PK = :pk",
        ExpressionAttributeValues={":pk": {"S": f"SUBS#{event_id}"}},
    ).get("Items", [])
    if not subs:
        return 0
    body = json.dumps(
        snapshot(event_id), default=lambda o: int(o) if isinstance(o, Decimal) else str(o)
    ).encode()
    api = client("apigatewaymanagementapi", endpoint_url=os.environ["WS_ENDPOINT"])
    sent = 0
    for s in subs:
        cid = s["SK"]["S"]
        try:
            api.post_to_connection(ConnectionId=cid, Data=body)
            sent += 1
        except api.exceptions.GoneException:
            ddb.delete_item(
                TableName=table, Key={"PK": {"S": f"SUBS#{event_id}"}, "SK": {"S": cid}}
            )
            ddb.delete_item(TableName=table, Key={"PK": {"S": f"CONN#{cid}"}, "SK": {"S": "-"}})
    return sent


def handler(event, context):
    table = os.environ["STATS_TABLE"]
    touched: list[str] = []
    counted = dupes = 0
    for seq, env in records(event):
        try:
            if apply(env, table):
                counted += 1
            else:
                dupes += 1
            if env.get("sale_event_id") and env["sale_event_id"] not in touched:
                touched.append(env["sale_event_id"])
        except Exception as exc:
            log.error(json.dumps({"seq": seq, "error": repr(exc)}))
            for ev in touched:  # what was counted so far is real: show it
                _safe_push(ev)
            return failure(seq)  # retry from here; earlier records are checkpointed
    pushed = sum(_safe_push(ev) for ev in touched)
    log.info(
        json.dumps(
            {"counted": counted, "duplicates": dupes, "sales": len(touched), "pushed": pushed}
        )
    )
    return OK


def _safe_push(event_id: str) -> int:
    try:
        return push(event_id)
    except Exception as exc:  # a push failure must never re-count the batch
        log.warning(json.dumps({"push_failed": event_id, "error": repr(exc)}))
        return 0
