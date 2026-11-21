"""Signed tokens: compact, HMAC-SHA256, bound to one user and one event (blueprint: "Queue
tokens and booking passes are signed and bound to the user, so they cannot be forged or shared").

Format:  base64url(JSON payload) "." base64url(HMAC-SHA256(key, first part))

The key lives in Secrets Manager as JSON {"kid": "...", "key": "..."}; it is read with the
function's IAM role and cached for a few minutes. `kid` is in every token so the key can be
rotated: the verifier picks the key by kid.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from functools import lru_cache

import boto3

KEY_CACHE_SECONDS = 300


class TokenError(ValueError):
    """The token is malformed, forged, expired, or for someone or something else."""


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


@lru_cache(maxsize=1)
def _secrets():
    return boto3.client("secretsmanager")


_keys: dict[str, tuple[float, dict]] = {}


def signing_key(secret_id: str | None = None) -> dict:
    """{"kid": ..., "key": ...} from Secrets Manager, cached for KEY_CACHE_SECONDS."""
    secret_id = secret_id or os.environ["TOKEN_KEY_SECRET"]
    hit = _keys.get(secret_id)
    if hit and time.monotonic() - hit[0] < KEY_CACHE_SECONDS:
        return hit[1]
    value = json.loads(_secrets().get_secret_value(SecretId=secret_id)["SecretString"])
    _keys[secret_id] = (time.monotonic(), value)
    return value


def sign(payload: dict, key: dict) -> str:
    body = _b64(json.dumps(payload | {"kid": key["kid"]}, separators=(",", ":")).encode())
    sig = hmac.new(key["key"].encode(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64(sig)}"


def verify(token: str, key: dict, *, typ: str, sub: str, event_id: str) -> dict:
    """Return the payload if the token is genuine, unexpired and for this user and event."""
    try:
        body, sig = token.split(".")
        payload = json.loads(_unb64(body))
        given = _unb64(sig)
    except (ValueError, TypeError) as exc:
        raise TokenError("malformed token") from exc
    if payload.get("kid") != key["kid"]:
        raise TokenError("unknown key")
    expected = hmac.new(key["key"].encode(), body.encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(given, expected):  # constant time: no timing side channel
        raise TokenError("bad signature")
    if payload.get("typ") != typ:
        raise TokenError("wrong token type")
    if payload.get("exp", 0) < time.time():
        raise TokenError("token expired")
    if payload.get("sub") != sub or payload.get("ev") != event_id:
        raise TokenError("token belongs to another user or event")
    return payload
