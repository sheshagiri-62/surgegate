"""Concurrency: no seat is ever held twice (plan: "200 parallel requests for the same 10 seats;
assert exactly 10 holds succeed").

A real HTTP server (uvicorn, in a background thread, with a 60-connection database pool) serves
the real app; 200 client threads wait at a barrier and then fire at the same moment, so
PostgreSQL sees genuinely competing transactions. The database is checked afterwards, not just
the HTTP answers.
"""

import json
import os
import random
import socket
import threading
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import uvicorn
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from tests.helpers import PASS_KEY, SETTINGS, FakeJwks, admitted_buyer, organiser

pytestmark = pytest.mark.integration

PARALLEL = 200


@pytest.fixture(scope="module")
def server(migrated_engine):
    """The real app on a free local port, backed by the test database."""

    from app import auth, db
    from app.main import app

    engine = db.make_engine(os.environ["DATABASE_URL"], pool_size=60, max_overflow=0)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def session():
        s = factory()
        try:
            yield s
        finally:
            s.close()

    # The race runs the production path: every buyer carries a booking pass.
    saved_env = {k: os.environ.get(k) for k in ("BOOKING_PASS_REQUIRED", "BOOKING_PASS_KEY_JSON")}
    os.environ["BOOKING_PASS_REQUIRED"] = "true"  # noqa: S105 - a feature flag, not a secret
    os.environ["BOOKING_PASS_KEY_JSON"] = json.dumps(PASS_KEY)
    original_jwks = auth._jwks_client
    auth._jwks_client = lambda url: FakeJwks()
    app.dependency_overrides[auth.get_auth_settings] = lambda: SETTINGS
    app.dependency_overrides[db.get_session] = session

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    while not srv.started:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    thread.join(timeout=10)
    app.dependency_overrides.clear()
    auth._jwks_client = original_jwks
    for k, v in saved_env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    engine.dispose()


def make_event(base, seats=10, per_buyer_limit=4):
    org = organiser()
    now = datetime.now(UTC)
    with httpx.Client(base_url=base, timeout=30) as c:
        ev = c.post(
            "/org/events",
            headers=org,
            json={
                "name": "Race",
                "venue": "Arena",
                "sale_starts_at": (now - timedelta(minutes=1)).isoformat(),
                "starts_at": (now + timedelta(days=1)).isoformat(),
                "per_buyer_limit": per_buyer_limit,
            },
        ).json()
        csv = "section,row,number,zone,price_inr\n" + "".join(
            f"A,1,{n},gold,500\n" for n in range(1, seats + 1)
        )
        r = c.put(
            f"/org/events/{ev['id']}/seats",
            content=csv.encode(),
            headers=org | {"Content-Type": "text/csv"},
        )
        assert r.status_code == 200, r.text
        seat_ids = [
            s["id"]
            for s in c.get(f"/book/{ev['id']}/seats", headers=admitted_buyer(ev["id"])).json()[
                "seats"
            ]
        ]
    return ev["id"], seat_ids


def fire(base, event_id, requests):
    """requests: list of (headers, seat_ids). All are released together by a barrier."""
    barrier = threading.Barrier(len(requests))
    # One thread-safe client with a connection per request (building 200 clients is slow).
    limits = httpx.Limits(max_connections=len(requests), max_keepalive_connections=len(requests))

    with httpx.Client(base_url=base, timeout=60, limits=limits) as c:

        def one(req):
            headers, seat_ids = req
            barrier.wait()
            r = c.post(f"/book/{event_id}/holds", json={"seat_ids": seat_ids}, headers=headers)
            return r.status_code, r.json(), seat_ids

        with ThreadPoolExecutor(max_workers=len(requests)) as pool:
            return list(pool.map(one, requests))


def db_view(engine, event_id):
    with engine.connect() as conn:
        seats = conn.execute(
            text("SELECT id::text, status, hold_id::text FROM seats WHERE event_id = :e"),
            {"e": event_id},
        ).all()
        holds = conn.execute(
            text("SELECT id::text, seat_count FROM holds WHERE event_id = :e"), {"e": event_id}
        ).all()
    return seats, holds


def test_200_parallel_requests_for_the_same_10_seats_exactly_10_succeed(server, migrated_engine):
    event_id, seat_ids = make_event(server, seats=10)
    # 200 different buyers; buyer i wants seat i % 10, so 20 buyers fight for every seat.
    requests = [(admitted_buyer(event_id), [seat_ids[i % 10]]) for i in range(PARALLEL)]
    results = fire(server, event_id, requests)

    codes = Counter(code for code, _, _ in results)
    assert codes == {201: 10, 409: 190}, codes  # no 5xx, no timeouts
    won = Counter(seats[0] for code, _, seats in results if code == 201)
    assert won == {s: 1 for s in seat_ids}  # every seat won exactly once
    losers = [body for code, body, _ in results if code == 409]
    assert {b["detail"] for b in losers} == {"someone just took that seat"}

    seats, holds = db_view(migrated_engine, event_id)
    assert {status for _, status, _ in seats} == {"held"}
    assert len({hold_id for _, _, hold_id in seats}) == 10  # 10 different holds
    assert len(holds) == 10  # losers' hold rows were rolled back


def test_overlapping_multi_seat_holds_never_deadlock_or_double_book(server, migrated_engine):
    event_id, seat_ids = make_event(server, seats=10)
    rng = random.Random(42)  # noqa: S311 - shuffling test data, not crypto
    requests = []
    for i in range(PARALLEL):
        pair = [seat_ids[i % 10], seat_ids[(i + 1) % 10]]
        rng.shuffle(pair)  # different lock order in different requests
        requests.append((admitted_buyer(event_id), pair))
    results = fire(server, event_id, requests)

    assert all(code in (201, 409) for code, _, _ in results), Counter(c for c, _, _ in results)
    seats, holds = db_view(migrated_engine, event_id)
    held = [s for s in seats if s[1] == "held"]
    winners = [set(s) for code, _, s in results if code == 201]
    assert sum(len(w) for w in winners) == len(held)  # every success fully applied
    flat = [s for w in winners for s in w]
    assert len(flat) == len(set(flat))  # no seat in two successful holds
    assert len(holds) == len(winners)
    per_hold = Counter(hold_id for _, status, hold_id in seats if status == "held")
    assert set(per_hold.values()) == {2}  # all or nothing: each hold has both its seats


def test_one_buyer_racing_themselves_cannot_beat_the_limit(server, migrated_engine):
    event_id, seat_ids = make_event(server, seats=20, per_buyer_limit=4)
    me = admitted_buyer(event_id, f"greedy-{uuid.uuid4()}")
    results = fire(server, event_id, [(me, [s]) for s in seat_ids])
    codes = Counter(code for code, _, _ in results)
    assert codes == {201: 4, 409: 16}, codes
    seats, _ = db_view(migrated_engine, event_id)
    assert sum(1 for _, status, _ in seats if status == "held") == 4
