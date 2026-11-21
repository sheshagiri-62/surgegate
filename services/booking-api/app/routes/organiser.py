"""Organiser endpoints (blueprint: POST /org/events, PUT /org/events/{id}/seats).

Tenant isolation: every query is filtered by the tenant from the caller's verified token
(`Organiser.tenant_id`). An event of another tenant is answered with 404, exactly like an event
that does not exist, so organisers cannot even learn which event IDs exist elsewhere.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import delete, func, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app import cache
from app.auth import Organiser
from app.db import get_session
from app.models import Event, Seat, SeatStatus, Tenant
from app.schemas import EventCreate, EventOut, SeatMapUploaded, ZoneSummary
from app.seatmap_csv import SeatMapError, parse_seat_map

router = APIRouter(prefix="/org", tags=["organiser"])
DB = Annotated[Session, Depends(get_session)]
MAX_UPLOAD_BYTES = 2 * 1024 * 1024


def _ensure_tenant(db: Session, tenant_id: uuid.UUID) -> None:
    # A tenant row is created the first time one of its organisers calls the API.
    db.execute(
        pg_insert(Tenant)
        .values(id=tenant_id, name=f"tenant-{str(tenant_id)[:8]}")
        .on_conflict_do_nothing(index_elements=[Tenant.id])
    )


def _own_event(db: Session, org: Organiser, event_id: uuid.UUID, *, lock: bool = False) -> Event:
    query = select(Event).where(Event.id == event_id, Event.tenant_id == org.tenant_id)
    if lock:
        query = query.with_for_update()
    event = db.scalars(query).one_or_none()
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "event not found")
    return event


def _zones(db: Session, event_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[ZoneSummary]]:
    rows = db.execute(
        select(Seat.event_id, Seat.zone, Seat.price_paise, func.count())
        .where(Seat.event_id.in_(event_ids))
        .group_by(Seat.event_id, Seat.zone, Seat.price_paise)
        .order_by(Seat.event_id, Seat.price_paise.desc())
    ).all()
    out: dict[uuid.UUID, list[ZoneSummary]] = {}
    for event_id, zone, price, count in rows:
        out.setdefault(event_id, []).append(ZoneSummary(zone=zone, price_paise=price, seats=count))
    return out


def _out(event: Event, zones: list[ZoneSummary]) -> EventOut:
    return EventOut(
        id=event.id,
        name=event.name,
        venue=event.venue,
        starts_at=event.starts_at,
        sale_starts_at=event.sale_starts_at,
        per_buyer_limit=event.per_buyer_limit,
        status=event.status,
        seat_count=sum(z.seats for z in zones),
        zones=zones,
    )


@router.post("/events", status_code=status.HTTP_201_CREATED, response_model=EventOut)
def create_event(body: EventCreate, org: Organiser, db: DB) -> EventOut:
    _ensure_tenant(db, org.tenant_id)
    event = Event(tenant_id=org.tenant_id, **body.model_dump())
    db.add(event)
    db.commit()
    db.refresh(event)
    return _out(event, [])


@router.get("/events", response_model=list[EventOut])
def list_events(org: Organiser, db: DB) -> list[EventOut]:
    events = db.scalars(
        select(Event).where(Event.tenant_id == org.tenant_id).order_by(Event.starts_at)
    ).all()
    zones = _zones(db, [e.id for e in events]) if events else {}
    return [_out(e, zones.get(e.id, [])) for e in events]


@router.get("/events/{event_id}", response_model=EventOut)
def get_event(event_id: uuid.UUID, org: Organiser, db: DB) -> EventOut:
    event = _own_event(db, org, event_id)
    return _out(event, _zones(db, [event.id]).get(event.id, []))


@router.put("/events/{event_id}/seats", response_model=SeatMapUploaded)
async def upload_seat_map(event_id: uuid.UUID, request: Request, org: Organiser, db: DB):
    """Replace the event's seat map with the CSV in the request body (Content-Type: text/csv)."""
    if request.headers.get("content-type", "").split(";")[0].strip() != "text/csv":
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "send the CSV as text/csv")
    data = await request.body()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "seat map larger than 2 MB")
    try:
        seats = parse_seat_map(data)
    except SeatMapError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    # Lock the event row: two uploads (or an upload and a hold) cannot interleave.
    event = _own_event(db, org, event_id, lock=True)
    taken = db.scalar(
        select(func.count())
        .select_from(Seat)
        .where(Seat.event_id == event.id, Seat.status != SeatStatus.AVAILABLE)
    )
    if taken:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"{taken} seats are held or sold; the map can't be replaced"
        )
    db.execute(delete(Seat).where(Seat.event_id == event.id))
    db.execute(
        insert(Seat),
        [
            {
                "event_id": event.id,
                "section": s.section,
                "row": s.row,
                "number": s.number,
                "label": s.label,
                "zone": s.zone,
                "price_paise": s.price_paise,
            }
            for s in seats
        ],
    )
    db.commit()
    cache.invalidate_seat_map(str(event.id))
    zones = _zones(db, [event.id]).get(event.id, [])
    return SeatMapUploaded(event_id=event.id, seat_count=len(seats), zones=zones)
