"""The hold timer's release: only seats still held by THIS hold go back on sale.

The database schema comes from the booking API's own Alembic migrations (CI and local runs apply
them first), so these tests always run against the real tables and constraints.
"""

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest

pytestmark = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="needs DATABASE_URL")

from sg_workers import release_hold  # noqa: E402
from sg_workers.db import connect  # noqa: E402


@pytest.fixture
def db():
    conn = connect()
    yield conn
    conn.close()


def make_event(conn):
    tenant, event = str(uuid.uuid4()), str(uuid.uuid4())
    now = datetime.now(UTC)
    conn.run("INSERT INTO tenants (id, name) VALUES (CAST(:t AS uuid), 't')", t=tenant)
    conn.run(
        "INSERT INTO events (id, tenant_id, name, venue, starts_at, sale_starts_at) "
        "VALUES (CAST(:e AS uuid), CAST(:t AS uuid), 'e', 'v', :s, :ss)",
        e=event,
        t=tenant,
        s=now + timedelta(days=2),
        ss=now - timedelta(hours=1),
    )
    return event


def make_hold(conn, event, status="active"):
    hold = str(uuid.uuid4())
    conn.run(
        "INSERT INTO holds (id, event_id, buyer_id, seat_count, status, expires_at) "
        "VALUES (CAST(:h AS uuid), CAST(:e AS uuid), 'b', 1, CAST(:s AS hold_status), now())",
        h=hold,
        e=event,
        s=status,
    )
    return hold


def make_seat(conn, event, label, status="available", hold=None):
    seat = str(uuid.uuid4())
    conn.run(
        "INSERT INTO seats (id, event_id, section, row, number, label, zone, price_paise, status, "
        "hold_id, held_until) VALUES (CAST(:id AS uuid), CAST(:e AS uuid), 'A', '1', 1, :l, 'g', "
        "100, CAST(:s AS seat_status), CAST(:h AS uuid), :until)",
        id=seat,
        e=event,
        l=label,
        s=status,
        h=hold,
        until=datetime.now(UTC) if status == "held" else None,
    )
    return seat


def seat_status(conn, label, event):
    return conn.run(
        "SELECT status::text, hold_id::text FROM seats "
        "WHERE label = :l AND event_id = CAST(:e AS uuid)",
        l=label,
        e=event,
    )[0]


def hold_status(conn, hold):
    return conn.run("SELECT status::text FROM holds WHERE id = CAST(:h AS uuid)", h=hold)[0][0]


def test_unpaid_hold_is_released(db):
    ev = make_event(db)
    h = make_hold(db, ev)
    make_seat(db, ev, "A-1-1", "held", h)
    make_seat(db, ev, "A-1-2", "held", h)
    out = release_hold.release(h)
    assert out == {"hold_id": h, "released_seats": ["A-1-1", "A-1-2"], "hold_was_active": True}
    assert seat_status(db, "A-1-1", ev) == ["available", None]
    assert hold_status(db, h) == "released"


def test_sold_seat_is_never_released(db):
    ev = make_event(db)
    h = make_hold(db, ev, status="converted")  # paid
    make_seat(db, ev, "B-1-1", "sold", h)
    out = release_hold.release(h)
    assert out["released_seats"] == [] and out["hold_was_active"] is False
    assert seat_status(db, "B-1-1", ev)[0] == "sold"
    assert hold_status(db, h) == "converted"


def test_seat_held_by_another_hold_is_untouched(db):
    ev = make_event(db)
    old, new = make_hold(db, ev), make_hold(db, ev)
    make_seat(db, ev, "C-1-1", "held", new)  # someone else holds it now
    assert release_hold.release(old)["released_seats"] == []
    assert seat_status(db, "C-1-1", ev) == ["held", new]


def test_release_twice_is_harmless(db):
    ev = make_event(db)
    h = make_hold(db, ev)
    make_seat(db, ev, "D-1-1", "held", h)
    assert release_hold.release(h)["released_seats"] == ["D-1-1"]
    assert release_hold.release(h) == {"hold_id": h, "released_seats": [], "hold_was_active": False}


def test_handler_publishes_only_when_something_was_released(db, monkeypatch):
    sent = []
    monkeypatch.setattr(release_hold, "publish", lambda ev, data: sent.append((ev, data)))
    ev = make_event(db)
    h = make_hold(db, ev)
    make_seat(db, ev, "E-1-1", "held", h)
    release_hold.handler({"hold_id": h, "event_id": ev}, None)
    release_hold.handler({"hold_id": h, "event_id": ev}, None)  # retry: nothing more
    assert [d["released_seats"] for _, d in sent] == [["E-1-1"]]


def test_release_locks_the_hold_row_before_the_seats(db):
    """Lock order = hold, then seats (same as the order worker): while another transaction
    holds the hold row, the release waits instead of touching any seat."""
    import threading

    ev = make_event(db)
    h = make_hold(db, ev)
    make_seat(db, ev, "F-1-1", "held", h)
    blocker = connect()
    blocker.run("BEGIN")
    blocker.run("SELECT id FROM holds WHERE id = CAST(:h AS uuid) FOR UPDATE", h=h)
    out = {}
    t = threading.Thread(target=lambda: out.update(release_hold.release(h)))
    t.start()
    t.join(timeout=1.5)
    assert t.is_alive()  # waiting on the hold lock
    assert seat_status(db, "F-1-1", ev)[0] == "held"
    blocker.run("ROLLBACK")
    blocker.close()
    t.join(timeout=10)
    assert out["released_seats"] == ["F-1-1"]
