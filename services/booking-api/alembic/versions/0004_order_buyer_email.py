"""orders.buyer_email (Day 8 Task 4 fix)

The buyer's verified email, copied from the access token's "email" claim when the order is
created. The ticket worker and the attendee export read it instead of calling Cognito
ListUsers once per buyer. Nullable: orders made before this change have none (the worker then
falls back to Cognito; the export leaves the cell empty).

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("buyer_email", sa.String(254)))


def downgrade() -> None:
    op.drop_column("orders", "buyer_email")
