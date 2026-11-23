"""Create an order for a hold (blueprint "Payments and idempotency", Day 7 Task 3).

Rules:
- The Idempotency-Key is unique PER BUYER: the same key again returns the same order (a double
  click or a retried request never makes two). The same key for another hold is refused (422).
- The order is for a hold of THIS buyer, for THIS event, still active, with at least 60 s left
  (otherwise 409: the buyer would be sent to pay for seats about to be released).
- At most one live (pending/paid) order per hold (partial unique index). A second key for the
  same hold gets the existing pending order back.
- The amount comes from the held seats in the database, never from the browser.
- order_items are a snapshot of the held seats and prices (sold = false until the payment
  worker confirms; Task 4).
- The provider order is created AFTER the order row commits. If the provider call fails, the
  order stays pending without provider_order_id, and a retry with the same key finishes it.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from urllib.parse import urlencode, urlsplit

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Hold, HoldStatus, Order, OrderItem, OrderStatus, Seat, SeatStatus
from app.payments import PaymentProvider, ProviderError

MIN_SECONDS_LEFT = 60
LIVE = (OrderStatus.PENDING, OrderStatus.PAID)


class OrderError(Exception):
    def __init__(self, status: int, detail: str, **extra):
        super().__init__(detail)
        self.status, self.detail, self.extra = status, detail, extra


def return_origins() -> set[str]:
    raw = os.getenv("ORDER_RETURN_ORIGINS") or os.getenv("CORS_ALLOW_ORIGINS", "")
    return {o.strip().rstrip("/") for o in raw.split(",") if o.strip()}


def check_return_url(url: str | None) -> None:
    """Only send buyers back to our own sites (no open redirect through the checkout)."""
    if url is None:
        return
    parts = urlsplit(url)
    if f"{parts.scheme}://{parts.netloc}" not in return_origins():
        raise OrderError(422, "return_url is not an allowed origin")


def _callback(return_url: str | None, order_id: uuid.UUID) -> str:
    if not return_url:
        return ""
    sep = "&" if urlsplit(return_url).query else "?"
    return f"{return_url}{sep}{urlencode({'id': str(order_id)})}"


def _by_key(db: Session, buyer_id: str, key: uuid.UUID) -> Order | None:
    return db.scalar(select(Order).where(Order.buyer_id == buyer_id, Order.idempotency_key == key))


def _live_for_hold(db: Session, hold_id: uuid.UUID) -> Order | None:
    return db.scalar(select(Order).where(Order.hold_id == hold_id, Order.status.in_(LIVE)))


def ensure_provider_order(
    db: Session, provider: PaymentProvider, order: Order, return_url: str | None
) -> Order:
    if order.provider_order_id or order.status != OrderStatus.PENDING:
        return order
    try:
        po = provider.create_order(
            order.amount_paise,
            order.currency,
            receipt=str(order.id),
            notes={
                "booking_order_id": str(order.id),
                "hold_id": str(order.hold_id),
                "callback_url": _callback(return_url, order.id),
            },
        )
    except ProviderError as exc:
        raise OrderError(
            502, "payment provider unavailable; try again with the same Idempotency-Key"
        ) from exc
    # Two retries racing: the first provider order wins; the other is never paid for.
    db.execute(
        update(Order)
        .where(Order.id == order.id, Order.provider_order_id.is_(None))
        .values(provider_order_id=po.id)
    )
    db.commit()
    db.refresh(order)
    return order


def create_order(
    db: Session,
    provider: PaymentProvider,
    event_id: uuid.UUID,
    buyer_id: str,
    hold_id: uuid.UUID,
    key: uuid.UUID,
    return_url: str | None,
) -> tuple[Order, bool]:
    """Return (order, created). created=False means an existing order was returned."""
    check_return_url(return_url)

    if existing := _by_key(db, buyer_id, key):
        if existing.hold_id != hold_id:
            raise OrderError(422, "this Idempotency-Key was already used for another hold")
        return ensure_provider_order(db, provider, existing, return_url), False

    try:
        # Lock the hold: the release worker (hold timer) can't free it while we decide.
        hold = db.scalar(select(Hold).where(Hold.id == hold_id).with_for_update())
        if hold is None or hold.buyer_id != buyer_id or hold.event_id != event_id:
            raise OrderError(404, "hold not found")
        if hold.status != HoldStatus.ACTIVE:
            raise OrderError(409, "this hold is no longer active; hold the seats again")
        left = (hold.expires_at - datetime.now(UTC)).total_seconds()
        if left < MIN_SECONDS_LEFT:
            raise OrderError(
                409,
                f"less than {MIN_SECONDS_LEFT} seconds left on this hold; hold the seats again",
                seconds_left=max(0, int(left)),
            )
        if live := _live_for_hold(db, hold_id):
            db.rollback()
            if live.status == OrderStatus.PAID:
                raise OrderError(409, "this hold is already paid", order_id=str(live.id))
            return ensure_provider_order(db, provider, live, return_url), False

        seats = db.execute(
            select(Seat.id, Seat.price_paise).where(
                Seat.hold_id == hold_id, Seat.status == SeatStatus.HELD
            )
        ).all()
        if len(seats) != hold.seat_count:
            raise OrderError(409, "this hold has lost its seats; hold the seats again")

        order = Order(
            id=uuid.uuid4(),
            event_id=event_id,
            hold_id=hold_id,
            buyer_id=buyer_id,
            idempotency_key=key,
            amount_paise=sum(s.price_paise for s in seats),
            provider=provider.name,
        )
        db.add(order)
        db.flush()
        db.add_all(
            OrderItem(order_id=order.id, seat_id=s.id, price_paise=s.price_paise) for s in seats
        )
        db.commit()
    except OrderError:
        db.rollback()
        raise
    except IntegrityError:
        # A concurrent request won: same key, or another live order for this hold.
        db.rollback()
        again = _by_key(db, buyer_id, key) or _live_for_hold(db, hold_id)
        if again is None:
            raise
        if again.hold_id != hold_id:
            raise OrderError(
                422, "this Idempotency-Key was already used for another hold"
            ) from None
        return ensure_provider_order(db, provider, again, return_url), False

    return ensure_provider_order(db, provider, order, return_url), True
