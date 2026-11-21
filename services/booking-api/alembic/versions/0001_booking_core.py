"""booking core: tenants, events, holds, seats, orders, order_items

Revision ID: 0001
Revises:
Create Date: 2026-11-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EVENT_STATUS = ("draft", "on_sale", "sold_out", "closed")
SEAT_STATUS = ("available", "held", "sold")
HOLD_STATUS = ("active", "released", "converted")
ORDER_STATUS = ("pending", "paid", "failed", "refunded")


def _enum(name: str, values: tuple[str, ...]) -> pg.ENUM:
    # create_type=False: the types are created explicitly below, exactly once.
    return pg.ENUM(*values, name=name, create_type=False)


def _id() -> sa.Column:
    return sa.Column("id", pg.UUID(as_uuid=True), primary_key=True)


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def upgrade() -> None:
    bind = op.get_bind()
    for name, values in (
        ("event_status", EVENT_STATUS),
        ("seat_status", SEAT_STATUS),
        ("hold_status", HOLD_STATUS),
        ("order_status", ORDER_STATUS),
    ):
        pg.ENUM(*values, name=name).create(bind, checkfirst=True)

    op.create_table(
        "tenants",
        _id(),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("plan", sa.String(20), server_default="free", nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name="pk_tenants"),
    )

    op.create_table(
        "events",
        _id(),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("venue", sa.String(200), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sale_starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("per_buyer_limit", sa.Integer, server_default="4", nullable=False),
        sa.Column(
            "status", _enum("event_status", EVENT_STATUS), server_default="draft", nullable=False
        ),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name="pk_events"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_events_tenant_id_tenants", ondelete="RESTRICT"
        ),
        sa.CheckConstraint(
            "per_buyer_limit BETWEEN 1 AND 10", name="ck_events_per_buyer_limit_range"
        ),
        sa.CheckConstraint("sale_starts_at < starts_at", name="ck_events_sale_before_event"),
    )
    op.create_index("ix_events_tenant_id_starts_at", "events", ["tenant_id", "starts_at"])

    op.create_table(
        "holds",
        _id(),
        sa.Column("event_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("buyer_id", sa.String(64), nullable=False),
        sa.Column("seat_count", sa.Integer, nullable=False),
        sa.Column(
            "status", _enum("hold_status", HOLD_STATUS), server_default="active", nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name="pk_holds"),
        sa.ForeignKeyConstraint(
            ["event_id"], ["events.id"], name="fk_holds_event_id_events", ondelete="CASCADE"
        ),
        sa.CheckConstraint("seat_count > 0", name="ck_holds_seat_count_positive"),
    )
    op.create_index(
        "ix_holds_event_id_buyer_id_status", "holds", ["event_id", "buyer_id", "status"]
    )

    op.create_table(
        "seats",
        _id(),
        sa.Column("event_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("section", sa.String(50), nullable=False),
        sa.Column("row", sa.String(10), nullable=False),
        sa.Column("number", sa.Integer, nullable=False),
        sa.Column("label", sa.String(80), nullable=False),
        sa.Column("zone", sa.String(30), nullable=False),
        sa.Column("price_paise", sa.Integer, nullable=False),
        sa.Column(
            "status",
            _enum("seat_status", SEAT_STATUS),
            server_default="available",
            nullable=False,
        ),
        sa.Column("hold_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("held_until", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_seats"),
        sa.ForeignKeyConstraint(
            ["event_id"], ["events.id"], name="fk_seats_event_id_events", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["hold_id"], ["holds.id"], name="fk_seats_hold_id_holds", ondelete="SET NULL"
        ),
        sa.UniqueConstraint("event_id", "label", name="uq_seats_event_id_label"),
        sa.CheckConstraint("price_paise >= 0", name="ck_seats_price_not_negative"),
        sa.CheckConstraint(
            "(status = 'held') = (hold_id IS NOT NULL AND held_until IS NOT NULL)",
            name="ck_seats_held_has_hold",
        ),
    )
    op.create_index("ix_seats_event_id_status", "seats", ["event_id", "status"])
    op.create_index("ix_seats_hold_id", "seats", ["hold_id"])

    op.create_table(
        "orders",
        _id(),
        sa.Column("event_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("hold_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("buyer_id", sa.String(64), nullable=False),
        sa.Column("idempotency_key", pg.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "status",
            _enum("order_status", ORDER_STATUS),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("amount_paise", sa.Integer, nullable=False),
        sa.Column("currency", sa.String(3), server_default="INR", nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name="pk_orders"),
        sa.ForeignKeyConstraint(
            ["event_id"], ["events.id"], name="fk_orders_event_id_events", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["hold_id"], ["holds.id"], name="fk_orders_hold_id_holds", ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("idempotency_key", name="uq_orders_idempotency_key"),
        sa.CheckConstraint("amount_paise >= 0", name="ck_orders_amount_not_negative"),
    )
    op.create_index("ix_orders_buyer_id", "orders", ["buyer_id"])

    op.create_table(
        "order_items",
        _id(),
        sa.Column("order_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("seat_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("price_paise", sa.Integer, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_order_items"),
        sa.ForeignKeyConstraint(
            ["order_id"], ["orders.id"], name="fk_order_items_order_id_orders", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["seat_id"], ["seats.id"], name="fk_order_items_seat_id_seats", ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("seat_id", name="uq_order_items_seat_id"),
        sa.CheckConstraint("price_paise >= 0", name="ck_order_items_price_not_negative"),
    )
    op.create_index("ix_order_items_order_id", "order_items", ["order_id"])


def downgrade() -> None:
    for table in ("order_items", "orders", "seats", "holds", "events", "tenants"):
        op.drop_table(table)
    bind = op.get_bind()
    for name in ("order_status", "hold_status", "seat_status", "event_status"):
        pg.ENUM(name=name).drop(bind, checkfirst=True)
