"""PostgreSQL schema for the booking core (blueprint: "Data model").

PostgreSQL is the single source of truth for seats. Two database rules make overselling
impossible even if application code has a bug:

1. A hold is ONE conditional UPDATE on seats ... WHERE status = 'available' (see holds.py).
2. A seat can be SOLD in at most one order item: order_items has a partial UNIQUE index on
   seat_id WHERE sold. Unsold items (a failed or expired order) don't block re-selling.

Money is stored as integer paise (1 INR = 100 paise) so there is no float rounding.
Tenant isolation: every organiser-owned row reaches a tenant through events.tenant_id.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Stable constraint names, so Alembic migrations can refer to (and drop) them by name.
NAMING = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def _pg_enum(cls: type[enum.Enum], name: str) -> Enum:
    # Store the lower-case .value ("available"), not the Python member name.
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e])


class EventStatus(enum.StrEnum):
    DRAFT = "draft"
    ON_SALE = "on_sale"
    SOLD_OUT = "sold_out"
    CLOSED = "closed"


class SeatStatus(enum.StrEnum):
    AVAILABLE = "available"
    HELD = "held"
    SOLD = "sold"


class HoldStatus(enum.StrEnum):
    ACTIVE = "active"  # seats reserved, buyer is paying
    RELEASED = "released"  # timer fired (or buyer cancelled); seats back on sale
    CONVERTED = "converted"  # paid; seats are sold


class OrderStatus(enum.StrEnum):
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    REFUNDED = "refunded"


class PaymentStatus(enum.StrEnum):
    CAPTURED = "captured"
    FAILED = "failed"
    REFUNDED = "refunded"


class Tenant(Base):
    """An organiser workspace (college fest committee, event company...)."""

    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    plan: Mapped[str] = mapped_column(String(20), nullable=False, server_default="free")
    created_at: Mapped[datetime] = _created_at()

    events: Mapped[list[Event]] = relationship(back_populates="tenant")


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        CheckConstraint("per_buyer_limit BETWEEN 1 AND 10", name="per_buyer_limit_range"),
        CheckConstraint("sale_starts_at < starts_at", name="sale_before_event"),
        Index("ix_events_tenant_id_starts_at", "tenant_id", "starts_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    venue: Mapped[str] = mapped_column(String(200), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sale_starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    per_buyer_limit: Mapped[int] = mapped_column(Integer, nullable=False, server_default="4")
    status: Mapped[EventStatus] = mapped_column(
        _pg_enum(EventStatus, "event_status"), nullable=False, server_default="draft"
    )
    created_at: Mapped[datetime] = _created_at()

    tenant: Mapped[Tenant] = relationship(back_populates="events")
    seats: Mapped[list[Seat]] = relationship(back_populates="event")


class Seat(Base):
    __tablename__ = "seats"
    __table_args__ = (
        UniqueConstraint("event_id", "label"),
        CheckConstraint("price_paise >= 0", name="price_not_negative"),
        # A held seat always points at its hold and has an expiry; other seats have neither.
        CheckConstraint(
            "(status = 'held') = (hold_id IS NOT NULL AND held_until IS NOT NULL)",
            name="held_has_hold",
        ),
        # The hold UPDATE filters on (event_id, status) and then id = ANY(...).
        Index("ix_seats_event_id_status", "event_id", "status"),
        Index("ix_seats_hold_id", "hold_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    section: Mapped[str] = mapped_column(String(50), nullable=False)
    row: Mapped[str] = mapped_column(String(10), nullable=False)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(80), nullable=False)  # e.g. "A-12-7"
    zone: Mapped[str] = mapped_column(String(30), nullable=False)  # price zone, max 3 per event
    price_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[SeatStatus] = mapped_column(
        _pg_enum(SeatStatus, "seat_status"), nullable=False, server_default="available"
    )
    hold_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("holds.id", ondelete="SET NULL"), nullable=True
    )
    held_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    event: Mapped[Event] = relationship(back_populates="seats")


class Hold(Base):
    """A buyer's 10-minute reservation of one or more seats."""

    __tablename__ = "holds"
    __table_args__ = (
        CheckConstraint("seat_count > 0", name="seat_count_positive"),
        # Per-buyer limit query: active + converted holds of this buyer for this event.
        Index("ix_holds_event_id_buyer_id_status", "event_id", "buyer_id", "status"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    buyer_id: Mapped[str] = mapped_column(String(64), nullable=False)  # Cognito "sub"
    seat_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[HoldStatus] = mapped_column(
        _pg_enum(HoldStatus, "hold_status"), nullable=False, server_default="active"
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = _created_at()


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        # A double click or a retry with the same key creates one order (keys are per buyer).
        UniqueConstraint("buyer_id", "idempotency_key"),
        UniqueConstraint("provider_order_id"),  # the webhook finds the order by it
        CheckConstraint("amount_paise >= 0", name="amount_not_negative"),
        Index("ix_orders_buyer_id", "buyer_id"),
        # At most one live (pending or paid) order per hold; a failed one may be retried.
        Index(
            "uq_orders_live_hold",
            "hold_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'paid')"),
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("events.id", ondelete="RESTRICT"), nullable=False
    )
    hold_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("holds.id", ondelete="RESTRICT"), nullable=False
    )
    buyer_id: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[OrderStatus] = mapped_column(
        _pg_enum(OrderStatus, "order_status"), nullable=False, server_default="pending"
    )
    amount_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="INR")
    provider: Mapped[str] = mapped_column(String(20), nullable=False, server_default="mock")
    # Set once the provider has created its order; NULL means "retry the provider call".
    provider_order_id: Mapped[str | None] = mapped_column(String(64))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    items: Mapped[list[OrderItem]] = relationship(back_populates="order")


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = (
        # Second safety net (blueprint): a seat can be SOLD in only one order item, ever.
        # Items are written when the order is created (a snapshot of seats and prices, which
        # the late-payment rule needs); only the payment worker sets sold = true.
        Index("uq_order_items_sold_seat", "seat_id", unique=True, postgresql_where=text("sold")),
        CheckConstraint("price_paise >= 0", name="price_not_negative"),
        Index("ix_order_items_order_id", "order_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    seat_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("seats.id", ondelete="RESTRICT"), nullable=False
    )
    price_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    sold: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    order: Mapped[Order] = relationship(back_populates="items")


class Payment(Base):
    """One provider payment (from a webhook). provider_payment_id UNIQUE = exactly once."""

    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("provider_payment_id"),
        CheckConstraint("amount_paise >= 0", name="amount_not_negative"),
        Index("ix_payments_order_id", "order_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    provider_payment_id: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_event_id: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[PaymentStatus] = mapped_column(
        _pg_enum(PaymentStatus, "payment_status"), nullable=False
    )
    amount_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="INR")
    raw_event: Mapped[dict] = mapped_column(JSONB, nullable=False)
    received_at: Mapped[datetime] = _created_at()
