"""Orders: create one for a hold (booking pass required), and read it back (owner only).

POST /book/{event_id}/orders  lives under /book/{event}/... so CloudFront's booking-pass
function (which reads the event id from the path) and the API both check the pass.
GET /orders/{order_id} is outside /book/*: the 15-minute pass may expire while the buyer waits
on the "payment pending" page, and only the order's owner can read it anyway.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import Buyer
from app.booking_pass import BookingPass
from app.db import get_session
from app.models import Hold, Order, OrderItem, OrderStatus, Seat
from app.orders import OrderError, create_order
from app.payments import PaymentProvider, get_provider
from app.schemas import OrderCreate, OrderOut

book = APIRouter(prefix="/book", tags=["orders"])
mine = APIRouter(prefix="/orders", tags=["orders"])
DB = Annotated[Session, Depends(get_session)]
Provider = Annotated[PaymentProvider, Depends(get_provider)]


def order_out(db: Session, order: Order, provider: PaymentProvider) -> OrderOut:
    labels = db.scalars(
        select(Seat.label)
        .join(OrderItem, OrderItem.seat_id == Seat.id)
        .where(OrderItem.order_id == order.id)
        .order_by(Seat.label)
    ).all()
    hold = db.get(Hold, order.hold_id)
    pending = order.status == OrderStatus.PENDING and order.provider_order_id
    return OrderOut(
        order_id=order.id,
        status=str(order.status),
        event_id=order.event_id,
        hold_id=order.hold_id,
        hold_expires_at=hold.expires_at,
        seats=list(labels),
        amount_paise=order.amount_paise,
        currency=order.currency,
        provider=order.provider,
        provider_order_id=order.provider_order_id,
        checkout=provider.checkout(order.provider_order_id) if pending else None,
        created_at=order.created_at,
        paid_at=order.paid_at,
    )


@book.post(
    "/{event_id}/orders",
    status_code=status.HTTP_201_CREATED,
    response_model=OrderOut,
    responses={
        200: {
            "description": "same Idempotency-Key (or a live order for this hold): existing order"
        },
        409: {"description": "hold not active, < 60 s left, lost its seats, or already paid"},
        422: {"description": "key reused for another hold, or return_url not allowed"},
        502: {"description": "payment provider unavailable; retry with the same key"},
    },
)
def create(
    event_id: uuid.UUID,
    body: OrderCreate,
    buyer: Buyer,
    booking_pass: BookingPass,
    db: DB,
    provider: Provider,
    response: Response,
    idempotency_key: Annotated[uuid.UUID, Header(description="a UUID per checkout attempt")],
):
    try:
        order, created = create_order(
            db,
            provider,
            event_id,
            buyer.sub,
            body.hold_id,
            idempotency_key,
            body.return_url,
            buyer_email=buyer.email,
        )
    except OrderError as err:
        return JSONResponse(status_code=err.status, content={"detail": err.detail, **err.extra})
    if not created:
        response.status_code = status.HTTP_200_OK
    return order_out(db, order, provider)


@mine.get("/{order_id}", response_model=OrderOut)
def read(order_id: uuid.UUID, buyer: Buyer, db: DB, provider: Provider):
    order = db.get(Order, order_id)
    if order is None or order.buyer_id != buyer.sub:  # someone else's order: same as missing
        raise HTTPException(status.HTTP_404_NOT_FOUND, "order not found")
    return order_out(db, order, provider)
