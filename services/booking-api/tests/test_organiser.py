"""Organiser endpoints against PostgreSQL: create, list, upload seat map, tenant scoping."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from tests.helpers import buyer, organiser

pytestmark = pytest.mark.integration

SEATS_CSV = (
    "section,row,number,zone,price_inr\n"
    "A,1,1,gold,1500\nA,1,2,gold,1500\nA,1,3,gold,1500\n"
    "B,1,1,silver,750\nB,1,2,silver,750\n"
)


def event_body(**overrides):
    now = datetime.now(UTC)
    return {
        "name": "Fest Night",
        "venue": "Main Ground",
        "starts_at": (now + timedelta(days=10)).isoformat(),
        "sale_starts_at": (now + timedelta(days=1)).isoformat(),
        "per_buyer_limit": 4,
    } | overrides


def create(api, headers, **overrides):
    r = api.post("/org/events", json=event_body(**overrides), headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def upload(api, headers, event_id, body=SEATS_CSV):
    return api.put(
        f"/org/events/{event_id}/seats",
        content=body.encode(),
        headers=headers | {"Content-Type": "text/csv"},
    )


def test_create_and_list_events(api):
    org = organiser()
    ev = create(api, org)
    assert ev["status"] == "draft"
    assert ev["seat_count"] == 0
    listed = api.get("/org/events", headers=org).json()
    assert [e["id"] for e in listed] == [ev["id"]]


def test_upload_seat_map_and_summary(api):
    org = organiser()
    ev = create(api, org)
    r = upload(api, org, ev["id"])
    assert r.status_code == 200, r.text
    assert r.json()["seat_count"] == 5
    assert r.json()["zones"] == [
        {"zone": "gold", "price_paise": 150000, "seats": 3},
        {"zone": "silver", "price_paise": 75000, "seats": 2},
    ]
    assert api.get(f"/org/events/{ev['id']}", headers=org).json()["seat_count"] == 5


def test_reupload_replaces_the_map(api):
    org = organiser()
    ev = create(api, org)
    upload(api, org, ev["id"])
    r = upload(api, org, ev["id"], "section,row,number,zone,price_inr\nC,1,1,gold,100\n")
    assert r.json()["seat_count"] == 1
    assert api.get(f"/org/events/{ev['id']}", headers=org).json()["seat_count"] == 1


def test_reupload_refused_once_a_seat_is_held(api, migrated_engine):
    org = organiser()
    ev = create(api, org)
    upload(api, org, ev["id"])
    hold = uuid.uuid4()
    with migrated_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO holds (id, event_id, buyer_id, seat_count, expires_at) "
                "VALUES (:h, :e, 'b', 1, now() + interval '10 minutes')"
            ),
            {"h": hold, "e": ev["id"]},
        )
        conn.execute(
            text(
                "UPDATE seats SET status = 'held', hold_id = :h, "
                "held_until = now() + interval '10 minutes' "
                "WHERE id = (SELECT id FROM seats WHERE event_id = :e LIMIT 1)"
            ),
            {"h": hold, "e": ev["id"]},
        )
    r = upload(api, org, ev["id"])
    assert r.status_code == 409
    assert "held or sold" in r.json()["detail"]


def test_invalid_csv_is_422_with_reason(api):
    org = organiser()
    ev = create(api, org)
    bad = "section,row,number,zone,price_inr\nA,1,1,gold,10\nA,1,1,gold,10\n"
    r = upload(api, org, ev["id"], bad)
    assert r.status_code == 422
    assert "appears twice" in r.json()["detail"]


def test_wrong_content_type_is_415(api):
    org = organiser()
    ev = create(api, org)
    r = api.put(f"/org/events/{ev['id']}/seats", json={"x": 1}, headers=org)
    assert r.status_code == 415


def test_sale_must_start_before_the_event(api):
    late = (datetime.now(UTC) + timedelta(days=11)).isoformat()
    r = api.post("/org/events", json=event_body(sale_starts_at=late), headers=organiser())
    assert r.status_code == 422


def test_per_buyer_limit_range(api):
    r = api.post("/org/events", json=event_body(per_buyer_limit=11), headers=organiser())
    assert r.status_code == 422


def test_buyer_and_anonymous_cannot_use_organiser_endpoints(api):
    assert api.get("/org/events", headers=buyer()).status_code == 403
    assert api.get("/org/events").status_code == 401
    assert api.post("/org/events", json=event_body(), headers=buyer()).status_code == 403


# --- tenant isolation (extended in Day 4 Task 4) ---------------------------------------------


def test_tenant_comes_from_the_token_not_the_body(api):
    r = api.post("/org/events", json=event_body(tenant_id=str(uuid.uuid4())), headers=organiser())
    assert r.status_code == 422  # unknown field refused, never silently used


def test_organiser_b_cannot_see_or_change_organiser_a_events(api):
    org_a, org_b = organiser(), organiser()
    ev = create(api, org_a)
    upload(api, org_a, ev["id"])
    assert api.get("/org/events", headers=org_b).json() == []
    assert api.get(f"/org/events/{ev['id']}", headers=org_b).status_code == 404
    assert upload(api, org_b, ev["id"]).status_code == 404
    assert api.get(f"/org/events/{ev['id']}", headers=org_a).json()["seat_count"] == 5


def test_two_organisers_of_the_same_tenant_share_events(api):
    tenant = uuid.uuid4()
    ev = create(api, organiser(tenant))
    listed = api.get("/org/events", headers=organiser(tenant)).json()
    assert [e["id"] for e in listed] == [ev["id"]]
