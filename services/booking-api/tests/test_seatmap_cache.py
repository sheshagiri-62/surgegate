"""Buyer seat map: Redis cache, invalidation on change, stampede protection, Redis-down fallback."""

import os
import time
import uuid

import pytest
import redis
from sqlalchemy import text
from tests.helpers import buyer, organiser
from tests.test_organiser import SEATS_CSV, create, upload

from app import cache

pytestmark = pytest.mark.integration
needs_redis = pytest.mark.skipif(not os.getenv("REDIS_URL"), reason="needs REDIS_URL")


def event_with_seats(api):
    org = organiser()
    ev = create(api, org)
    assert upload(api, org, ev["id"]).status_code == 200
    return org, ev["id"]


def seats(api, event_id, headers=None):
    r = api.get(f"/book/{event_id}/seats", headers=headers or buyer())
    assert r.status_code == 200, r.text
    return r


def test_seat_map_lists_every_seat_with_status(api):
    _, event_id = event_with_seats(api)
    body = seats(api, event_id).json()
    assert body["event"]["id"] == event_id
    assert [s["label"] for s in body["seats"]] == ["A-1-1", "A-1-2", "A-1-3", "B-1-1", "B-1-2"]
    assert {s["status"] for s in body["seats"]} == {"available"}


def test_unknown_event_is_404_and_anonymous_is_401(api):
    assert api.get(f"/book/{uuid.uuid4()}/seats", headers=buyer()).status_code == 404
    assert api.get(f"/book/{uuid.uuid4()}/seats").status_code == 401


@needs_redis
def test_second_read_is_served_from_redis(api):
    _, event_id = event_with_seats(api)
    assert seats(api, event_id).headers["X-Cache"] == "miss"
    assert seats(api, event_id).headers["X-Cache"] == "hit"
    ttl = cache.get_redis().ttl(f"seatmap:{event_id}")
    assert 0 < ttl <= cache.FRESH_TTL_SECONDS


@needs_redis
def test_upload_invalidates_the_cache(api):
    org, event_id = event_with_seats(api)
    seats(api, event_id)
    assert seats(api, event_id).headers["X-Cache"] == "hit"
    one_seat = "section,row,number,zone,price_inr\nZ,1,1,gold,100\n"
    assert upload(api, org, event_id, one_seat).status_code == 200
    r = seats(api, event_id)
    assert r.headers["X-Cache"] == "miss"
    assert [s["label"] for s in r.json()["seats"]] == ["Z-1-1"]


@needs_redis
def test_changes_made_elsewhere_show_within_the_ttl(api, migrated_engine):
    """E.g. the hold-release timer (Day 7) changes seats without calling invalidate."""
    _, event_id = event_with_seats(api)
    seats(api, event_id)
    hold = uuid.uuid4()
    with migrated_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO holds (id, event_id, buyer_id, seat_count, expires_at) "
                "VALUES (:h, :e, 'b', 5, now() + interval '10 minutes')"
            ),
            {"h": hold, "e": event_id},
        )
        conn.execute(
            text(
                "UPDATE seats SET status = 'held', hold_id = :h, "
                "held_until = now() + interval '10 minutes' WHERE event_id = :e"
            ),
            {"h": hold, "e": event_id},
        )
    time.sleep(cache.FRESH_TTL_SECONDS + 0.5)
    assert {s["status"] for s in seats(api, event_id).json()["seats"]} == {"held"}


@needs_redis
def test_only_one_request_rebuilds_others_get_the_stale_copy(api):
    _, event_id = event_with_seats(api)
    seats(api, event_id)  # fills fresh + stale
    r = cache.get_redis()
    r.delete(f"seatmap:{event_id}")  # fresh copy gone...
    r.set(f"seatmap:{event_id}:lock", "1", ex=2)  # ...and someone else is rebuilding
    assert seats(api, event_id).headers["X-Cache"] == "stale"


def test_redis_down_falls_back_to_postgres(api, monkeypatch):
    _, event_id = event_with_seats(api)
    dead = redis.Redis(host="127.0.0.1", port=1, socket_timeout=0.2, socket_connect_timeout=0.2)
    monkeypatch.setattr(cache, "get_redis", lambda: dead)
    r = seats(api, event_id)
    assert r.headers["X-Cache"] == "db"
    assert len(r.json()["seats"]) == 5
    assert upload(api, organiser(), event_id, SEATS_CSV).status_code == 404  # other tenant
