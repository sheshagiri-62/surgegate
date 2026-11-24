"""tickets + ticket-email bookkeeping on orders (Day 8 Task 1)

- tickets: one per order item (order_item_id UNIQUE: re-issuing is a no-op), the seat, the key
  id of the QR token, the PDF's S3 key, and used_at for the gate's one-time check-in.
- orders: ticket_email_claimed_at / ticket_email_sent_at / ticket_email_message_id, so a replayed
  order_paid never sends a second email.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tickets",
        sa.Column("id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("order_item_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("order_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("seat_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("kid", sa.String(40), nullable=False),
        sa.Column("s3_key", sa.String(300)),
        sa.Column(
            "issued_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("id", name="pk_tickets"),
        sa.ForeignKeyConstraint(
            ["order_item_id"],
            ["order_items.id"],
            name="fk_tickets_order_item_id_order_items",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["order_id"], ["orders.id"], name="fk_tickets_order_id_orders", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["event_id"], ["events.id"], name="fk_tickets_event_id_events", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["seat_id"], ["seats.id"], name="fk_tickets_seat_id_seats", ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("order_item_id", name="uq_tickets_order_item_id"),
    )
    op.create_index("ix_tickets_order_id", "tickets", ["order_id"])
    op.add_column("orders", sa.Column("ticket_email_claimed_at", sa.DateTime(timezone=True)))
    op.add_column("orders", sa.Column("ticket_email_sent_at", sa.DateTime(timezone=True)))
    op.add_column("orders", sa.Column("ticket_email_message_id", sa.String(100)))


def downgrade() -> None:
    for col in ("ticket_email_message_id", "ticket_email_sent_at", "ticket_email_claimed_at"):
        op.drop_column("orders", col)
    op.drop_table("tickets")
