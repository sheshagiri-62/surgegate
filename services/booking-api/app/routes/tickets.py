"""GET /me/tickets: the buyer's tickets, with a short-lived download link for each order's PDF.

Cognito only (no booking pass): tickets are needed long after the sale. Only the caller's own
paid orders. The PDF link is a presigned S3 GET valid for 5 minutes; the bucket stays private
(SSE-KMS; the presigned request is signed with the booking-api role, which may read tickets/*).
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import Buyer
from app.db import get_session
from app.models import Event, Order, OrderStatus, Seat, Ticket

router = APIRouter(prefix="/me", tags=["tickets"])
DB = Annotated[Session, Depends(get_session)]
LINK_SECONDS = 300


@lru_cache(maxsize=1)
def _s3():
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        region_name=os.getenv("AWS_REGION", "ap-south-1"),
        config=Config(signature_version="s3v4"),
    )


def presign(key: str) -> str:
    return _s3().generate_presigned_url(
        "get_object",
        Params={"Bucket": os.environ["TICKETS_BUCKET"], "Key": key},
        ExpiresIn=LINK_SECONDS,
    )


@router.get("/tickets")
def my_tickets(buyer: Buyer, db: DB) -> dict:
    rows = db.execute(
        select(Order, Event, Ticket, Seat)
        .join(Event, Event.id == Order.event_id)
        .join(Ticket, Ticket.order_id == Order.id)
        .join(Seat, Seat.id == Ticket.seat_id)
        .where(Order.buyer_id == buyer.sub, Order.status == OrderStatus.PAID)
        .order_by(Order.paid_at.desc(), Seat.label)
    ).all()
    orders: dict = {}
    for order, event, ticket, seat in rows:
        o = orders.setdefault(
            order.id,
            {
                "order_id": str(order.id),
                "event": {
                    "id": str(event.id),
                    "name": event.name,
                    "venue": event.venue,
                    "starts_at": event.starts_at.isoformat(),
                },
                "paid_at": order.paid_at.isoformat() if order.paid_at else None,
                "emailed": order.ticket_email_sent_at is not None,
                "pdf_url": None,
                "tickets": [],
            },
        )
        if ticket.s3_key and o["pdf_url"] is None:
            o["pdf_url"] = presign(ticket.s3_key)
        o["tickets"].append(
            {
                "ticket_id": str(ticket.id),
                "seat": seat.label,
                "used_at": ticket.used_at.isoformat() if ticket.used_at else None,
            }
        )
    return {"orders": list(orders.values()), "link_expires_in": LINK_SECONDS}
