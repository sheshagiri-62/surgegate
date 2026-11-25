"""Gate check-in and attendee export (Day 8 Task 4). Organisers, their own events only.

POST /org/events/{id}/check-in   {"token": "<the QR's signed ticket token>"}
    verify the token (HMAC, typ "ticket", THIS event), the order is still paid, then mark the
    ticket used ONCE:  UPDATE tickets SET used_at = now() WHERE id = :tid AND used_at IS NULL
      200 {"result": "admitted", seat, ...}      first scan
      409 {"result": "already used", used_at}    any later scan (a screenshot, a second copy)
      400 forged / not a ticket / another event  404 unknown ticket   409 order not paid
GET /org/events/{id}/attendees.csv
    one row per ticket of a paid order: seat, order, buyer email (from the order), ticket,
    used_at; cells are escaped against CSV formula injection
"""

from __future__ import annotations

import csv
import io
import json
import os
import time
import uuid
from typing import Annotated

from fastapi import Depends
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app import ticket_token
from app.auth import Organiser
from app.db import get_session
from app.models import Order, OrderStatus, Seat, Ticket
from app.routes.organiser import _own_event, router

DB = Annotated[Session, Depends(get_session)]
_key_cache: dict[str, tuple[float, dict[str, str]]] = {}


class CheckIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=10, max_length=2000)


def ticket_keys() -> dict[str, str]:
    """{kid: key} for verification (old kids can be added here during a key rotation)."""
    if raw := os.getenv("TICKET_KEY_JSON"):
        k = json.loads(raw)
        return {k["kid"]: k["key"]}
    secret_id = os.environ["TICKET_KEY_SECRET_ID"]
    hit = _key_cache.get(secret_id)
    if hit and time.monotonic() - hit[0] < 300:
        return hit[1]
    import boto3

    sm = boto3.client("secretsmanager", region_name=os.getenv("AWS_REGION", "ap-south-1"))
    k = json.loads(sm.get_secret_value(SecretId=secret_id)["SecretString"])
    _key_cache[secret_id] = (time.monotonic(), {k["kid"]: k["key"]})
    return _key_cache[secret_id][1]


def _out(status: int, **body) -> JSONResponse:
    return JSONResponse(status_code=status, content=body)


@router.post("/events/{event_id}/check-in")
def check_in(event_id: uuid.UUID, body: CheckIn, org: Organiser, db: DB):
    event = _own_event(db, org, event_id)
    try:
        claims = ticket_token.verify(body.token, ticket_keys(), str(event.id))
    except ValueError as err:
        return _out(400, result="refused", reason=str(err))
    try:
        tid = uuid.UUID(claims["tid"])
    except (KeyError, ValueError):
        return _out(400, result="refused", reason="malformed ticket")
    row = db.execute(
        select(Ticket, Order.status, Seat.label)
        .join(Order, Order.id == Ticket.order_id)
        .join(Seat, Seat.id == Ticket.seat_id)
        .where(Ticket.id == tid, Ticket.event_id == event.id)
    ).first()
    if row is None:
        return _out(404, result="refused", reason="unknown ticket")
    ticket, order_status, label = row
    if order_status != OrderStatus.PAID:
        return _out(409, result="refused", reason=f"order is {order_status}", seat=label)
    used = db.execute(
        text(
            "UPDATE tickets SET used_at = now() WHERE id = :t AND used_at IS NULL RETURNING used_at"
        ),
        {"t": tid},
    ).scalar()
    db.commit()
    if used is None:
        db.refresh(ticket)
        return _out(
            409,
            result="already used",
            seat=label,
            used_at=ticket.used_at.isoformat() if ticket.used_at else None,
        )
    return _out(200, result="admitted", seat=label, ticket_id=str(tid), used_at=used.isoformat())


def csv_safe(value) -> str:
    """Stop CSV/formula injection: a cell starting with = + - @ (or tab / CR) is opened as a
    formula by Excel and Sheets, so prefix it with ' (OWASP CSV injection guidance)."""
    text_value = "" if value is None else str(value)
    if text_value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text_value
    return text_value


@router.get("/events/{event_id}/attendees.csv", response_class=Response)
def attendees(event_id: uuid.UUID, org: Organiser, db: DB):
    event = _own_event(db, org, event_id)
    rows = db.execute(
        select(Seat.label, Order.id, Order.buyer_email, Order.paid_at, Ticket.id, Ticket.used_at)
        .join(Ticket, Ticket.seat_id == Seat.id)
        .join(Order, Order.id == Ticket.order_id)
        .where(Ticket.event_id == event.id, Order.status == OrderStatus.PAID)
        .order_by(Seat.label)
    ).all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["seat", "order_id", "buyer_email", "paid_at", "ticket_id", "checked_in_at"])
    for label, oid, email, paid_at, tid, used_at in rows:
        w.writerow(
            csv_safe(v)
            for v in (
                label,
                oid,
                email,
                paid_at.isoformat() if paid_at else "",
                tid,
                used_at.isoformat() if used_at else "",
            )
        )
    name = f"attendees-{str(event.id)[:8]}.csv"
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
