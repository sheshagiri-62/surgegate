"""mock-pay: Razorpay shapes, the checkout page's limits, and the test switches."""

import base64
import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from app import main

SECRET = {"key_id": "rzp_test_mock", "key_secret": "ks-test", "webhook_secret": "wh-test"}
AUTH = {"Authorization": "Basic " + base64.b64encode(b"rzp_test_mock:ks-test").decode()}


@pytest.fixture
def sent(monkeypatch):
    """Capture webhooks; deliver inline (no threads) so tests are deterministic."""
    out = []
    monkeypatch.setenv("SECRET_JSON", json.dumps(SECRET))
    monkeypatch.setenv("WEBHOOK_URL", "https://edge.test/webhooks/razorpay")
    monkeypatch.setenv("CALLBACK_ALLOW_ORIGINS", "http://localhost:3000")
    monkeypatch.setattr(main, "spawn", lambda fn, *a: fn(*a))
    monkeypatch.setattr(main.time, "sleep", lambda s: out.append(("slept", s)))
    monkeypatch.setattr(
        main, "http_send", lambda url, raw, headers: out.append((url, raw, headers)) or 200
    )
    return out


@pytest.fixture
def client(sent):
    return TestClient(main.app)


def new_order(client, amount=150000, callback="http://localhost:3000/order/?id=o-1"):
    r = client.post(
        "/v1/orders",
        json={"amount": amount, "receipt": "o-1", "notes": {"callback_url": callback}},
        headers=AUTH,
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_create_order_is_razorpay_shaped(client):
    o = new_order(client)
    assert o["id"].startswith("order_") and len(o["id"]) == 20
    assert (o["entity"], o["status"], o["amount_due"], o["currency"]) == (
        "order",
        "created",
        150000,
        "INR",
    )
    assert client.get(f"/v1/orders/{o['id']}", headers=AUTH).json()["id"] == o["id"]


def test_api_needs_the_key(client):
    r = client.post("/v1/orders", json={"amount": 100, "receipt": "x"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "BAD_REQUEST_ERROR"
    bad = {"Authorization": "Basic " + base64.b64encode(b"rzp_test_mock:nope").decode()}
    assert (
        client.post("/v1/orders", json={"amount": 100, "receipt": "x"}, headers=bad).status_code
        == 401
    )


def test_callback_must_be_allow_listed(client):
    r = client.post(
        "/v1/orders",
        json={"amount": 100, "receipt": "x", "notes": {"callback_url": "https://evil.example/"}},
        headers=AUTH,
    )
    assert r.status_code == 400


def test_pay_success_sends_a_signed_razorpay_webhook_and_redirects(client, sent):
    o = new_order(client)
    r = client.post(
        f"/mockpay/checkout/{o['id']}/pay", data={"outcome": "success"}, follow_redirects=False
    )
    assert r.status_code == 303
    assert r.headers["location"].startswith(
        "http://localhost:3000/order/?id=o-1&razorpay_payment_id=pay_"
    )
    (url, raw, headers) = sent[-1]
    assert url == "https://edge.test/webhooks/razorpay"
    assert headers["X-Razorpay-Signature"] == hmac.new(b"wh-test", raw, hashlib.sha256).hexdigest()
    assert headers["X-Razorpay-Event-Id"].startswith("evt_")
    event = json.loads(raw)
    assert event["event"] == "payment.captured" and event["contains"] == ["payment"]
    payment = event["payload"]["payment"]["entity"]
    assert (payment["order_id"], payment["amount"], payment["status"]) == (
        o["id"],
        150000,
        "captured",
    )


def test_page_pays_only_existing_orders_for_their_own_amount(client, sent):
    assert client.get("/mockpay/checkout/order_doesnotexist").status_code == 404
    assert (
        client.post("/mockpay/checkout/order_nope/pay", data={"outcome": "success"}).status_code
        == 404
    )
    o = new_order(client, amount=50000)
    # An "amount" in the form is ignored: the stored order decides.
    client.post(
        f"/mockpay/checkout/{o['id']}/pay",
        data={"outcome": "success", "amount": "1"},
        follow_redirects=False,
    )
    payment = json.loads(sent[-1][1])["payload"]["payment"]["entity"]
    assert payment["amount"] == 50000


def test_an_order_is_paid_only_once(client):
    o = new_order(client)
    client.post(
        f"/mockpay/checkout/{o['id']}/pay", data={"outcome": "success"}, follow_redirects=False
    )
    again = client.post(f"/mockpay/checkout/{o['id']}/pay", data={"outcome": "success"})
    assert again.status_code == 409
    assert "Already paid" in client.get(f"/mockpay/checkout/{o['id']}").text


def test_pay_fail_sends_payment_failed_and_allows_a_retry(client, sent):
    o = new_order(client)
    r = client.post(
        f"/mockpay/checkout/{o['id']}/pay", data={"outcome": "fail"}, follow_redirects=False
    )
    assert r.headers["location"].endswith("&payment=failed")
    assert json.loads(sent[-1][1])["event"] == "payment.failed"
    assert client.get(f"/v1/orders/{o['id']}", headers=AUTH).json()["status"] == "attempted"
    ok = client.post(
        f"/mockpay/checkout/{o['id']}/pay", data={"outcome": "success"}, follow_redirects=False
    )
    assert ok.status_code == 303


def test_bad_outcome_is_refused(client):
    o = new_order(client)
    assert (
        client.post(f"/mockpay/checkout/{o['id']}/pay", data={"outcome": "free"}).status_code == 400
    )


def test_switch_duplicate_sends_the_same_event_twice(client, sent):
    o = new_order(client)
    client.post("/mockpay/test/pay", json={"order_id": o["id"], "duplicate": True})
    a, b = sent[-2:]
    assert a[1] == b[1] and a[2]["X-Razorpay-Event-Id"] == b[2]["X-Razorpay-Event-Id"]
    deliveries = client.get(f"/mockpay/test/orders/{o['id']}").json()["deliveries"]
    assert [d["attempt"] for d in deliveries] == [1, 2] and deliveries[0]["result"] == 200


def test_switch_bad_signature(client, sent):
    o = new_order(client)
    client.post("/mockpay/test/pay", json={"order_id": o["id"], "bad_signature": True})
    url, raw, headers = sent[-1]
    assert headers["X-Razorpay-Signature"] != hmac.new(b"wh-test", raw, hashlib.sha256).hexdigest()


def test_switch_delay(client, sent):
    o = new_order(client)
    client.post("/mockpay/test/pay", json={"order_id": o["id"], "delay_seconds": 90})
    assert ("slept", 90) in sent


def test_resend_repeats_a_past_webhook_exactly(client, sent):
    o = new_order(client)
    pid = client.post("/mockpay/test/pay", json={"order_id": o["id"]}).json()["payment"]["id"]
    first = sent[-1]
    client.post(f"/mockpay/test/webhooks/{pid}/resend", json={})
    assert sent[-1][1] == first[1] and sent[-1][2] == first[2]


def test_no_callback_shows_a_result_page(client):
    o = new_order(client, callback="")
    r = client.post(f"/mockpay/checkout/{o['id']}/pay", data={"outcome": "success"})
    assert r.status_code == 200 and "Payment captured" in r.text


def test_refund_is_razorpay_shaped_and_idempotent(client):
    o = new_order(client, amount=40000)
    pid = client.post("/mockpay/test/pay", json={"order_id": o["id"]}).json()["payment"]["id"]
    r1 = client.post(f"/v1/payments/{pid}/refund", json={"amount": 40000}, headers=AUTH)
    r2 = client.post(f"/v1/payments/{pid}/refund", json={"amount": 40000}, headers=AUTH)
    assert r1.status_code == 200 and r1.json()["id"].startswith("rfnd_")
    assert r2.json()["id"] == r1.json()["id"]  # a retried worker never refunds twice
    assert (r1.json()["amount"], r1.json()["status"]) == (40000, "processed")
    assert len(client.get(f"/mockpay/test/orders/{o['id']}").json()["refunds"]) == 1


def test_refund_rules(client):
    o = new_order(client, amount=40000)
    failed = client.post("/mockpay/test/pay", json={"order_id": o["id"], "outcome": "fail"}).json()[
        "payment"
    ]["id"]
    assert client.post(f"/v1/payments/{failed}/refund", json={}, headers=AUTH).status_code == 400
    ok = client.post("/mockpay/test/pay", json={"order_id": o["id"]}).json()["payment"]["id"]
    too_much = client.post(f"/v1/payments/{ok}/refund", json={"amount": 50000}, headers=AUTH)
    assert too_much.status_code == 400
    assert client.post(f"/v1/payments/{ok}/refund", json={}).status_code == 401
    assert client.post("/v1/payments/pay_nope/refund", json={}, headers=AUTH).status_code == 404
