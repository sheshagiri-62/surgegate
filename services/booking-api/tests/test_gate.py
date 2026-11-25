"""Gate check-in (each ticket once) and the attendee export (Day 8 Task 4)."""

import base64
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from tests.helpers import buyer, organiser
from tests.test_holds import TEN_SEATS, hold
from tests.test_orders import order
from tests.test_organiser import create, upload
from tests.test_payment_flow import drain, flow, post, webhook_body  # noqa: F401

from app import ticket_token
from app.routes import gate

pytestmark = pytest.mark.integration

KEY = {"kid": "t1", "key": "g" * 40}


@pytest.fixture
def paid(flow, monkeypatch):  # noqa: F811
    """A paid order of 2 seats with its 2 tickets, and the organiser who owns the event."""
    monkeypatch.setenv("TICKET_KEY_JSON", json.dumps(KEY))
    org = organiser()
    now = datetime.now(UTC)
    ev = create(
        flow.api,
        org,
        sale_starts_at=(now - timedelta(minutes=5)).isoformat(),
        starts_at=(now + timedelta(days=1)).isoformat(),
    )
    assert upload(flow.api, org, ev["id"], TEN_SEATS).status_code == 200
    from tests.helpers import admitted_buyer

    seats = [
        s["id"]
        for s in flow.api.get(f"/book/{ev['id']}/seats", headers=admitted_buyer(ev["id"])).json()[
            "seats"
        ]
    ]
    b = buyer(email="fan@example.test")  # email claim -> stored on the order
    h = hold(flow.api, ev["id"], seats[:2], b).json()
    o = order(flow.api, ev["id"], b, h["hold_id"]).json()
    post(flow, webhook_body(o))
    drain(flow)
    with flow.engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO tickets (id, order_item_id, order_id, event_id, seat_id, kid) "
                "SELECT gen_random_uuid(), i.id, i.order_id, :e, i.seat_id, 't1' "
                "FROM order_items i "
                "WHERE i.order_id = :o"
            ),
            {"e": ev["id"], "o": o["order_id"]},
        )
        tickets = c.execute(
            text(
                "SELECT t.id::text, s.label, s.id::text FROM tickets t "
                "JOIN seats s ON s.id = t.seat_id "
                "WHERE t.order_id = :o ORDER BY s.label"
            ),
            {"o": o["order_id"]},
        ).all()
    tokens = [
        ticket_token.sign(
            {
                "typ": "ticket",
                "tid": tid,
                "ord": o["order_id"],
                "ev": ev["id"],
                "seat": {"id": sid, "label": label},
                "iat": 1,
            },
            KEY,
        )
        for tid, label, sid in tickets
    ]
    return flow, org, ev["id"], o, tokens


def scan(api, org, ev, token):
    return api.post(f"/org/events/{ev}/check-in", json={"token": token}, headers=org)


def test_first_scan_admits_second_scan_is_refused(paid):
    f, org, ev, _, tokens = paid
    first = scan(f.api, org, ev, tokens[0])
    assert first.status_code == 200 and first.json()["result"] == "admitted"
    assert first.json()["seat"] == "A-1-1"
    again = scan(f.api, org, ev, tokens[0])  # a screenshot of the same QR
    assert again.status_code == 409 and again.json()["result"] == "already used"
    assert again.json()["used_at"] == first.json()["used_at"]
    assert scan(f.api, org, ev, tokens[1]).status_code == 200  # the other seat still works


def test_forged_and_wrong_event_tokens_are_refused(paid):
    f, org, ev, o, tokens = paid
    claims = json.loads(base64.urlsafe_b64decode(tokens[0].split(".")[0] + "=="))
    forged = ticket_token.sign(claims, {"kid": "t1", "key": "attacker"})
    r = scan(f.api, org, ev, forged)
    assert r.status_code == 400 and "forged" in r.json()["reason"]
    other = create(f.api, org)  # same organiser, another event
    assert scan(f.api, org, other["id"], tokens[0]).status_code == 400  # "another event"
    unknown = ticket_token.sign(
        {
            "typ": "ticket",
            "tid": str(uuid.uuid4()),
            "ord": o["order_id"],
            "ev": ev,
            "seat": {},
            "iat": 1,
        },
        KEY,
    )
    assert scan(f.api, org, ev, unknown).status_code == 404


def test_refunded_order_does_not_get_in(paid):
    f, org, ev, o, tokens = paid
    with f.engine.begin() as c:
        c.execute(text("UPDATE orders SET status = 'refunded' WHERE id = :o"), {"o": o["order_id"]})
    r = scan(f.api, org, ev, tokens[0])
    assert r.status_code == 409 and "refunded" in r.json()["reason"]


def test_another_organiser_cannot_check_in(paid):
    f, _, ev, _, tokens = paid
    assert scan(f.api, organiser(), ev, tokens[0]).status_code == 404


def test_attendee_export(paid, monkeypatch):
    f, org, ev, o, tokens = paid
    scan(f.api, org, ev, tokens[0])
    r = f.api.get(f"/org/events/{ev}/attendees.csv", headers=org)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    lines = r.text.strip().splitlines()
    assert lines[0] == "seat,order_id,buyer_email,paid_at,ticket_id,checked_in_at"
    rows = [line.split(",") for line in lines[1:]]
    assert [x[0] for x in rows] == ["A-1-1", "A-1-2"]
    assert all(x[1] == o["order_id"] and x[2] == "fan@example.test" for x in rows)
    assert rows[0][5] and not rows[1][5]  # A-1-1 checked in, A-1-2 not yet


def test_export_escapes_formula_cells(paid):
    """CSV injection: a buyer email like =HYPERLINK(...) must not run as a formula."""
    f, org, ev, o, _ = paid
    with f.engine.begin() as c:
        c.execute(
            text("UPDATE orders SET buyer_email = :e WHERE id = :o"),
            {"e": '=HYPERLINK("http://evil.test","x")@example.test', "o": o["order_id"]},
        )
    r = f.api.get(f"/org/events/{ev}/attendees.csv", headers=org)
    assert "'=HYPERLINK" in r.text and ",=HYPERLINK" not in r.text


@pytest.mark.parametrize(
    ("raw", "out"),
    [
        ("=1+1", "'=1+1"),
        ("+91", "'+91"),
        ("-2", "'-2"),
        ("@SUM(A1)", "'@SUM(A1)"),
        ("\tx", "'\tx"),
        ("a@b.test", "a@b.test"),
        ("", ""),
        (None, ""),
    ],
)
def test_csv_safe(raw, out):
    assert gate.csv_safe(raw) == out
