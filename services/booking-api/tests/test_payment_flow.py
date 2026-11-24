"""Webhook -> SQS -> order worker (Day 7 Task 4): exactly once, late payments, the race.

Real pieces: the app's /webhooks/razorpay endpoint, a moto SQS queue, the worker's
handle_message (what the long-running loop calls), PostgreSQL, and for the race the hold
timer's REAL release code (services/workers, pg8000).
"""

import json
import sys
import threading
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from tests.conftest import ROOT
from tests.helpers import buyer
from tests.test_holds import hold, open_event
from tests.test_orders import FakeProvider, order

from app import order_worker, payment_queue, sale_events
from app.payments import get_provider, webhook_signature

pytestmark = pytest.mark.integration

SECRET = {"key_id": "rzp_test_t", "key_secret": "ks", "webhook_secret": "wh-secret"}


class TestProvider(FakeProvider):
    """Fake orders and refunds; REAL webhook signature check."""

    def __init__(self):
        super().__init__()
        self.refunds = {}

    def verify_webhook_signature(self, raw_body, signature):
        import hmac

        return hmac.compare_digest(webhook_signature(raw_body, SECRET["webhook_secret"]), signature)

    def refund(self, payment_id, amount_paise):
        return self.refunds.setdefault(payment_id, f"rfnd_{uuid.uuid4().hex[:14]}")


@pytest.fixture
def flow(api, monkeypatch, migrated_engine):
    import boto3

    from app.main import app

    monkeypatch.setenv("PAYMENT_SECRET_JSON", json.dumps(SECRET))
    monkeypatch.setenv("ORDER_RETURN_ORIGINS", "http://localhost:3000")
    provider = TestProvider()
    app.dependency_overrides[get_provider] = lambda: provider
    payment_queue.sqs.cache_clear()
    url = boto3.client("sqs", region_name="ap-south-1").create_queue(QueueName="payments-test")[
        "QueueUrl"
    ]
    monkeypatch.setenv("PAYMENTS_QUEUE_URL", url)
    published = []
    monkeypatch.setattr(sale_events, "publish", lambda *a: published.append(a) or True)

    class Flow:
        pass

    f = Flow()
    f.api, f.provider, f.published = api, provider, published
    f.factory = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    f.engine = migrated_engine
    yield f
    payment_queue.sqs.cache_clear()


def held_order(f, n=2, per_buyer_limit=4):
    event_id, seats = open_event(f.api, per_buyer_limit=per_buyer_limit)
    headers = buyer()
    h = hold(f.api, event_id, seats[:n], headers).json()
    o = order(f.api, event_id, headers, h["hold_id"]).json()
    return event_id, seats, headers, h, o


def webhook_body(o, kind="payment.captured", pay_id=None, amount=None):
    captured = kind == "payment.captured"
    event = {
        "entity": "event",
        "account_id": "acc_test",
        "event": kind,
        "contains": ["payment"],
        "payload": {
            "payment": {
                "entity": {
                    "id": pay_id or f"pay_{uuid.uuid4().hex[:14]}",
                    "entity": "payment",
                    "amount": o["amount_paise"] if amount is None else amount,
                    "currency": "INR",
                    "status": "captured" if captured else "failed",
                    "order_id": o["provider_order_id"],
                    "captured": captured,
                }
            }
        },
        "created_at": 1,
    }
    return json.dumps(event, separators=(",", ":")).encode()


def post(f, raw, signature=None, event_id="evt_test"):
    sig = webhook_signature(raw, SECRET["webhook_secret"]) if signature is None else signature
    headers = {"Content-Type": "application/json", "X-Razorpay-Event-Id": event_id}
    if sig:
        headers["X-Razorpay-Signature"] = sig
    return f.api.post("/webhooks/razorpay", content=raw, headers=headers)


def drain(f):
    """Run the worker on every queued message (delete only after success, like run())."""
    sqs, url, outcomes = payment_queue.sqs(), payment_queue.queue_url(), []
    while msgs := sqs.receive_message(QueueUrl=url, MaxNumberOfMessages=10).get("Messages"):
        for m in msgs:
            outcomes.append(order_worker.handle_message(f.factory, f.provider, m))
            sqs.delete_message(QueueUrl=url, ReceiptHandle=m["ReceiptHandle"])
    return outcomes


def queued(f) -> int:
    attrs = payment_queue.sqs().get_queue_attributes(
        QueueUrl=payment_queue.queue_url(), AttributeNames=["ApproximateNumberOfMessages"]
    )
    return int(attrs["Attributes"]["ApproximateNumberOfMessages"])


