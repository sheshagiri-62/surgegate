"""Ticket worker (Day 8 Task 1): order_paid -> PDF with one signed QR per seat -> S3 -> email.

Triggers (one Lambda):
  * SQS `tickets` queue, fed by an EventBridge rule on detail.type = "order_paid" (the sale-
    events bus). Batch with ReportBatchItemFailures.
  * {"sweep": true} every 5 minutes (EventBridge Scheduler): paid orders older than 2 minutes
    that NO run has ever claimed are queued. A safety net for a lost order_paid (published
    best-effort). Claimed-but-unsent orders are NOT re-queued: their job is still retrying on
    SQS (and ends in the DLQ + alarm if it keeps failing); re-queuing them would pile up copies.

Idempotent per order, so a replay or duplicate never sends a second email:
  1. lock the order; not paid -> skip (ack); email already sent -> ack
  2. email CLAIMED by another run less than CLAIM_SECONDS ago -> NOT acked (batch item failure):
     SQS retries it later, by when it is sent (then acked) or the claim has expired
  3. tickets: one row per order item, INSERT ... ON CONFLICT (order_item_id) DO NOTHING, ticket
     id = uuid5(order item) -> the same ticket and the same QR token every time
  4. claim the email (ticket_email_claimed_at = now()), COMMIT
  5. PDF -> s3://<tickets bucket>/tickets/<event>/<order>.pdf (same key = overwrite, KMS)
  6. send with SES, then store ticket_email_sent_at + the SES message id; publish ticket_issued

Limit (SES has no idempotency key): a crash AFTER SES accepted the email but BEFORE step 6
commits can send a second copy once the claim expires (2 minutes). Replays and duplicates
(the common case) never resend.

Sandbox: SES only delivers to verified addresses, so the config parameter may set
`sandbox_recipient`; otherwise the email stored on the order
(Cognito only for older orders without one).
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from datetime import UTC, datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from functools import lru_cache

import segno

from sg_workers import pdf, ticket_token
from sg_workers.db import connect

log = logging.getLogger()
log.setLevel(logging.INFO)

CLAIM_SECONDS = int(os.getenv("TICKET_CLAIM_SECONDS", "120"))  # 2 x the Lambda timeout
SWEEP_AFTER_SECONDS = 120
SWEEP_LIMIT = 50
TICKET_NS = uuid.UUID("6f1b6d3e-6a7e-4f5e-9a51-5e1d7c2b0a11")  # uuid5 namespace for ticket ids


class ClaimedElsewhere(Exception):
    """Another run is sending this order's email right now: retry later, don't ack."""


# --- AWS clients and settings (patched in tests) ------------------------------------------------
def _client(name: str):
    import boto3

    return boto3.client(name, region_name=os.getenv("AWS_REGION", "ap-south-1"))


@lru_cache(maxsize=1)
def ticket_key() -> dict:
    if raw := os.getenv("TICKET_KEY_JSON"):
        return json.loads(raw)
    value = _client("secretsmanager").get_secret_value(SecretId=os.environ["TICKET_KEY_SECRET_ID"])
    return json.loads(value["SecretString"])


@lru_cache(maxsize=1)
def email_config() -> dict:
    """{"sender": ..., "sandbox_recipient": ...} from SSM (the address is never in Git)."""
    if raw := os.getenv("TICKET_EMAIL_JSON"):
        return json.loads(raw)
    p = _client("ssm").get_parameter(Name=os.environ["TICKET_EMAIL_PARAM"])
    return json.loads(p["Parameter"]["Value"])


def put_pdf(key: str, body: bytes) -> None:
    _client("s3").put_object(
        Bucket=os.environ["TICKETS_BUCKET"],
        Key=key,
        Body=body,
        ContentType="application/pdf",
        ServerSideEncryption="aws:kms",  # bucket default key (data KMS key)
    )


_last_send = 0.0


def pace_sends(now=time.monotonic, sleep=time.sleep) -> None:
    """Keep at least SES_MIN_SEND_INTERVAL_SECONDS between this instance's sends (0 = off).

    The SES sandbox allows 1 email per second for the whole account, and the mailbox simulator
    (demo load tests) counts toward that RATE too. demo: 2 instances x one send per 2 s = 1/s,
    so a burst of 2,000 paid orders drains in ~35 minutes instead of throttling into the DLQ.
    """
    global _last_send
    interval = float(os.getenv("SES_MIN_SEND_INTERVAL_SECONDS", "0") or 0)
    if interval > 0:
        wait = _last_send + interval - now()
        if wait > 0:
            sleep(wait)
    _last_send = now()


@lru_cache(maxsize=1)
def _ses():
    import boto3
    from botocore.config import Config

    # TooManyRequestsException (rate exceeded) is a throttling error: retried with backoff.
    return boto3.client(
        "sesv2",
        region_name=os.getenv("AWS_REGION", "ap-south-1"),
        config=Config(retries={"mode": "standard", "max_attempts": 8}),
    )


def send_email(raw: bytes, sender: str, to: str) -> str:
    pace_sends()
    r = _ses().send_email(
        FromEmailAddress=sender,
        Destination={"ToAddresses": [to]},
        Content={"Raw": {"Data": raw}},
        ConfigurationSetName=os.getenv("SES_CONFIGURATION_SET", ""),
    )
    return r["MessageId"]


def buyer_email(sub: str) -> str | None:
    users = _client("cognito-idp").list_users(
        UserPoolId=os.environ["COGNITO_USER_POOL_ID"], Filter=f'sub = "{sub}"', Limit=1
    )["Users"]
    attrs = {a["Name"]: a["Value"] for u in users for a in u["Attributes"]}
    return attrs.get("email")


def publish(event_id: str, data: dict) -> None:
    stream = os.getenv("SALE_EVENTS_STREAM")
    if not stream:
        return
    record = {
        "id": str(uuid.uuid4()),
        "type": "ticket_issued",
        "sale_event_id": event_id,
        "at": datetime.now(UTC).isoformat(),
        "data": data,
    }
    try:
        _client("kinesis").put_record(
            StreamName=stream, Data=json.dumps(record).encode(), PartitionKey=event_id
        )
    except Exception as exc:  # best-effort, like every producer
        log.warning("ticket_issued not published: %s", type(exc).__name__)


# --- building the ticket ----------------------------------------------------------------------
def qr_matrix(token: str) -> list[list[int]]:
    return [list(row) for row in segno.make(token, error="m").matrix_iter(scale=1, border=4)]


def render(order: dict, tickets: list[dict], key: dict) -> tuple[bytes, list[str]]:
    pages, tokens = [], []
    for t in tickets:
        token = ticket_token.sign(
            {
                "typ": "ticket",
                "tid": t["ticket_id"],
                "ord": order["id"],
                "ev": order["event_id"],
                "seat": {"id": t["seat_id"], "label": t["label"]},
                "iat": int(order["paid_at"].timestamp()),
            },
            key,
        )
        tokens.append(token)
        pages.append(
            {
                "title": order["event_name"],
                "lines": [
                    f"Seat {t['label']}  "
                    f"(section {t['section']}, row {t['row']}, seat {t['number']})",
                    f"{order['venue']}  -  {order['starts_at']:%d %b %Y, %H:%M} UTC",
                    f"Order {order['id']}",
                    f"Ticket {t['ticket_id']}",
                ],
                "matrix": qr_matrix(token),
            }
        )
    return pdf.ticket_pdf(pages), tokens


def mime(
    order: dict, tickets: list[dict], pdf_bytes: bytes, sender: str, to: str, note: str
) -> bytes:
    msg = MIMEMultipart()
    msg["Subject"] = f"Your tickets: {order['event_name']}"
    msg["From"], msg["To"] = sender, to
    seats = ", ".join(t["label"] for t in tickets)
    body = (
        f"Thank you! Your seats for {order['event_name']}: {seats}.\n"
        f"{order['venue']}, {order['starts_at']:%d %b %Y, %H:%M} UTC.\n\n"
        "Your tickets are attached (one page and one QR code per seat). "
        "Each code works once at the gate.\n"
        f"Order {order['id']}\n{note}"
    )
    msg.attach(MIMEText(body, "plain", "utf-8"))
    part = MIMEApplication(pdf_bytes, _subtype="pdf")
    part.add_header("Content-Disposition", "attachment", filename=f"tickets-{order['id'][:8]}.pdf")
    msg.attach(part)
    return msg.as_bytes()


# --- one order ----------------------------------------------------------------------------------
def _claim(conn, order_id: str) -> dict | None:
    """Lock the order and decide. Returns the order to send, None to ack, or raises."""
    rows = conn.run(
        "SELECT o.id::text, o.event_id::text, o.status::text, o.paid_at, "
        "o.buyer_id, o.buyer_email, "
        "o.ticket_email_sent_at, o.ticket_email_claimed_at, "
        "now() - o.ticket_email_claimed_at < make_interval(secs => :claim), "
        "e.name, e.venue, e.starts_at "
        "FROM orders o JOIN events e ON e.id = o.event_id "
        "WHERE o.id = CAST(:o AS uuid) FOR UPDATE OF o",
        o=order_id,
        claim=CLAIM_SECONDS,
    )
    if not rows:
        raise LookupError(f"order {order_id} not found")
    (
        oid,
        ev,
        status,
        paid_at,
        buyer,
        email,
        sent_at,
        claimed_at,
        fresh_claim,
        name,
        venue,
        starts,
    ) = rows[0]
    if status != "paid":
        return {"skip": f"order is {status}"}
    if sent_at is not None:
        return {"skip": "email already sent"}
    if claimed_at is not None and fresh_claim:
        raise ClaimedElsewhere(order_id)
    conn.run(
        "INSERT INTO tickets (id, order_item_id, order_id, event_id, seat_id, kid, issued_at) "
        "SELECT CAST(CAST(:ids AS jsonb) ->> i.id::text AS uuid), i.id, i.order_id, "
        "CAST(:ev AS uuid), i.seat_id, :kid, now() "
        "FROM order_items i WHERE i.order_id = CAST(:o AS uuid) "
        "ON CONFLICT (order_item_id) DO NOTHING",
        ids=json.dumps(_ticket_ids(conn, order_id)),
        ev=ev,
        kid=ticket_key()["kid"],
        o=order_id,
    )
    conn.run(
        "UPDATE orders SET ticket_email_claimed_at = now() WHERE id = CAST(:o AS uuid)", o=order_id
    )
    return {
        "id": oid,
        "event_id": ev,
        "paid_at": paid_at,
        "buyer_id": buyer,
        "buyer_email": email,
        "event_name": name,
        "venue": venue,
        "starts_at": starts,
    }


def _ticket_ids(conn, order_id: str) -> dict[str, str]:
    items = conn.run(
        "SELECT id::text FROM order_items WHERE order_id = CAST(:o AS uuid)", o=order_id
    )
    return {i[0]: str(uuid.uuid5(TICKET_NS, i[0])) for i in items}


def issue(order_id: str) -> str:
    """Returns sent / skipped: <why>; raises ClaimedElsewhere (retry) or on errors (retry)."""
    conn = connect()
    try:
        conn.run("BEGIN")
        try:
            order = _claim(conn, order_id)
            conn.run("COMMIT")
        except Exception:
            conn.run("ROLLBACK")
            raise
        if "skip" in order:
            return f"skipped: {order['skip']}"

        rows = conn.run(
            "SELECT t.id::text, s.id::text, s.label, s.section, s.row, s.number "
            "FROM tickets t JOIN seats s ON s.id = t.seat_id "
            "WHERE t.order_id = CAST(:o AS uuid) ORDER BY s.label",
            o=order_id,
        )
        tickets = [
            dict(zip(("ticket_id", "seat_id", "label", "section", "row", "number"), r, strict=True))
            for r in rows
        ]
        pdf_bytes, _ = render(order, tickets, ticket_key())
        key = f"tickets/{order['event_id']}/{order_id}.pdf"
        put_pdf(key, pdf_bytes)
        conn.run(
            "UPDATE tickets SET s3_key = :k WHERE order_id = CAST(:o AS uuid)", k=key, o=order_id
        )

        cfg = email_config()
        # Stored on the order at creation; Cognito only for orders made before that (Task 4 fix).
        to = (
            cfg.get("sandbox_recipient")
            or order.get("buyer_email")
            or buyer_email(order["buyer_id"])
        )
        if not to:
            raise LookupError(f"no email address for buyer of order {order_id}")
        note = "(SES sandbox: sent to the test address.)" if cfg.get("sandbox_recipient") else ""
        message_id = send_email(
            mime(order, tickets, pdf_bytes, cfg["sender"], to, note), cfg["sender"], to
        )
        conn.run(
            "UPDATE orders SET ticket_email_sent_at = now(), ticket_email_message_id = :m "
            "WHERE id = CAST(:o AS uuid) AND ticket_email_sent_at IS NULL",
            m=message_id,
            o=order_id,
        )
    finally:
        conn.close()
    publish(
        order["event_id"],
        {"order_id": order_id, "tickets": [t["ticket_id"] for t in tickets], "s3_key": key},
    )
    log.info(
        json.dumps({"ticket": "sent", "order": order_id, "seats": len(tickets), "ses": message_id})
    )
    return "sent"


# --- safety net -------------------------------------------------------------------------------
def sweep() -> dict:
    conn = connect()
    try:
        rows = conn.run(
            "SELECT id::text, event_id::text FROM orders WHERE status = 'paid' "
            "AND ticket_email_sent_at IS NULL AND ticket_email_claimed_at IS NULL "
            "AND paid_at < now() - make_interval(secs => :age) "
            "ORDER BY paid_at LIMIT :n",
            age=SWEEP_AFTER_SECONDS,
            n=SWEEP_LIMIT,
        )
    finally:
        conn.close()
    sqs = _client("sqs") if rows else None
    for oid, ev in rows:
        sqs.send_message(
            QueueUrl=os.environ["TICKETS_QUEUE_URL"],
            MessageBody=json.dumps(
                {
                    "source": "sweep",
                    "detail": {
                        "type": "order_paid",
                        "sale_event_id": ev,
                        "data": {"order_id": oid},
                    },
                }
            ),
        )
    log.info(json.dumps({"sweep": len(rows)}))
    return {"queued": len(rows)}


# --- Lambda entry point -----------------------------------------------------------------------
def order_id_of(body: dict) -> str | None:
    """EventBridge -> SQS puts the whole event in the body; sweep messages use the same shape."""
    detail = body.get("detail") or {}
    if detail.get("type") != "order_paid":
        return None
    return (detail.get("data") or {}).get("order_id")


def handler(event, context):
    if event.get("sweep"):
        return sweep()
    failures = []
    for record in event.get("Records", []):
        try:
            order_id = order_id_of(json.loads(record["body"]))
            if order_id is None:
                log.info("not an order_paid message: acked")
                continue
            result = issue(order_id)
            log.info(
                json.dumps({"message": record["messageId"], "order": order_id, "result": result})
            )
        except ClaimedElsewhere as exc:
            log.info(
                json.dumps(
                    {
                        "message": record["messageId"],
                        "order": str(exc),
                        "result": "claimed elsewhere: retry",
                    }
                )
            )
            failures.append({"itemIdentifier": record["messageId"]})
        except Exception as exc:
            log.error(json.dumps({"message": record["messageId"], "error": repr(exc)}))
            failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}
