"""Seat holds: the only code that decides who gets a seat.

Blueprint ("Seat inventory: never sell a seat twice"): a hold is ONE conditional UPDATE that
only changes seats that are still available. Under PostgreSQL's row locking, when many requests
race for the same seat, the first to commit wins; every other UPDATE re-checks
`status = 'available'` after the winner commits, finds it false, and changes nothing.

One transaction per hold:
  1. per-buyer advisory lock   -> two parallel requests of the SAME buyer run one after the other,
                                  so both cannot pass the limit check below
  2. per-buyer limit           -> active (not expired) + paid seats of this buyer for this event
  3. INSERT the hold row
  4. the conditional UPDATE    -> seats locked in id order (no deadlocks between multi-seat
                                  holds); fewer rows than asked = someone was faster -> ROLLBACK
  5. COMMIT, then invalidate the seat-map cache
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app import cache
from app.models import Event, Hold

HOLD_MINUTES = 10

HOLD_SEATS = text(
    """
    UPDATE seats
    SET status = 'held', hold_id = :hold, held_until = :until
    WHERE id IN (
        SELECT id FROM seats
        WHERE event_id = :event AND id = ANY(:seat_ids) AND status = 'available'
        ORDER BY id
        FOR UPDATE
    )
    AND status = 'available'
    RETURNING id, label, price_paise
    """
)

SEATS_ALREADY_HELD_BY_BUYER = text(
    """
    SELECT COALESCE(SUM(seat_count), 0) FROM holds
    WHERE event_id = :event AND buyer_id = :buyer
      AND (status = 'converted' OR (status = 'active' AND expires_at > now()))
    """
)


class HoldError(Exception):
    def __init__(self, status: int, detail: str, **extra):
        super().__init__(detail)
        self.status, self.detail, self.extra = status, detail, extra


@dataclass(frozen=True)
class HoldResult:
    hold_id: uuid.UUID
    expires_at: datetime
    seats: list[dict]
    amount_paise: int


def create_hold(
    db: Session, event_id: uuid.UUID, buyer_id: str, seat_ids: list[uuid.UUID]
) -> HoldResult:
    event = db.get(Event, event_id)
    if event is None:
        raise HoldError(404, "event not found")
    now = datetime.now(UTC)
    if now < event.sale_starts_at:
        raise HoldError(409, "the sale has not started yet", sale_starts_at=event.sale_starts_at)
    if now >= event.starts_at:
        raise HoldError(409, "the event has already started")
    if len(seat_ids) > event.per_buyer_limit:
        raise HoldError(422, f"at most {event.per_buyer_limit} seats per buyer")

    try:
        # Wait at most 2 s for another transaction's lock instead of piling up requests.
        db.execute(text("SET LOCAL lock_timeout = '2s'"))
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
            {"k": f"hold:{event_id}:{buyer_id}"},
        )
        already = db.scalar(SEATS_ALREADY_HELD_BY_BUYER, {"event": event_id, "buyer": buyer_id})
        if already + len(seat_ids) > event.per_buyer_limit:
            raise HoldError(
                409,
                f"per-buyer limit is {event.per_buyer_limit}; you already hold {already}",
                limit=event.per_buyer_limit,
                held=already,
            )

        expires_at = now + timedelta(minutes=HOLD_MINUTES)
        hold = Hold(
            id=uuid.uuid4(),
            event_id=event_id,
            buyer_id=buyer_id,
            seat_count=len(seat_ids),
            expires_at=expires_at,
        )
        db.add(hold)
        db.flush()

        rows = db.execute(
            HOLD_SEATS,
            {"hold": hold.id, "until": expires_at, "event": event_id, "seat_ids": seat_ids},
        ).all()
        if len(rows) != len(seat_ids):
            got = {r.id for r in rows}
            raise HoldError(
                409,
                "someone just took that seat",
                unavailable=[str(s) for s in seat_ids if s not in got],
            )
        db.commit()
    except HoldError:
        db.rollback()
        raise
    except OperationalError as exc:
        db.rollback()
        # lock_timeout (55P03) or deadlock (40P01): nothing was held; the buyer can retry.
        if getattr(exc.orig, "sqlstate", None) in {"55P03", "40P01"}:
            raise HoldError(409, "seats are busy, please try again") from exc
        raise

    cache.invalidate_seat_map(str(event_id))
    return HoldResult(
        hold_id=hold.id,
        expires_at=expires_at,
        seats=[{"id": str(r.id), "label": r.label, "price_paise": r.price_paise} for r in rows],
        amount_paise=sum(r.price_paise for r in rows),
    )