def state(f, o):
    with f.engine.connect() as c:
        order_status = c.execute(
            text("SELECT status::text FROM orders WHERE id = :o"), {"o": o["order_id"]}
        ).scalar_one()
        hold_status = c.execute(
            text("SELECT status::text FROM holds WHERE id = :h"), {"h": o["hold_id"]}
        ).scalar_one()
        seats = c.execute(
            text(
                "SELECT s.status::text, s.hold_id::text, i.sold FROM order_items i "
                "JOIN seats s ON s.id = i.seat_id WHERE i.order_id = :o"
            ),
            {"o": o["order_id"]},
        ).all()
        payments = c.execute(
            text("SELECT status::text FROM payments WHERE order_id = :o"), {"o": o["order_id"]}
        ).scalars()
        return order_status, hold_status, [tuple(s) for s in seats], sorted(payments)


def release(f, hold_id):
    """What the hold timer does (same rule as services/workers release_hold)."""
    with f.engine.begin() as c:
        c.execute(text("SELECT id FROM holds WHERE id = :h FOR UPDATE"), {"h": hold_id})
        c.execute(
            text(
                "UPDATE seats SET status='available', hold_id=NULL, held_until=NULL "
                "WHERE hold_id = :h AND status = 'held'"
            ),
            {"h": hold_id},
        )
        c.execute(
            text("UPDATE holds SET status='released' WHERE id = :h AND status='active'"),
            {"h": hold_id},
        )


# --- the endpoint -------------------------------------------------------------------------------
def test_bad_signature_is_400_and_nothing_is_queued(flow):
    _, _, _, _, o = held_order(flow)
    raw = webhook_body(o)
    assert post(flow, raw, signature="0" * 64).status_code == 400
    assert post(flow, raw, signature="").status_code == 400  # missing header
    reserialised = json.dumps(json.loads(raw)).encode()  # same JSON, different bytes
    assert (
        post(flow, reserialised, signature=webhook_signature(raw, "wh-secret")).status_code == 400
    )
    assert queued(flow) == 0
    assert state(flow, o)[3] == []  # no payment row


def test_other_events_are_acknowledged_but_not_queued(flow):
    raw = json.dumps({"event": "order.paid", "payload": {}}).encode()
    r = post(flow, raw)
    assert r.status_code == 200 and r.json()["status"] == "ignored"
    assert queued(flow) == 0


def test_queue_down_is_503_so_the_provider_retries(flow, monkeypatch):
    _, _, _, _, o = held_order(flow)

    def down(*a):
        raise RuntimeError("sqs down")

    monkeypatch.setattr(payment_queue, "send", down)
    assert post(flow, webhook_body(o)).status_code == 503


def test_oversized_body_is_413(flow):
    assert post(flow, b"{" + b" " * (65 * 1024) + b"}").status_code == 413


# --- exactly once ---------------------------------------------------------------------------------
def test_duplicate_webhook_is_one_payment_one_confirm(flow):
    _, _, _, _, o = held_order(flow)
    raw = webhook_body(o)
    assert post(flow, raw).json() == {"status": "queued"}
    assert post(flow, raw).json() == {"status": "queued"}  # the provider sends it again
    assert [x.result for x in drain(flow)] == ["paid", "duplicate"]
    order_status, hold_status, seats, payments = state(flow, o)
    assert (order_status, hold_status, payments) == ("paid", "converted", ["captured"])
    assert all(s == ("sold", o["hold_id"], True) for s in seats) and len(seats) == 2
    assert [p[0] for p in flow.published].count("order_paid") == 1


def test_payment_failed_fails_the_order_and_keeps_the_hold(flow):
    event_id, _, headers, h, o = held_order(flow)
    post(flow, webhook_body(o, "payment.failed"))
    assert [x.result for x in drain(flow)] == ["failed"]
    order_status, hold_status, seats, payments = state(flow, o)
    assert (order_status, hold_status, payments) == ("failed", "active", ["failed"])
    assert all(s[0] == "held" for s in seats)
    # The buyer retries before the hold expires: a new order for the same hold.
    retry = order(flow.api, event_id, headers, h["hold_id"])
    assert retry.status_code == 201 and retry.json()["order_id"] != o["order_id"]


def test_capture_for_a_failed_order_with_a_newer_order_is_refunded(flow):
    event_id, _, headers, h, o = held_order(flow)
    post(flow, webhook_body(o, "payment.failed"))
    drain(flow)
    order(flow.api, event_id, headers, h["hold_id"])  # newer live order
    pay = f"pay_{uuid.uuid4().hex[:14]}"
    post(flow, webhook_body(o, pay_id=pay))
    (out,) = drain(flow)
    assert out.result == "refunded" and pay in flow.provider.refunds


def test_amount_mismatch_is_refunded_not_confirmed(flow):
    _, _, _, _, o = held_order(flow)
    post(flow, webhook_body(o, amount=100))
    (out,) = drain(flow)
    assert (out.result, out.reason) == ("refunded", "amount mismatch")
    assert state(flow, o)[1] == "active"  # hold untouched


def test_unknown_order_is_not_acknowledged(flow):
    fake = {"provider_order_id": "order_doesnotexist", "amount_paise": 100}
    post(flow, webhook_body(fake))
    with pytest.raises(order_worker.UnknownOrder):
        drain(flow)
    assert queued(flow) == 0  # in flight (invisible), NOT deleted: it returns, then DLQ


