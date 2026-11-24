"""Order worker: confirm a payment exactly once (Day 7 Task 4; blueprint "Payments and
idempotency").

Reads the payments SQS queue (raw webhook bodies, already signature-checked by the endpoint)
and, for each message, runs ONE database transaction:

  lock the order (by provider order id)             -- unknown order: raise -> retry -> DLQ
  INSERT payment ON CONFLICT (provider_payment_id) DO NOTHING
      nothing inserted -> duplicate webhook -> no-op
  payment.failed   -> order pending -> failed; the hold is untouched (buyer may retry)
  payment.captured -> lock the hold (same lock order as the release Lambda: hold, then seats)
      hold active   : seats held by THIS hold -> sold; order_items.sold; hold converted; order paid
      hold released : late payment: all the order's seats free AND within the per-buyer limit
                      -> sold (re-held) and paid; otherwise refund
      anything else (amount mismatch, already paid, another live order) -> refund
COMMIT, then publish order_paid / payment_refunded (Kinesis sale-events -> Pipe -> EventBridge).

The payment insert is in the SAME transaction as the confirm: if the worker crashes half-way,
everything rolls back and the retry starts clean (a separate insert would make the retry look
like a duplicate and the order would never be confirmed).

The refund is called INSIDE the transaction (5 s timeout). It is idempotent per payment, so a
crash after refunding but before COMMIT is safe: the retry gets the same refund back. (At scale
an outbox would be better; see the Day 7 Task 4 report.)

The message is deleted only after the commit. Any exception leaves it on the queue: SQS
redelivers after the visibility timeout and moves it to the DLQ after 5 receives (alarm).

Run: python -m app.order_worker
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
import signal
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app import sale_events
from app.holds import SEATS_ALREADY_HELD_BY_BUYER
from app.models import (
    Event,
    Hold,
    HoldStatus,
    Order,
    OrderItem,
    OrderStatus,
    Payment,
    PaymentStatus,
)
from app.payments import PaymentProvider

log = logging.getLogger("order_worker")

HEARTBEAT = pathlib.Path(os.getenv("WORKER_HEARTBEAT", "/tmp/heartbeat"))  # noqa: S108 - emptyDir
LIVE = (OrderStatus.PENDING, OrderStatus.PAID)


class UnknownOrder(Exception):
    """No order for this provider order id: never acknowledged, so it ends up in the DLQ."""


@dataclass
class Outcome:
    result: str  # paid | paid_late | failed | refunded | duplicate | ignored
    order_id: str | None = None
    reason: str = ""
    events: list[tuple[str, str, dict]] = field(default_factory=list)  # published after commit


def _sell_held(db: Session, hold_id, seat_ids) -> int:
    return db.execute(
        text(
            "UPDATE seats SET status = 'sold', held_until = NULL "
            "WHERE id = ANY(:ids) AND hold_id = :hold AND status = 'held'"
        ),
        {"ids": seat_ids, "hold": hold_id},
    ).rowcount


def _sell_free(db: Session, hold_id, seat_ids) -> int:
    return db.execute(
        text(
            "UPDATE seats SET status = 'sold', hold_id = :hold, held_until = NULL "
            "WHERE id = ANY(:ids) AND status = 'available'"
        ),
        {"ids": seat_ids, "hold": hold_id},
    ).rowcount


def _paid(db: Session, order: Order, hold: Hold, late: bool) -> Outcome:
    db.execute(update(OrderItem).where(OrderItem.order_id == order.id).values(sold=True))
    hold.status = HoldStatus.CONVERTED
    order.status = OrderStatus.PAID
    order.paid_at = datetime.now(UTC)
    labels = db.scalars(
        text(
            "SELECT s.label FROM seats s JOIN order_items i ON i.seat_id = s.id "
            "WHERE i.order_id = :o ORDER BY s.label"
        ),
        {"o": order.id},
    ).all()
    data = {
        "order_id": str(order.id),
        "hold_id": str(hold.id),
        "seats": list(labels),
        "amount_paise": order.amount_paise,
        "late": late,
    }
    return Outcome(
        "paid_late" if late else "paid",
        str(order.id),
        events=[("order_paid", str(order.event_id), data)],
    )


def _refund(
    db: Session, provider: PaymentProvider, order: Order, payment_row, payment: dict, reason: str
) -> Outcome:
    refund_id = provider.refund(payment["id"], payment["amount"])  # idempotent per payment
    db.execute(
        update(Payment).where(Payment.id == payment_row).values(status=PaymentStatus.REFUNDED)
    )
    if order.status != OrderStatus.PAID:  # an extra payment on a paid order leaves it paid
        order.status = OrderStatus.REFUNDED
    log.warning("refunded %s for order %s: %s", payment["id"], order.id, reason)
    data = {
        "order_id": str(order.id),
        "payment_id": payment["id"],
        "refund_id": refund_id,
        "amount_paise": payment["amount"],
        "reason": reason,
    }
    return Outcome(
        "refunded",
        str(order.id),
        reason,
        events=[("payment_refunded", str(order.event_id), data)],
    )


def process(db: Session, provider: PaymentProvider, raw: bytes) -> Outcome:
    """Handle one webhook body in ONE transaction. Commits on success, rolls back on error."""
    try:
        outcome = _process(db, provider, raw)
        db.commit()
    except Exception:
        db.rollback()
        raise
    for kind, sale_event_id, data in outcome.events:
        sale_events.publish(kind, sale_event_id, data)  # after commit, best-effort
    return outcome


def _process(db: Session, provider: PaymentProvider, raw: bytes) -> Outcome:
    event = json.loads(raw)
    kind = event.get("event")
    if kind not in ("payment.captured", "payment.failed"):
        return Outcome("ignored", reason=str(kind))
    payment = event["payload"]["payment"]["entity"]

    db.execute(text("SET LOCAL lock_timeout = '5s'"))
    order = db.scalar(
        select(Order).where(Order.provider_order_id == payment["order_id"]).with_for_update()
    )
    if order is None:
        raise UnknownOrder(payment["order_id"])

    captured = kind == "payment.captured"
    payment_row = db.scalar(
        insert(Payment)
        .values(
            id=uuid.uuid4(),
            order_id=order.id,
            provider=provider.name,
            provider_payment_id=payment["id"],
            status=PaymentStatus.CAPTURED if captured else PaymentStatus.FAILED,
            amount_paise=int(payment["amount"]),
            currency=payment.get("currency", "INR"),
            raw_event=event,
        )
        .on_conflict_do_nothing(index_elements=["provider_payment_id"])
        .returning(Payment.id)
    )
    if payment_row is None:
        return Outcome("duplicate", str(order.id), payment["id"])

    if not captured:
        if order.status == OrderStatus.PENDING:
            order.status = OrderStatus.FAILED
        return Outcome("failed", str(order.id))

    if int(payment["amount"]) != order.amount_paise or payment.get("currency") != order.currency:
        return _refund(db, provider, order, payment_row, payment, "amount mismatch")
    if order.status in (OrderStatus.PAID, OrderStatus.REFUNDED):
        return _refund(db, provider, order, payment_row, payment, f"order already {order.status}")

    hold = db.scalar(select(Hold).where(Hold.id == order.hold_id).with_for_update())
    if order.status == OrderStatus.FAILED:
        other = db.scalar(
            select(Order.id).where(
                Order.hold_id == hold.id, Order.id != order.id, Order.status.in_(LIVE)
            )
        )
        if other:
            return _refund(db, provider, order, payment_row, payment, "a newer order exists")

    seat_ids = list(db.scalars(select(OrderItem.seat_id).where(OrderItem.order_id == order.id)))

    if hold.status == HoldStatus.ACTIVE:
        with db.begin_nested() as sp:
            if _sell_held(db, hold.id, seat_ids) == len(seat_ids):
                return _paid(db, order, hold, late=False)
            sp.rollback()
        return _refund(db, provider, order, payment_row, payment, "hold lost its seats")

    if hold.status == HoldStatus.RELEASED:
        # Late payment: the timer already gave the seats back. Re-hold them if ALL are free
        # and the buyer stays within the per-buyer limit; otherwise refund.
        event_row = db.get(Event, order.event_id)
        already = db.scalar(
            SEATS_ALREADY_HELD_BY_BUYER, {"event": order.event_id, "buyer": order.buyer_id}
        )
        if already + len(seat_ids) > event_row.per_buyer_limit:
            return _refund(db, provider, order, payment_row, payment, "per-buyer limit")
        with db.begin_nested() as sp:
            if _sell_free(db, hold.id, seat_ids) == len(seat_ids):
                return _paid(db, order, hold, late=True)
            sp.rollback()
        return _refund(db, provider, order, payment_row, payment, "seats no longer free")

    return _refund(db, provider, order, payment_row, payment, f"hold {hold.status}")


# --- the long-running worker ------------------------------------------------------------------
def handle_message(session_factory, provider: PaymentProvider, message: dict) -> Outcome:
    with session_factory() as db:
        return process(db, provider, message["Body"].encode())


def run() -> None:  # pragma: no cover - exercised live in the cluster
    from app import payment_queue
    from app.db import _session_factory
    from app.payments import get_provider

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    stopping = []
    signal.signal(signal.SIGTERM, lambda *_: stopping.append(1))
    factory, provider, sqs, url = (
        _session_factory(),
        get_provider(),
        payment_queue.sqs(),
        payment_queue.queue_url(),
    )
    log.info("order worker started")
    while not stopping:
        HEARTBEAT.touch()
        resp = sqs.receive_message(
            QueueUrl=url,
            MaxNumberOfMessages=5,
            WaitTimeSeconds=20,
            MessageAttributeNames=["All"],
            MessageSystemAttributeNames=["ApproximateReceiveCount"],
        )
        for m in resp.get("Messages", []):
            receives = m.get("Attributes", {}).get("ApproximateReceiveCount", "?")
            try:
                out = handle_message(factory, provider, m)
            except Exception as exc:
                # Not deleted: SQS redelivers after the visibility timeout; DLQ after 5 receives.
                log.error("message %s failed (receive %s): %r", m["MessageId"], receives, exc)
                continue
            sqs.delete_message(QueueUrl=url, ReceiptHandle=m["ReceiptHandle"])
            log.info(
                "message %s: %s order=%s %s", m["MessageId"], out.result, out.order_id, out.reason
            )
    log.info("order worker stopping")


if __name__ == "__main__":  # pragma: no cover
    run()
