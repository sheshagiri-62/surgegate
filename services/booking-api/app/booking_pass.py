"""Booking pass check on every /book/{event}/... request (blueprint step 7).

Only buyers the waiting room has let in may see seats and hold them. The admit endpoint gives
them a 15-minute pass, sent back here in the `X-Booking-Pass` header:

    base64url(payload) "." base64url(HMAC-SHA256(pass key, first part))
    payload = {typ: "pass", ev: <event id>, sub: <Cognito sub>, iat, exp, kid}

The pass must be genuine, unexpired, for THIS event and for the SAME user as the access token,
so a pass can't be shared or reused for another sale. (Once CloudFront is verified, a
CloudFront Function checks the pass at the edge too, so requests without one never reach the
cluster; this check stays as defence in depth.)

Key: BOOKING_PASS_KEY_JSON (tests) or Secrets Manager BOOKING_PASS_SECRET_ID (cluster, read with
the pod's role, cached 5 minutes). BOOKING_PASS_REQUIRED=false turns the check off (tests of
seat logic only).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import uuid
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from app.auth import AnyUser

KEY_CACHE_SECONDS = 300
_cache: dict[str, tuple[float, dict]] = {}


def required() -> bool:
    return os.getenv("BOOKING_PASS_REQUIRED", "true").lower() != "false"


def _key() -> dict:
    if raw := os.getenv("BOOKING_PASS_KEY_JSON"):
        return json.loads(raw)
    secret_id = os.environ["BOOKING_PASS_SECRET_ID"]
    hit = _cache.get(secret_id)
    if hit and time.monotonic() - hit[0] < KEY_CACHE_SECONDS:
        return hit[1]
    import boto3

    sm = boto3.client("secretsmanager", region_name=os.getenv("AWS_REGION", "ap-south-1"))
    value = json.loads(sm.get_secret_value(SecretId=secret_id)["SecretString"])
    _cache[secret_id] = (time.monotonic(), value)
    return value


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def verify(token: str, key: dict, sub: str, event_id: uuid.UUID) -> dict:
    """Return the payload, or raise ValueError with the reason."""
    try:
        body, sig = token.split(".")
        payload = json.loads(_unb64(body))
        given = _unb64(sig)
    except (ValueError, TypeError) as exc:
        raise ValueError("malformed pass") from exc
    expected = hmac.new(key["key"].encode(), body.encode(), hashlib.sha256).digest()
    if payload.get("kid") != key["kid"] or not hmac.compare_digest(given, expected):
        raise ValueError("forged pass")
    if payload.get("typ") != "pass":
        raise ValueError("not a booking pass")
    if payload.get("exp", 0) < time.time():
        raise ValueError("pass expired")
    if payload.get("ev") != str(event_id):
        raise ValueError("pass is for another event")
    if payload.get("sub") != sub:
        raise ValueError("pass belongs to someone else")
    return payload


def require_pass(
    event_id: uuid.UUID,
    user: AnyUser,
    x_booking_pass: Annotated[str | None, Header()] = None,
) -> dict | None:
    if not required():
        return None
    if not x_booking_pass:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            {"reason": "booking pass required", "queue": f"/queue/{event_id}/join"},
        )
    try:
        return verify(x_booking_pass, _key(), user.sub, event_id)
    except ValueError as err:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            {"reason": f"booking pass refused: {err}", "queue": f"/queue/{event_id}/join"},
        ) from err


BookingPass = Annotated[dict | None, Depends(require_pass)]