# --- late payments ---------------------------------------------------------------------
def test_late_payment_with_seats_free_is_reheld_and_paid(flow):
    _, _, _, h, o = held_order(flow)
    release(flow, h["hold_id"])
    post(flow, webhook_body(o))
    (out,) = drain(flow)
    assert out.result == "paid_late"
    order_status, hold_status, seats, _ = state(flow, o)
    assert (order_status, hold_status) == ("paid", "converted")
    assert all(s == ("sold", o["hold_id"], True) for s in seats)
    assert flow.published[-1][2]["late"] is True


def test_late_payment_after_a_seat_was_resold_is_refunded(flow):
    event_id, seats, _, h, o = held_order(flow)
    release(flow, h["hold_id"])
    other = hold(flow.api, event_id, seats[1:2], buyer())  # someone else takes one seat
    assert other.status_code == 201
    pay = f"pay_{uuid.uuid4().hex[:14]}"
    post(flow, webhook_body(o, pay_id=pay))
    (out,) = drain(flow)
    assert (out.result, out.reason) == ("refunded", "seats no longer free")
    order_status, hold_status, seats_now, payments = state(flow, o)
    assert (order_status, hold_status, payments) == ("refunded", "released", ["refunded"])
    assert not any(s[2] for s in seats_now)  # nothing sold to this order
    assert [s[0] for s in seats_now].count("held") == 1  # the other buyer keeps their hold
    assert list(flow.provider.refunds) == [pay]
    assert flow.published[-1][0] == "payment_refunded"


def test_late_payment_over_the_per_buyer_limit_is_refunded(flow):
    event_id, seats, headers, h, o = held_order(flow, n=2, per_buyer_limit=4)
    release(flow, h["hold_id"])
    assert hold(flow.api, event_id, seats[2:5], headers).status_code == 201  # 3 more
    post(flow, webhook_body(o))
    (out,) = drain(flow)
    assert (out.result, out.reason) == ("refunded", "per-buyer limit")


def test_refund_is_idempotent_on_retry(flow):
    """Crash after refunding but before COMMIT: the retry gets the same refund back."""
    _, seats, _, h, o = held_order(flow)
    release(flow, h["hold_id"])
    hold(flow.api, o["event_id"], seats[:1], buyer())
    pay = f"pay_{uuid.uuid4().hex[:14]}"
    first = flow.provider.refund(pay, o["amount_paise"])  # as if the first attempt got here
    post(flow, webhook_body(o, pay_id=pay))
    drain(flow)
    assert flow.provider.refunds == {pay: first}


# --- the race: confirm vs the hold timer's release ----------------------------------------
def test_confirm_vs_release_race_exactly_one_outcome(flow):
    """The REAL release code and the worker, started together, 30 times. Whatever wins, the end
    state is consistent: the order is paid and every seat is sold to this hold (seats are free
    after a release, so a late payment re-holds them). Never a paid order with a free seat."""
    sys.path.insert(0, str(ROOT.parent / "workers" / "src"))
    import random
    import time

    from sg_workers import release_hold

    results = []
    for i in range(30):
        _, _, _, h, o = held_order(flow)
        post(flow, webhook_body(o))
        sqs, url = payment_queue.sqs(), payment_queue.queue_url()
        (m,) = sqs.receive_message(QueueUrl=url, MaxNumberOfMessages=1)["Messages"]
        sqs.delete_message(QueueUrl=url, ReceiptHandle=m["ReceiptHandle"])
        gate, out = threading.Barrier(2), {}
        # Jitter on alternating sides so both orders happen (the release opens a new pg8000
        # connection, so it needs a head start to win sometimes).
        lag = {"worker": random.uniform(0.05, 0.25) if i % 2 else 0.0}  # noqa: S311 - test timing jitter
        lag["release"] = 0.0 if i % 2 else random.uniform(0, 0.03)  # noqa: S311 - test timing jitter

        def confirm(m=m, gate=gate, out=out, lag=lag):
            gate.wait()
            time.sleep(lag["worker"])
            out["worker"] = order_worker.handle_message(flow.factory, flow.provider, m).result

        def timer(h=h, gate=gate, out=out, lag=lag):
            gate.wait()
            time.sleep(lag["release"])
            out["release"] = release_hold.release(h["hold_id"])["released_seats"]

        threads = [threading.Thread(target=confirm), threading.Thread(target=timer)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        order_status, hold_status, seats, payments = state(flow, o)
        assert (order_status, hold_status, payments) == ("paid", "converted", ["captured"])
        assert all(s == ("sold", o["hold_id"], True) for s in seats)
        # exactly one path did the work: either the worker confirmed first (release found
        # nothing) or the release ran first and the worker re-held the free seats
        assert (out["worker"], bool(out["release"])) in {("paid", False), ("paid_late", True)}
        results.append(out["worker"])
    print("race outcomes:", {r: results.count(r) for r in set(results)})
    assert set(results) == {"paid", "paid_late"}, "both orders should have happened"
