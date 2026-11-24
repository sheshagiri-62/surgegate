"""60-second signed "live tokens" for the organiser dashboard WebSocket (Day 8 Task 3).

Browsers can't set headers on a WebSocket, so the token travels in the query string
(`wss://…/live?token=…`). The booking API issues it (organiser only, own tenant's event) and
the $connect authorizer verifies it with the standard library only:

    token = base64url(payload) "." base64url(HMAC-SHA256(key, first part))
    payload = {"typ": "live", "ev": <event id>, "sub": <organiser>, "iat": ..., "exp": iat + 60}

Same format as the booking pass and the ticket token, with its own key and `typ`. The key is
Secrets Manager LIVE_KEY_SECRET_ID = {"kid": ..., "key": ...} (LIVE_KEY_JSON in tests).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

TTL_SECONDS = 60


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def issue(event_id: str, sub: str, key: dict, now: int | None = None) -> str:
    now = int(time.time()) if now is None else now
    payload = {"typ": "live", "ev": event_id, "sub": sub, "iat": now, "exp": now + TTL_SECONDS}
    body = _b64(
        json.dumps(payload | {"kid": key["kid"]}, sort_keys=True, separators=(",", ":")).encode()
    )
    return f"{body}.{_b64(hmac.new(key['key'].encode(), body.encode(), hashlib.sha256).digest())}"


def verify(token: str, key: dict, now: int | None = None) -> dict:
    """Return the payload or raise ValueError."""
    try:
        body, sig = token.split(".")
        payload = json.loads(_unb64(body))
        given = _unb64(sig)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("malformed token") from exc
    expected = hmac.new(key["key"].encode(), body.encode(), hashlib.sha256).digest()
    if payload.get("kid") != key["kid"] or not hmac.compare_digest(given, expected):
        raise ValueError("forged token")
    if payload.get("typ") != "live":
        raise ValueError("not a live token")
    if payload.get("exp", 0) < (int(time.time()) if now is None else now):
        raise ValueError("token expired")
    return payload
