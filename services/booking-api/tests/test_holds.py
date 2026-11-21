"""Hold endpoint: the conditional UPDATE, all-or-nothing, per-buyer limit, sale window."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from tests.helpers import buyer, organiser
from tests.test_organiser import create, upload

pytestmark = pytest.mark.integration

TEN_SEATS = "section,row,number,zone,price_inr\n" + "".join(
    f"A,1,{n},gold,1000\n" for n in range(1, 11)
)


def open_event(api, per_buyer_limit=4, csv=TEN_SEATS, **times):
    """An event whose sale is open now (unless times say otherwise), with seats."""
    now = datetime.now(UTC)
    body = {
        "sale_starts_at": (now - timedelta(minutes=5)).isoformat(),
        "starts_at": (now + timedelta(days=1)).isoformat(),
        "per_buyer_limit": per_buyer_limit,
    } | {k: v.isoformat() for k, v in times.items()}
    org = organiser()
    ev = create(api, org, **body)
    assert upload(api, org, ev["id"], csv).status_code == 200
    seat_ids = [
        s["id"] for s in api.get(f"/book/{ev['id']}/seats", headers=buyer()).json()["seats"]
    ]
    return ev["id"], seat_ids


def hold(api, event_id, seat_ids, headers=None):
    return api.post(
        f"/book/{event_id}/holds", json={"seat_ids": seat_ids}, headers=headers or buyer()
    )


def statuses(api, event_id):
    return {
        s["id"]: s["status"]
        for s in api.get(f"/book/{event_id}/seats", headers=buyer()).json()["seats"]
    }


def test_hold_two_seats(api):
    event_id, seats = open_event(api)
    r = hold(api, event_id, seats[:2])
    assert r.status_code == 201, r.text
    body = r.json()
    assert {s["id"] for s in body["seats"]} == set(seats[:2])
    assert body["amount_paise"] == 2 * 100000
    expires = datetime.fromisoformat(body["expires_at"])
    assert timedelta(minutes=9) < expires - datetime.now(UTC) <= timedelta(minutes=10)
    st = statuses(api, event_id)  # cache invalidated: the change is visible at once
    assert [st[s] for s in seats[:3]] == ["held", "held", "available"]


def test_taken_seat_fails_and_nothing_is_partly_held(api):
    event_id, seats = open_event(api)
    assert hold(api, event_id, [seats[0]]).status_code == 201
    r = hold(api, event_id, [seats[1], seats[0]])  # one free, one taken
    assert r.status_code == 409
    assert r.json() == {"detail": "someone just took that seat", "unavailable": [seats[0]]}
    assert statuses(api, event_id)[seats[1]] == "available"  # rolled back, not half-held


def test_per_buyer_limit_counts_existing_holds(api):
    event_id, seats = open_event(api, per_buyer_limit=4)
    me = buyer("buyer-limit")
    assert hold(api, event_id, seats[:3], me).status_code == 201
    r = hold(api, event_id, seats[3:5], me)
    assert r.status_code == 409
    assert r.json()["detail"] == "per-buyer limit is 4; you already hold 3"
    assert hold(api, event_id, seats[3:4], me).status_code == 201  # exactly at the limit
    assert hold(api, event_id, seats[5:6], buyer()).status_code == 201  # others unaffected


def test_expired_holds_do_not_count_towards_the_limit(api, migrated_engine):
    event_id, seats = open_event(api, per_buyer_limit=2)
    me = buyer("buyer-expired")
    assert hold(api, event_id, seats[:2], me).status_code == 201
    with migrated_engine.begin() as conn:
        conn.execute(
            text("UPDATE holds SET expires_at = now() - interval '1 second' WHERE event_id = :e"),
            {"e": event_id},
        )
    assert hold(api, event_id, seats[2:4], me).status_code == 201


def test_more_seats_than_the_limit_in_one_request_is_422(api):
    event_id, seats = open_event(api, per_buyer_limit=2)
    r = hold(api, event_id, seats[:3])
    assert r.status_code == 422
    assert r.json()["detail"] == "at most 2 seats per buyer"


@pytest.mark.parametrize("seat_ids", [[], "dup"], ids=["empty", "duplicates"])
def test_bad_requests_are_422(api, seat_ids):
    event_id, seats = open_event(api)
    ids = [seats[0], seats[0]] if seat_ids == "dup" else seat_ids
    assert hold(api, event_id, ids).status_code == 422


def test_seat_of_another_event_cannot_be_held(api):
    event_a, _ = open_event(api)
    _, seats_b = open_event(api)
    r = hold(api, event_a, [seats_b[0]])
    assert r.status_code == 409
    assert r.json()["unavailable"] == [seats_b[0]]


def test_sale_window(api):
    now = datetime.now(UTC)
    early, seats = open_event(
        api, sale_starts_at=now + timedelta(hours=1), starts_at=now + timedelta(days=1)
    )
    r = hold(api, early, seats[:1])
    assert r.status_code == 409
    assert r.json()["detail"] == "the sale has not started yet"
    late, seats = open_event(
        api, sale_starts_at=now - timedelta(days=2), starts_at=now - timedelta(hours=1)
    )
    assert hold(api, late, seats[:1]).json()["detail"] == "the event has already started"


def test_unknown_event_is_404(api):
    assert hold(api, uuid.uuid4(), [str(uuid.uuid4())]).status_code == 404


def test_only_buyers_can_hold(api):
    event_id, seats = open_event(api)
    assert hold(api, event_id, seats[:1], organiser()).status_code == 403
    assert api.post(f"/book/{event_id}/holds", json={"seat_ids": seats[:1]}).status_code == 401
