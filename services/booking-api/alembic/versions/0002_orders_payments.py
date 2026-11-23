"""orders + payments for checkout (Day 7 Task 3, ADR 004)

- orders: idempotency key unique PER BUYER; provider, provider_order_id (unique), paid_at,
  updated_at; at most one live (pending/paid) order per hold.
- order_items: written at order creation (snapshot); `sold` flag; a seat can be sold in only
  one item (partial unique index), so failed/expired orders don't block re-selling the seat.
- payments: one row per provider payment; provider_payment_id unique (exactly-once webhooks).

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PAYMENT_STATUS = ("captured", "failed", "refunded")


def upgrade() -> None:
    # --- orders -------------------------------------------------------------------------
    op.drop_constraint("uq_orders_idempotency_key", "orders", type_="unique")
    op.create_unique_constraint(
        "uq_orders_buyer_id_idempotency_key", "orders", ["buyer_id", "idempotency_key"]
    )
    op.add_column(
        "orders", sa.Column("provider", sa.String(20), server_default="mock", nullable=False)
    )
    op.add_column("orders", sa.Column("provider_order_id", sa.String(64)))
    op.add_column("orders", sa.Column("paid_at", sa.DateTime(timezone=True)))
    op.add_column(
        "orders",
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_unique_constraint("uq_orders_provider_order_id", "orders", ["provider_order_id"])
    op.create_index(
        "uq_orders_live_hold",
        "orders",
        ["hold_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'paid')"),
    )

    # --- order_items ----------------------------------------------------------------------
    op.drop_constraint("uq_order_items_seat_id", "order_items", type_="unique")
    op.add_column(
        "order_items", sa.Column("sold", sa.Boolean, server_default="false", nullable=False)
    )
    # Every existing item counts as sold (none exist yet; this keeps the rule if any did).
    op.execute("UPDATE order_items SET sold = true")
    op.create_index(
        "uq_order_items_sold_seat",
        "order_items",
        ["seat_id"],
        unique=True,
        postgresql_where=sa.text("sold"),
    )

    # --- payments -------------------------------------------------------------------------
    payment_status = pg.ENUM(*PAYMENT_STATUS, name="payment_status", create_type=False)
    pg.ENUM(*PAYMENT_STATUS, name="payment_status").create(op.get_bind(), checkfirst=True)
    op.create_table(
        "payments",
        sa.Column("id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("order_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("provider_payment_id", sa.String(64), nullable=False),
        sa.Column("provider_event_id", sa.String(64)),
        sa.Column("status", payment_status, nullable=False),
        sa.Column("amount_paise", sa.Integer, nullable=False),
        sa.Column("currency", sa.String(3), server_default="INR", nullable=False),
        sa.Column("raw_event", pg.JSONB, nullable=False),
        sa.Column(
            "received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_payments"),
        sa.ForeignKeyConstraint(
            ["order_id"], ["orders.id"], name="fk_payments_order_id_orders", ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("provider_payment_id", name="uq_payments_provider_payment_id"),
        sa.CheckConstraint("amount_paise >= 0", name="ck_payments_amount_not_negative"),
    )
    op.create_index("ix_payments_order_id", "payments", ["order_id"])


def downgrade() -> None:
    op.drop_table("payments")
    pg.ENUM(name="payment_status").drop(op.get_bind(), checkfirst=True)

    op.drop_index("uq_order_items_sold_seat", table_name="order_items")
    op.drop_column("order_items", "sold")
    op.create_unique_constraint("uq_order_items_seat_id", "order_items", ["seat_id"])

    op.drop_index("uq_orders_live_hold", table_name="orders")
    op.drop_constraint("uq_orders_provider_order_id", "orders", type_="unique")
    for col in ("updated_at", "paid_at", "provider_order_id", "provider"):
        op.drop_column("orders", col)
    op.drop_constraint("uq_orders_buyer_id_idempotency_key", "orders", type_="unique")
    op.create_unique_constraint("uq_orders_idempotency_key", "orders", ["idempotency_key"])
