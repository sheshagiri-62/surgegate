"""Buyer endpoints under /book (later protected by the booking pass at CloudFront, Days 5-6)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import cache, sale_events
from app.auth import AnyUser, Buyer
from app.booking_pass import BookingPass
from app.db import get_session
from app.holds import HoldError, create_hold
from app.models import Event, Seat
from app.schemas import HoldCreate, HoldOut

router = APIRouter(prefix="/book", tags=["buyer"])
DB = Annotated[Session, Depends(get_session)]


def load_seat_map(db: Session, event_id: uuid.UUID) -> dict | None:
    """The seat map straight from PostgreSQL (the source of truth)."""
    event = db.get(Event, event_id)
    if event is None:
        return None
    seats = db.execute(
        select(
            Seat.id,
            Seat.label,
            Seat.section,
            Seat.row,
            Seat.number,
            Seat.zone,
            Seat.price_paise,
            Seat.status,
        )
        .where(Seat.event_id == event_id)
        .order_by(Seat.section, Seat.row, Seat.number)
    ).all()
    return {
        "event": {
            "id": str(event.id),
            "name": event.name,
            "venue": event.venue,
            "starts_at": event.starts_at.isoformat(),
            "sale_starts_at": event.sale_starts_at.isoformat(),
            "per_buyer_limit": event.per_buyer_limit,
        },
        "generated_at": datetime.now(UTC).isoformat(),
        "seats": [
            {
                "id": str(s.id),
                "label": s.label,
                "section": s.section,
                "row": s.row,
                "number": s.number,
                "zone": s.zone,
                "price_paise": s.price_paise,
                "status": s.status.value,
            }
            for s in seats
        ],
    }


@router.get("/{event_id}/seats")
def seat_map(
    event_id: uuid.UUID, user: AnyUser, booking_pass: BookingPass, db: DB, response: Response
) -> dict:
    """Seat map with each seat's status. Served from Redis; may lag a moment behind holds."""
    data, source = cache.get_seat_map(str(event_id), lambda: load_seat_map(db, event_id))
    if data is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "event not found")
    response.headers["X-Cache"] = source
    response.headers["Cache-Control"] = "private, max-age=1"
    return data


@router.post(
    "/{event_id}/holds",
    status_code=status.HTTP_201_CREATED,
    response_model=HoldOut,
    responses={409: {"description": "seat taken, limit reached, or sale not open"}},
)
def hold_seats(
    event_id: uuid.UUID, body: HoldCreate, buyer: Buyer, booking_pass: BookingPass, db: DB
):
    """Hold seats for 10 minutes. Exactly one buyer can ever hold a given seat."""
    try:
        result = create_hold(db, event_id, buyer.sub, body.seat_ids)
    except HoldError as err:
        return JSONResponse(
            status_code=err.status, content={"detail": err.detail, **jsonable(err.extra)}
        )
    sale_events.publish(
        "seat_held",
        str(event_id),
        {
            "hold_id": str(result.hold_id),
            "sub": buyer.sub,
            "seats": [s["label"] for s in result.seats],
            "amount_paise": result.amount_paise,
            "expires_at": result.expires_at.isoformat(),
        },
    )
    return HoldOut(
        hold_id=result.hold_id,
        expires_at=result.expires_at,
        seats=result.seats,
        amount_paise=result.amount_paise,
    )


def jsonable(extra: dict) -> dict:
    return {k: v.isoformat() if isinstance(v, datetime) else v for k, v in extra.items()}
