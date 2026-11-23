"""Every /book/{event}/... route needs a valid booking pass (the waiting room let you in).

Routes are discovered from the app (like the cross-tenant test), so a /book route added later
is covered automatically; a route without a recipe makes the test fail on purpose.
"""

import json
import uuid

import pytest
from tests.helpers import PASS_KEY, admitted_buyer, buyer, make_pass
from tests.test_holds import open_event

from app.main import app

pytestmark = pytest.mark.integration


def _order(api, event_id, seats, sub):
    """An order needs a hold of the same buyer (made with the pass check off) and a key."""
    from tests.test_orders import FakeProvider

    from app.payments import get_provider

    app.dependency_overrides[get_provider] = lambda: FakeProvider()
    r = api.post(
        f"/book/{event_id}/holds",
        json={"seat_ids": seats[1:2]},
        headers=admitted_buyer(event_id, sub),
    )
    assert r.status_code == 201, r.text
    return {
        "json": {"hold_id": r.json()["hold_id"]},
        "headers": {"Idempotency-Key": str(uuid.uuid4())},
    }


# (api, event_id, seats, sub) -> request kwargs (json, extra headers)
RECIPES = {
    ("GET", "/book/{event_id}/seats"): lambda api, ev, seats, sub: {},
    ("POST", "/book/{event_id}/holds"): lambda api, ev, seats, sub: {
        "json": {"seat_ids": seats[:1]}
    },
    ("POST", "/book/{event_id}/orders"): _order,
}


def book_routes():
    routes = sorted(
        (method.upper(), path)
        for path, ops in app.openapi()["paths"].items()
        if path.startswith("/book/") and "{event_id}" in path
        for method in ops
    )
    assert routes, "no /book routes found: discovery is broken"
    return routes


@pytest.fixture
def passes_on(api, monkeypatch):
    monkeypatch.setenv("BOOKING_PASS_REQUIRED", "true")
    monkeypatch.setenv("BOOKING_PASS_KEY_JSON", json.dumps(PASS_KEY))
    return api


def test_every_book_route_has_a_recipe():
    assert not set(book_routes()) - set(RECIPES)


def bad_passes(event_id, sub):
    other_key = {"kid": PASS_KEY["kid"], "key": "attacker"}
    return {
        "missing": None,
        "garbage": "not-a-pass",
        "forged": make_pass(sub, event_id, key=other_key),
        "expired": make_pass(sub, event_id, ttl=-1),
        "other event": make_pass(sub, uuid.uuid4()),
        "other user": make_pass("someone-else", event_id),
        "queue token instead": make_pass(sub, event_id, typ="queue"),
    }


@pytest.mark.parametrize(("method", "path"), book_routes())
def test_no_valid_pass_no_booking(passes_on, method, path):
    api = passes_on
    event_id, seats = open_event(api)  # (open_event reads seats with the check still off)
    url = path.replace("{event_id}", event_id)
    sub = f"buyer-{uuid.uuid4()}"
    request = RECIPES[(method, path)](api, event_id, seats, sub)
    extra = request.pop("headers", {})
    for name, bad in bad_passes(event_id, sub).items():
        headers = buyer(sub) | extra | ({"X-Booking-Pass": bad} if bad else {})
        r = api.request(method, url, headers=headers, **request)
        assert r.status_code == 403, f"{method} {path} with {name} pass -> {r.status_code}"
        assert r.json()["detail"]["queue"] == f"/queue/{event_id}/join"
    # ...and with a genuine pass of the same buyer it works
    ok = api.request(method, url, headers=admitted_buyer(event_id, sub) | extra, **request)
    assert ok.status_code < 300, ok.text


def test_refusal_says_why(passes_on):
    event_id, _ = open_event(passes_on)
    sub = "b-why"
    r = passes_on.get(
        f"/book/{event_id}/seats",
        headers=buyer(sub) | {"X-Booking-Pass": make_pass(sub, event_id, ttl=-5)},
    )
    assert r.json()["detail"]["reason"] == "booking pass refused: pass expired"
