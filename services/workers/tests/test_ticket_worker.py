"""Ticket worker on the real schema (booking API migrations): one email per order, ever."""

import json
import os
import threading
import uuid
from datetime import UTC, datetime, timedelta

import pytest

pytestmark = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="needs DATABASE_URL")

from sg_workers import ticket_worker  # noqa: E402
from sg_workers.db import connect  # noqa: E402

KEY = {"kid": "test", "key": "t" * 32}


@pytest.fixture
def aws(monkeypatch):
    """Fake S3 / SES / SQS / Kinesis; record what was sent."""
    sent = {"pdf": {}, "email": [], "queued": [], "published": []}
    monkeypatch.setenv("TICKET_KEY_JSON", json.dumps(KEY))
    monkeypatch.setenv(
        "TICKET_EMAIL_JSON",
        json.dumps({"sender": "t@example.com", "sandbox_recipient": "t@example.com"}),
    )
    monkeypatch.setenv("TICKETS_QUEUE_URL", "https://sqs.test/q")
    ticket_worker.ticket_key.cache_clear()
    ticket_worker.email_config.cache_clear()
    monkeypatch.setattr(ticket_worker, "put_pdf", lambda k, b: sent["pdf"].__setitem__(k, b))

    def send(raw, sender, to):
        sent["email"].append((to, raw))
        return f"ses-{len(sent['email'])}"

    monkeypatch.setattr(ticket_worker, "send_email", send)
    monkeypatch.setattr(ticket_worker, "publish", lambda ev, data: sent["published"].append(data))

    class Sqs:
        def send_message(self, **kw):
            sent["queued"].append(json.loads(kw["MessageBody"]))

    monkeypatch.setattr(ticket_worker, "_client", lambda name: Sqs())
    yield sent
    ticket_worker.ticket_key.cache_clear()
    ticket_worker.email_config.cache_clear()


def paid_order(seats=2, status="paid", paid_ago=timedelta(minutes=5)):
    """A paid order with sold seats, inserted directly (as the order worker leaves it)."""
    c = connect()
    t, ev, h, o = (str(uuid.uuid4()) for _ in range(4))
    now = datetime.now(UTC)
    c.run("INSERT INTO tenants (id, name) VALUES (CAST(:t AS uuid), 't')", t=t)
    c.run(
        "INSERT INTO events (id, tenant_id, name, venue, starts_at, sale_starts_at) VALUES "
        "(CAST(:e AS uuid), CAST(:t AS uuid), 'Fest', 'Mumbai', :s, :ss)",
        e=ev,
        t=t,
        s=now + timedelta(days=3),
        ss=now - timedelta(hours=1),
    )
    c.run(
        "INSERT INTO holds (id, event_id, buyer_id, seat_count, status, expires_at) VALUES "
        "(CAST(:h AS uuid), CAST(:e AS uuid), 'buyer', :n, 'converted', now())",
        h=h,
        e=ev,
        n=seats,
    )
    c.run(
        "INSERT INTO orders (id, event_id, hold_id, buyer_id, idempotency_key, status, "
        "amount_paise, "
        "paid_at) VALUES (CAST(:o AS uuid), CAST(:e AS uuid), CAST(:h AS uuid), 'buyer', "
        "CAST(:k AS uuid), CAST(:st AS order_status), 100, :p)",
        o=o,
        e=ev,
        h=h,
        k=str(uuid.uuid4()),
        st=status,
        p=now - paid_ago,
    )
    for n in range(1, seats + 1):
        s = str(uuid.uuid4())
        c.run(
            "INSERT INTO seats (id, event_id, section, row, number, label, zone, price_paise, "
            "status, hold_id) VALUES (CAST(:s AS uuid), CAST(:e AS uuid), 'A', '1', :n, :l, 'g', "
            "50, 'sold', "
            "CAST(:h AS uuid))",
            s=s,
            e=ev,
            n=n,
            l=f"A-1-{n}",
            h=h,
        )
        c.run(
            "INSERT INTO order_items (id, order_id, seat_id, price_paise, sold) VALUES "
            "(CAST(:i AS uuid), CAST(:o AS uuid), CAST(:s AS uuid), 50, true)",
            i=str(uuid.uuid4()),
            o=o,
            s=s,
        )
    c.close()
    return o


def order_row(o):
    c = connect()
    try:
        return c.run(
            "SELECT ticket_email_sent_at IS NOT NULL, ticket_email_message_id, "
            "(SELECT count(*) FROM tickets WHERE order_id = CAST(:o AS uuid)) "
            "FROM orders WHERE id = CAST(:o AS uuid)",
            o=o,
        )[0]
    finally:
        c.close()


def message(o, mid="m1"):
    return {
        "messageId": mid,
        "body": json.dumps(
            {"detail-type": "sale-event", "detail": {"type": "order_paid", "data": {"order_id": o}}}
        ),
    }


