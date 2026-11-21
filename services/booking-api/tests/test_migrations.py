import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.models import Base

TABLES = {"tenants", "events", "seats", "holds", "orders", "order_items"}


def test_metadata_has_the_six_booking_tables():
    assert TABLES <= set(Base.metadata.tables)


def test_order_items_seat_id_is_unique_in_the_model():
    uniques = {
        tuple(c.columns.keys())
        for c in Base.metadata.tables["order_items"].constraints
        if c.__class__.__name__ == "UniqueConstraint"
    }
    assert ("seat_id",) in uniques


@pytest.mark.integration
def test_migration_matches_models(migrated_engine):
    """The hand-written migration creates exactly what the models describe."""
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    with migrated_engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == [], diff


@pytest.mark.integration
def test_downgrade_then_upgrade_round_trips(alembic_cfg, migrated_engine):
    from alembic import command

    command.downgrade(alembic_cfg, "base")
    assert TABLES.isdisjoint(inspect(migrated_engine).get_table_names())
    command.upgrade(alembic_cfg, "head")
    assert TABLES <= set(inspect(migrated_engine).get_table_names())


def _event(conn) -> uuid.UUID:
    tenant, event = uuid.uuid4(), uuid.uuid4()
    now = datetime.now(UTC)
    conn.execute(text("INSERT INTO tenants (id, name) VALUES (:id, 't')"), {"id": tenant})
    conn.execute(
        text(
            "INSERT INTO events (id, tenant_id, name, venue, starts_at, sale_starts_at) "
            "VALUES (:id, :t, 'e', 'v', :s, :ss)"
        ),
        {"id": event, "t": tenant, "s": now + timedelta(days=2), "ss": now + timedelta(days=1)},
    )
    return event


def _seat(conn, event, label="A-1-1") -> uuid.UUID:
    seat = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO seats (id, event_id, section, row, number, label, zone, price_paise) "
            "VALUES (:id, :e, 'A', '1', 1, :l, 'gold', 50000)"
        ),
        {"id": seat, "e": event, "l": label},
    )
    return seat


@pytest.mark.integration
def test_a_seat_can_be_in_only_one_order(migrated_engine):
    with migrated_engine.connect() as conn:
        event = _event(conn)
        seat = _seat(conn, event)
        hold = uuid.uuid4()
        conn.execute(
            text(
                "INSERT INTO holds (id, event_id, buyer_id, seat_count, expires_at) "
                "VALUES (:id, :e, 'buyer', 1, now())"
            ),
            {"id": hold, "e": event},
        )
        for _ in range(2):
            order = uuid.uuid4()
            conn.execute(
                text(
                    "INSERT INTO orders (id, event_id, hold_id, buyer_id, idempotency_key, "
                    "amount_paise) VALUES (:id, :e, :h, 'buyer', :k, 50000)"
                ),
                {"id": order, "e": event, "h": hold, "k": uuid.uuid4()},
            )
        with pytest.raises(IntegrityError, match="uq_order_items_seat_id"):
            for order_id in (
                conn.execute(text("SELECT id FROM orders WHERE hold_id = :h"), {"h": hold})
                .scalars()
                .all()
            ):
                conn.execute(
                    text(
                        "INSERT INTO order_items (id, order_id, seat_id, price_paise) "
                        "VALUES (:id, :o, :s, 50000)"
                    ),
                    {"id": uuid.uuid4(), "o": order_id, "s": seat},
                )
        conn.rollback()


@pytest.mark.integration
def test_held_seat_must_reference_a_hold(migrated_engine):
    with migrated_engine.connect() as conn:
        seat = _seat(conn, _event(conn))
        with pytest.raises(IntegrityError, match="ck_seats_held_has_hold"):
            conn.execute(text("UPDATE seats SET status = 'held' WHERE id = :s"), {"s": seat})
        conn.rollback()
