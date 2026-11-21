"""Request and response bodies (pydantic)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.models import EventStatus


class EventCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")  # e.g. a "tenant_id" field is rejected, not ignored

    name: str = Field(min_length=1, max_length=200)
    venue: str = Field(min_length=1, max_length=200)
    starts_at: AwareDatetime
    sale_starts_at: AwareDatetime
    per_buyer_limit: int = Field(default=4, ge=1, le=10)

    @model_validator(mode="after")
    def sale_before_event(self) -> EventCreate:
        if self.sale_starts_at >= self.starts_at:
            raise ValueError("sale_starts_at must be before starts_at")
        return self


class ZoneSummary(BaseModel):
    zone: str
    price_paise: int
    seats: int


class EventOut(BaseModel):
    id: uuid.UUID
    name: str
    venue: str
    starts_at: datetime
    sale_starts_at: datetime
    per_buyer_limit: int
    status: EventStatus
    seat_count: int = 0
    zones: list[ZoneSummary] = []


class SeatMapUploaded(BaseModel):
    event_id: uuid.UUID
    seat_count: int
    zones: list[ZoneSummary]


class HoldCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seat_ids: list[uuid.UUID] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def unique_seats(self) -> HoldCreate:
        if len(set(self.seat_ids)) != len(self.seat_ids):
            raise ValueError("seat_ids must not repeat")
        return self


class HeldSeat(BaseModel):
    id: uuid.UUID
    label: str
    price_paise: int


class HoldOut(BaseModel):
    hold_id: uuid.UUID
    expires_at: datetime
    seats: list[HeldSeat]
    amount_paise: int
