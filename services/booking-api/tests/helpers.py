"""Signed test tokens: a local RSA key stands in for Cognito's JWKS."""

import time
import uuid

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from app.auth import AuthSettings

ISSUER = "https://cognito-idp.ap-south-1.amazonaws.com/ap-south-1_TEST"
CLIENT = "test-client"
SETTINGS = AuthSettings(issuer=ISSUER, client_ids=frozenset({CLIENT}))
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class FakeJwks:
    def get_signing_key_from_jwt(self, token):
        return jwt.PyJWK.from_dict(
            {**jwt.algorithms.RSAAlgorithm.to_jwk(KEY.public_key(), as_dict=True), "kid": "k1"}
        )


def make_token(
    sub: str, groups: list[str], tenant_id: uuid.UUID | None = None, email: str | None = None
) -> str:
    now = int(time.time())
    claims = {
        "sub": sub,
        "iss": ISSUER,
        "client_id": CLIENT,
        "token_use": "access",
        "iat": now,
        "exp": now + 3600,
        "cognito:groups": groups,
    }
    if tenant_id:
        claims["tenant_id"] = str(tenant_id)
    if email:
        claims["email"] = email
    return jwt.encode(claims, KEY, algorithm="RS256", headers={"kid": "k1"})


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def organiser(tenant_id: uuid.UUID | None = None) -> dict[str, str]:
    """Headers for a new organiser in tenant_id (a fresh tenant by default)."""
    return bearer(make_token(f"org-{uuid.uuid4()}", ["organiser"], tenant_id or uuid.uuid4()))


def buyer(sub: str | None = None, email: str | None = None) -> dict[str, str]:
    return bearer(make_token(sub or f"buyer-{uuid.uuid4()}", ["buyer"], email=email))


# --- booking passes (what the queue's admit endpoint issues) ------------------------------
PASS_KEY = {"kid": "pass-test", "key": "k" * 64}


def make_pass(sub: str, event_id, ttl: int = 900, key: dict | None = None, **overrides) -> str:
    import base64
    import hashlib
    import hmac
    import json

    key = key or PASS_KEY
    now = int(time.time())
    payload = {
        "typ": "pass",
        "ev": str(event_id),
        "sub": sub,
        "iat": now,
        "exp": now + ttl,
        "kid": key["kid"],
    } | overrides
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    sig = hmac.new(key["key"].encode(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{base64.urlsafe_b64encode(sig).rstrip(b'=').decode()}"


def admitted_buyer(event_id, sub: str | None = None) -> dict[str, str]:
    """Headers of a buyer the waiting room has let in: access token + booking pass."""
    sub = sub or f"buyer-{uuid.uuid4()}"
    return buyer(sub) | {"X-Booking-Pass": make_pass(sub, event_id)}