def test_paid_order_gets_tickets_a_pdf_and_one_email(aws):
    o = paid_order()
    assert ticket_worker.handler({"Records": [message(o)]}, None) == {"batchItemFailures": []}
    assert order_row(o) == [True, "ses-1", 2]
    (key,) = aws["pdf"]
    assert key.endswith(f"/{o}.pdf") and aws["pdf"][key].startswith(b"%PDF")
    (to, raw) = aws["email"][0]
    assert b"Content-Type: application/pdf" in raw and b'filename="tickets-' in raw
    assert len(aws["published"][0]["tickets"]) == 2


def test_replay_and_duplicates_never_send_a_second_email(aws):
    o = paid_order()
    ticket_worker.handler({"Records": [message(o, "a")]}, None)
    out = ticket_worker.handler({"Records": [message(o, "b"), message(o, "c")]}, None)
    assert out == {"batchItemFailures": []}  # acked: already sent
    assert len(aws["email"]) == 1 and order_row(o)[2] == 2  # still 2 tickets


def test_tickets_and_tokens_are_stable_across_reissue(aws):
    """Same ticket ids (uuid5 of the order item) every time -> the same QR codes."""
    o = paid_order()
    ticket_worker.handler({"Records": [message(o)]}, None)
    first = next(iter(aws["pdf"].values()))
    c = connect()
    c.run(
        "UPDATE orders SET ticket_email_sent_at = NULL, ticket_email_claimed_at = NULL "
        "WHERE id = CAST(:o AS uuid)",
        o=o,
    )
    c.close()
    ticket_worker.handler({"Records": [message(o)]}, None)
    assert next(iter(aws["pdf"].values())) == first


def test_claimed_but_not_sent_is_not_acked(aws):
    o = paid_order()
    c = connect()
    c.run("UPDATE orders SET ticket_email_claimed_at = now() WHERE id = CAST(:o AS uuid)", o=o)
    c.close()
    out = ticket_worker.handler({"Records": [message(o, "x")]}, None)
    assert out == {"batchItemFailures": [{"itemIdentifier": "x"}]}  # SQS will retry it
    assert aws["email"] == []


def test_expired_claim_is_taken_over_and_sent(aws):
    """A run that crashed after claiming: after 2 minutes the retry sends the email."""
    o = paid_order()
    c = connect()
    c.run(
        "UPDATE orders SET ticket_email_claimed_at = now() - interval '3 minutes' "
        "WHERE id = CAST(:o AS uuid)",
        o=o,
    )
    c.close()
    assert ticket_worker.handler({"Records": [message(o)]}, None) == {"batchItemFailures": []}
    assert len(aws["email"]) == 1


def test_two_workers_at_once_send_one_email(aws):
    o = paid_order()
    gate, results = threading.Barrier(2), []

    def run(mid):
        gate.wait()
        results.append(ticket_worker.handler({"Records": [message(o, mid)]}, None))

    threads = [threading.Thread(target=run, args=(m,)) for m in ("p", "q")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert len(aws["email"]) == 1
    failures = [f for r in results for f in r["batchItemFailures"]]
    assert len(failures) <= 1  # the loser is retried (or found it already sent)


def test_unpaid_order_is_skipped_and_acked(aws):
    o = paid_order(status="refunded")
    assert ticket_worker.handler({"Records": [message(o)]}, None) == {"batchItemFailures": []}
    assert aws["email"] == [] and order_row(o)[2] == 0


def test_unknown_order_and_bad_messages(aws):
    out = ticket_worker.handler(
        {
            "Records": [
                message(str(uuid.uuid4()), "unknown"),
                {"messageId": "other", "body": json.dumps({"detail": {"type": "seat_held"}})},
            ]
        },
        None,
    )
    assert out == {"batchItemFailures": [{"itemIdentifier": "unknown"}]}  # -> retries -> DLQ


def test_one_failure_does_not_retry_the_rest_of_the_batch(aws, monkeypatch):
    good, bad = paid_order(), paid_order()
    real = ticket_worker.put_pdf

    def flaky(key, body):
        if bad in key:
            raise RuntimeError("s3 down")
        real(key, body)

    monkeypatch.setattr(ticket_worker, "put_pdf", flaky)
    out = ticket_worker.handler({"Records": [message(good, "g"), message(bad, "b")]}, None)
    assert out == {"batchItemFailures": [{"itemIdentifier": "b"}]}
    assert len(aws["email"]) == 1


def test_sweep_queues_paid_orders_without_an_email(aws):
    stale = paid_order(paid_ago=timedelta(minutes=10))
    fresh = paid_order(paid_ago=timedelta(seconds=10))  # its order_paid event is probably in flight
    done = paid_order(paid_ago=timedelta(minutes=10))
    ticket_worker.handler({"Records": [message(done)]}, None)
    ticket_worker.handler({"sweep": True}, None)
    queued = {q["detail"]["data"]["order_id"] for q in aws["queued"]}
    assert stale in queued and fresh not in queued and done not in queued
    assert ticket_worker.order_id_of(aws["queued"][0]) in queued  # same shape as EventBridge
