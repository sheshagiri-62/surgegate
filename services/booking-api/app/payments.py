"""Payment providers (ADR 004): one interface; the mock now, Razorpay later.

The booking API only ever talks to `PaymentProvider`:

    create_order(amount_paise, currency, receipt, notes) -> ProviderOrder(id, checkout)
    checkout(provider_order_id)                          -> how the browser pays
    verify_webhook_signature(raw_body, signature)        -> bool   (the webhook endpoint)
    refund(payment_id, amount_paise)                     -> refund id (idempotent per payment)

`checkout` is a small descriptor the buyer app follows:
    mock:      {"type": "redirect", "url": "https://<cloudfront>/mockpay/checkout/order_..."}
    razorpay:  {"type": "razorpay_js", "key_id": "...", "order_id": "order_..."}  (later)

Keys: one JSON secret (Secrets Manager PAYMENT_SECRET_ID = surgegate/dev/data/razorpay) with
key_id, key_secret, webhook_secret. Tests set PAYMENT_SECRET_JSON instead. Values are never
logged.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

log = logging.getLogger(__name__)

SECRET_CACHE_SECONDS = 300
_secret_cache: dict[str, tuple[float, dict]] = {}


class ProviderError(Exception):
    """The provider could not be reached or refused the call; the buyer may retry."""


@dataclass(frozen=True)
class ProviderOrder:
    id: str
    checkout: dict


class PaymentProvider(Protocol):
    name: str

    def create_order(
        self, amount_paise: int, currency: str, receipt: str, notes: dict[str, str]
    ) -> ProviderOrder: ...

    def checkout(self, provider_order_id: str) -> dict: ...

    def verify_webhook_signature(self, raw_body: bytes, signature: str) -> bool: ...

    def refund(self, payment_id: str, amount_paise: int) -> str: ...


def payment_secret() -> dict:
    if raw := os.getenv("PAYMENT_SECRET_JSON"):
        return json.loads(raw)
    secret_id = os.environ["PAYMENT_SECRET_ID"]
    hit = _secret_cache.get(secret_id)
    if hit and time.monotonic() - hit[0] < SECRET_CACHE_SECONDS:
        return hit[1]
    import boto3

    sm = boto3.client("secretsmanager", region_name=os.getenv("AWS_REGION", "ap-south-1"))
    value = json.loads(sm.get_secret_value(SecretId=secret_id)["SecretString"])
    _secret_cache[secret_id] = (time.monotonic(), value)
    return value


def webhook_signature(raw_body: bytes, webhook_secret: str) -> str:
    """Razorpay's X-Razorpay-Signature: hex HMAC-SHA256 of the RAW request body."""
    return hmac.new(webhook_secret.encode(), raw_body, hashlib.sha256).hexdigest()


class MockProvider:
    """The Razorpay-shaped mock in the cluster (services/mock-pay)."""

    name = "mock"

    def __init__(self, api_url: str, checkout_base: str, timeout: float = 5.0):
        if not api_url.startswith(("http://", "https://")):
            raise ValueError("MOCKPAY_API_URL must be an http(s) URL")
        self.api_url = api_url.rstrip("/")
        self.checkout_base = checkout_base.rstrip("/")
        self.timeout = timeout

    def _post(self, path: str, payload: dict) -> dict:
        secret = payment_secret()
        auth = base64.b64encode(f"{secret['key_id']}:{secret['key_secret']}".encode()).decode()
        req = urllib.request.Request(  # noqa: S310 - http(s) only, checked in __init__
            f"{self.api_url}{path}",
            data=json.dumps(payload).encode(),
            headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:  # noqa: S310 - http(s) only, checked in __init__
                return json.loads(r.read())
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            log.error("mock provider %s failed: %s", path.split("/")[2], type(exc).__name__)
            raise ProviderError("payment provider unavailable") from exc

    def create_order(
        self, amount_paise: int, currency: str, receipt: str, notes: dict[str, str]
    ) -> ProviderOrder:
        body = self._post(
            "/v1/orders",
            {"amount": amount_paise, "currency": currency, "receipt": receipt, "notes": notes},
        )
        return ProviderOrder(id=body["id"], checkout=self.checkout(body["id"]))

    def refund(self, payment_id: str, amount_paise: int) -> str:
        """Razorpay-shaped POST /v1/payments/{id}/refund. The mock returns the SAME refund if
        asked twice for one payment, so a retried worker never refunds twice."""
        return self._post(f"/v1/payments/{payment_id}/refund", {"amount": amount_paise})["id"]

    def checkout(self, provider_order_id: str) -> dict:
        return {
            "type": "redirect",
            "url": f"{self.checkout_base}/mockpay/checkout/{provider_order_id}",
        }

    def verify_webhook_signature(self, raw_body: bytes, signature: str) -> bool:
        expected = webhook_signature(raw_body, payment_secret()["webhook_secret"])
        return hmac.compare_digest(expected, signature or "")


@lru_cache(maxsize=1)
def get_provider() -> PaymentProvider:
    kind = os.getenv("PAYMENT_PROVIDER", "mock")
    if kind == "mock":
        return MockProvider(
            api_url=os.getenv("MOCKPAY_API_URL", "http://mock-pay.mock-pay.svc.cluster.local"),
            checkout_base=os.getenv("MOCKPAY_CHECKOUT_BASE", "http://localhost:18081"),
        )
    raise RuntimeError(f"payment provider {kind!r} is not available yet (ADR 004)")
