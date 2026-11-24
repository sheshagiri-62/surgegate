"""Orders: idempotency per buyer, one live order per hold, hold checks (Day 7 Task 3)."""

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from tests.helpers import buyer
from tests.test_holds import hold, open_event

from app.orders import create_order
from app.payments import ProviderError, ProviderOrder, get_provider

pytestmark = pytest.mark.integration


class FakeProvider:
    name = "mock"

    def __init__(self):
        self.calls, self.fail = [], False
        self._lock = threading.Lock()

    def create_order(self, amount_paise, currency, receipt, notes):
        if self.fail:
            raise ProviderError("down")
        with self._lock:
            self.calls.append({"amount": amount_paise, "receipt": receipt, "notes": notes})
        oid = f"order_{uuid.uuid4().hex[:14]}"  # unique across tests (the database is shared)
        return ProviderOrder(id=oid, checkout=self.checkout(oid))

    def checkout(self, provider_order_id):
        return {"type": "redirect", "url": f"https://pay.test/mockpay/checkout/{provider_order_id}"}

    def verify_webhook_signature(self, raw_body, signature):
        return False

    def refund(self, payment_id, amount_paise):
        return "rfnd_test"


@pytest.fixture
def provider(api, monkeypatch):
    from app.main import app

    monkeypatch.setenv("ORDER_RETURN_ORIGINS", "http://localhost:3000")
    fake = FakeProvider()
    app.dependency_overrides[get_provider] = lambda: fake
    return fake


def held(api, n=2):
    """(event_id, buyer headers, hold json) for a fresh event and buyer."""
    event_id, seats = open_event(api)
    headers = buyer()
    r = hold(api, event_id, seats[:n], headers)
    assert r.status_code == 201
    return event_id, headers, r.json()


def order(api, event_id, headers, hold_id, key=None, **body):
    return api.post(
        f"/book/{event_id}/orders",
        json={"hold_id": hold_id, **body},
        headers=headers | {"Idempotency-Key": str(key or uuid.uuid4())},
    )


def test_order_for_a_hold_amount_from_the_database(api, provider):
    event_id, headers, h = held(api)
    r = order(api, event_id, headers, h["hold_id"], return_url="http://localhost:3000/order/")
    assert r.status_code == 201, r.text
    o = r.json()
    assert o["status"] == "pending" and o["amount_paise"] == h["amount_paise"] == 200000
    assert sorted(o["seats"]) == sorted(s["label"] for s in h["seats"])
    assert o["checkout"]["type"] == "redirect" and o["provider_order_id"].startswith("order_")
    (call,) = provider.calls
    assert call["receipt"] == o["order_id"] and call["amount"] == 200000
    assert call["notes"]["callback_url"] == f"http://localhost:3000/order/?id={o['order_id']}"


def test_same_key_returns_the_same_order(api, provider):
    event_id, headers, h = held(api)
    key = uuid.uuid4()
    first = order(api, event_id, headers, h["hold_id"], key)
    again = order(api, event_id, headers, h["hold_id"], key)
    assert (first.status_code, again.status_code) == (201, 200)
    assert first.json()["order_id"] == again.json()["order_id"]
    assert len(provider.calls) == 1  # one provider order, not two


def test_key_reused_for_another_hold_is_refused(api, provider):
    event_id, seats = open_event(api)
    headers = buyer()
    h1 = hold(api, event_id, seats[:1], headers).json()
    h2 = hold(api, event_id, seats[1:2], headers).json()
    key = uuid.uuid4()
    assert order(api, event_id, headers, h1["hold_id"], key).status_code == 201
    r = order(api, event_id, headers, h2["hold_id"], key)
    assert r.status_code == 422 and "another hold" in r.json()["detail"]


def test_keys_are_per_buyer(api, provider):
    """Another buyer using the same key value gets their own order (no clash, no leak)."""
    key = uuid.uuid4()
    a = held(api)
    b = held(api)
    ra = order(api, a[0], a[1], a[2]["hold_id"], key)
    rb = order(api, b[0], b[1], b[2]["hold_id"], key)
    assert (ra.status_code, rb.status_code) == (201, 201)
    assert ra.json()["order_id"] != rb.json()["order_id"]


