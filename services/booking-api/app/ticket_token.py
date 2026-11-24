"""Signed ticket tokens (same code as services/workers/src/sg_workers/ticket_token.py; a shared
test vector in both test suites keeps them identical). The gate check-in uses verify().
    token = base64url(payload) "." base64url(HMAC-SHA256(key, first part))
    payload = {"typ": "ticket", "tid": <ticket id>, "ord": <order id>, "ev": <event id>,
               "seat": {"id": <seat id>, "label": "A-1-3"}, "iat": <paid_at, unix>, "kid": ...}

The same format as the booking pass, with a different key and `typ`. The gate check-in (booking
API) verifies the signature, `typ` and event, then marks the ticket used ONCE
(`UPDATE tickets SET used_at = now() WHERE id = :tid AND used_at IS NULL`).

Deterministic: the same ticket always gives the same token (sorted JSON keys, iat = paid_at),
so re-issuing a ticket (a retry or a replay) never changes the QR code.
Key: Secrets Manager TICKET_KEY_SECRET_ID = {"kid": ..., "key": ...}; TICKET_KEY_JSON in tests.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign(payload: dict, key: dict) -> str:
    body = _b64(
        json.dumps(payload | {"kid": key["kid"]}, sort_keys=True, separators=(",", ":")).encode()
    )
    sig = hmac.new(key["key"].encode(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64(sig)}"


def verify(token: str, keys: dict[str, str], event_id: str | None = None) -> dict:
    """Return the payload or raise ValueError. `keys` = {kid: key} (old keys during rotation)."""
    try:
        body, sig = token.split(".")
        payload = json.loads(_unb64(body))
        given = _unb64(sig)
    except (ValueError, TypeError) as exc:
        raise ValueError("malformed ticket") from exc
    key = keys.get(payload.get("kid", ""))
    if key is None:
        raise ValueError("unknown key")
    if not hmac.compare_digest(
        given, hmac.new(key.encode(), body.encode(), hashlib.sha256).digest()
    ):
        raise ValueError("forged ticket")
    if payload.get("typ") != "ticket":
        raise ValueError("not a ticket")
    if event_id is not None and payload.get("ev") != event_id:
        raise ValueError("ticket is for another event")
    return payload
