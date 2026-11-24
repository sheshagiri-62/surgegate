import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.models import Base

TABLES = {"tenants", "events", "seats", "holds", "orders", "order_items", "payments", "tickets"}


def test_metadata_has_the_booking_tables():
    assert TABLES <= set(Base.metadata.tables)


def test_a_sold_seat_is_unique_in_the_model():
    (ix,) = [
        i
        for i in Base.metadata.tables["order_items"].indexes
        if i.name == "uq_order_items_sold_seat"
    ]
    assert ix.unique and [c.name for c in ix.columns] == ["seat_id"]
    assert str(ix.dialect_options["postgresql"]["where"]) == "sold"


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
def test_a_seat_can_be_sold_in_only_one_order(migrated_engine):
    """Unsold items (failed/expired orders) may repeat a seat; a second SOLD item may not."""
    with migrated_engine.connect() as conn:
        event = _event(conn)
        seat = _seat(conn, event)
        orders = []
        for _ in range(3):  # three holds over time for the same seat, one order each
            hold, order = uuid.uuid4(), uuid.uuid4()
            conn.execute(
                text(
                    "INSERT INTO holds (id, event_id, buyer_id, seat_count, expires_at) "
                    "VALUES (:id, :e, 'buyer', 1, now())"
                ),
                {"id": hold, "e": event},
            )
            conn.execute(
                text(
                    "INSERT INTO orders (id, event_id, hold_id, buyer_id, idempotency_key, "
                    "amount_paise) VALUES (:id, :e, :h, 'buyer', :k, 50000)"
                ),
                {"id": order, "e": event, "h": hold, "k": uuid.uuid4()},
            )
            orders.append(order)
        item = text(
            "INSERT INTO order_items (id, order_id, seat_id, price_paise, sold) "
            "VALUES (:id, :o, :s, 50000, :sold)"
        )
        conn.execute(item, {"id": uuid.uuid4(), "o": orders[0], "s": seat, "sold": False})
        conn.execute(item, {"id": uuid.uuid4(), "o": orders[1], "s": seat, "sold": True})
        with pytest.raises(IntegrityError, match="uq_order_items_sold_seat"):
            conn.execute(item, {"id": uuid.uuid4(), "o": orders[2], "s": seat, "sold": True})
        conn.rollback()


@pytest.mark.integration
def test_one_live_order_per_hold(migrated_engine):
    with migrated_engine.connect() as conn:
        event = _event(conn)
        hold = uuid.uuid4()
        conn.execute(
            text(
                "INSERT INTO holds (id, event_id, buyer_id, seat_count, expires_at) "
                "VALUES (:id, :e, 'buyer', 1, now())"
            ),
            {"id": hold, "e": event},
        )
        ins = text(
            "INSERT INTO orders (id, event_id, hold_id, buyer_id, idempotency_key, amount_paise, "
            "status) VALUES (:id, :e, :h, 'buyer', :k, 1, CAST(:st AS order_status))"
        )
        conn.execute(
            ins, {"id": uuid.uuid4(), "e": event, "h": hold, "k": uuid.uuid4(), "st": "failed"}
        )
        conn.execute(
            ins, {"id": uuid.uuid4(), "e": event, "h": hold, "k": uuid.uuid4(), "st": "pending"}
        )
        with pytest.raises(IntegrityError, match="uq_orders_live_hold"):
            conn.execute(
                ins, {"id": uuid.uuid4(), "e": event, "h": hold, "k": uuid.uuid4(), "st": "pending"}
            )
        conn.rollback()


@pytest.mark.integration
def test_held_seat_must_reference_a_hold(migrated_engine):
    with migrated_engine.connect() as conn:
        seat = _seat(conn, _event(conn))
        with pytest.raises(IntegrityError, match="ck_seats_held_has_hold"):
            conn.execute(text("UPDATE seats SET status = 'held' WHERE id = :s"), {"s": seat})
        conn.rollback()