def test_second_key_for_the_same_hold_gets_the_live_order(api, provider):
    event_id, headers, h = held(api)
    first = order(api, event_id, headers, h["hold_id"])
    second = order(api, event_id, headers, h["hold_id"])  # e.g. a second browser tab
    assert second.status_code == 200 and second.json()["order_id"] == first.json()["order_id"]


def test_someone_elses_hold_is_not_found(api, provider):
    event_id, _, h = held(api)
    r = order(api, event_id, buyer(), h["hold_id"])
    assert r.status_code == 404


def test_hold_for_another_event_is_not_found(api, provider):
    event_id, headers, h = held(api)
    other, _ = open_event(api)
    assert order(api, other, headers, h["hold_id"]).status_code == 404


def test_less_than_60_seconds_left_is_refused(api, provider, migrated_engine):
    event_id, headers, h = held(api)
    with migrated_engine.begin() as conn:
        conn.execute(
            text("UPDATE holds SET expires_at = now() + interval '30 seconds' WHERE id = :h"),
            {"h": h["hold_id"]},
        )
    r = order(api, event_id, headers, h["hold_id"])
    assert r.status_code == 409 and "60 seconds" in r.json()["detail"]
    assert 0 <= r.json()["seconds_left"] <= 30
    assert provider.calls == []


def test_released_hold_is_refused(api, provider, migrated_engine):
    event_id, headers, h = held(api)
    with migrated_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE seats SET status='available', hold_id=NULL, held_until=NULL "
                "WHERE hold_id=:h"
            ),
            {"h": h["hold_id"]},
        )
        conn.execute(text("UPDATE holds SET status='released' WHERE id=:h"), {"h": h["hold_id"]})
    r = order(api, event_id, headers, h["hold_id"])
    assert r.status_code == 409 and "no longer active" in r.json()["detail"]


def test_return_url_must_be_allow_listed(api, provider):
    event_id, headers, h = held(api)
    r = order(api, event_id, headers, h["hold_id"], return_url="https://evil.example/steal")
    assert r.status_code == 422


def test_idempotency_key_header_is_required(api, provider):
    event_id, headers, h = held(api)
    r = api.post(f"/book/{event_id}/orders", json={"hold_id": h["hold_id"]}, headers=headers)
    assert r.status_code == 422


def test_provider_down_then_retry_with_same_key_finishes(api, provider):
    event_id, headers, h = held(api)
    key = uuid.uuid4()
    provider.fail = True
    assert order(api, event_id, headers, h["hold_id"], key).status_code == 502
    provider.fail = False
    r = order(api, event_id, headers, h["hold_id"], key)
    assert r.status_code == 200 and r.json()["provider_order_id"]  # same order, now complete


def test_read_own_order_only(api, provider):
    event_id, headers, h = held(api)
    o = order(api, event_id, headers, h["hold_id"]).json()
    mine = api.get(f"/orders/{o['order_id']}", headers=headers)
    assert mine.status_code == 200 and mine.json()["status"] == "pending"
    assert api.get(f"/orders/{o['order_id']}", headers=buyer()).status_code == 404


def test_twenty_parallel_creates_with_one_key_make_one_order(api, provider, migrated_engine):
    event_id, headers, h = held(api)
    sub = None
    # The buyer's sub is inside the token; read it back from the hold row.
    with migrated_engine.connect() as conn:
        sub = conn.execute(
            text("SELECT buyer_id FROM holds WHERE id = :h"), {"h": h["hold_id"]}
        ).scalar_one()
    factory = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    key, barrier = uuid.uuid4(), threading.Barrier(20)

    def attempt(_):
        with factory() as db:
            barrier.wait()
            o, created = create_order(
                db, provider, uuid.UUID(event_id), sub, uuid.UUID(h["hold_id"]), key, None
            )
            return o.id, created

    with ThreadPoolExecutor(20) as pool:
        results = list(pool.map(attempt, range(20)))
    assert len({oid for oid, _ in results}) == 1
    assert sum(created for _, created in results) == 1
    with migrated_engine.connect() as conn:
        n = conn.execute(
            text("SELECT count(*) FROM orders WHERE hold_id = :h"), {"h": h["hold_id"]}
        ).scalar_one()
        items = conn.execute(
            text(
                "SELECT count(*) FROM order_items i JOIN orders o ON o.id = i.order_id "
                "WHERE o.hold_id = :h"
            ),
            {"h": h["hold_id"]},
        ).scalar_one()
    assert (n, items) == (1, 2)
