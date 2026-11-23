"""PaymentProvider: the mock client and Razorpay-style webhook signatures (unit tests)."""

import hashlib
import hmac
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app import payments

SECRET = {"key_id": "rzp_test_mock", "key_secret": "ks-test", "webhook_secret": "wh-test"}


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setenv("PAYMENT_SECRET_JSON", json.dumps(SECRET))


def test_signature_is_hex_hmac_sha256_of_the_raw_body():
    body = b'{"event":"payment.captured"}'
    expected = hmac.new(b"wh-test", body, hashlib.sha256).hexdigest()
    assert payments.webhook_signature(body, "wh-test") == expected


def test_verify_accepts_only_the_exact_body_and_secret():
    p = payments.MockProvider("http://unused", "https://edge.test")
    body = b'{"a":1}'
    good = payments.webhook_signature(body, "wh-test")
    assert p.verify_webhook_signature(body, good)
    assert not p.verify_webhook_signature(b'{"a": 1}', good)  # re-serialised body: refused
    assert not p.verify_webhook_signature(body, payments.webhook_signature(body, "other"))
    assert not p.verify_webhook_signature(body, "")


class _Mock(BaseHTTPRequestHandler):
    seen: list = []

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _Mock.seen.append((self.path, self.headers["Authorization"], body))
        out = json.dumps({"id": "order_abc123", "entity": "order", **body}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


def test_create_order_calls_the_mock_with_basic_auth():
    srv = HTTPServer(("127.0.0.1", 0), _Mock)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        p = payments.MockProvider(f"http://127.0.0.1:{srv.server_port}", "https://edge.test/")
        po = p.create_order(150000, "INR", "r-1", {"hold_id": "h"})
    finally:
        srv.shutdown()
    path, auth, body = _Mock.seen[-1]
    assert path == "/v1/orders" and auth.startswith("Basic ")
    assert body == {
        "amount": 150000,
        "currency": "INR",
        "receipt": "r-1",
        "notes": {"hold_id": "h"},
    }
    assert po.id == "order_abc123"
    assert po.checkout == {
        "type": "redirect",
        "url": "https://edge.test/mockpay/checkout/order_abc123",
    }


def test_unreachable_provider_raises_provider_error():
    p = payments.MockProvider("http://127.0.0.1:9", "https://edge.test", timeout=0.5)
    with pytest.raises(payments.ProviderError):
        p.create_order(100, "INR", "r", {})
