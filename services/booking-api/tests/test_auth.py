"""JWT checks, with a locally generated RSA key standing in for Cognito's JWKS."""

import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import auth
from app.auth import AuthSettings, Buyer, Organiser

ISSUER = "https://cognito-idp.ap-south-1.amazonaws.com/ap-south-1_TEST"
CLIENT = "buyer-web-client"
SETTINGS = AuthSettings(issuer=ISSUER, client_ids=frozenset({CLIENT}))
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
TENANT = uuid.uuid4()


class FakeJwks:
    """Behaves like PyJWKClient: returns our public key for kid "k1", fails otherwise."""

    def get_signing_key_from_jwt(self, token):
        kid = jwt.get_unverified_header(token).get("kid")
        if kid != "k1":
            raise jwt.PyJWKClientError(f'Unable to find a signing key that matches: "{kid}"')
        return jwt.PyJWK.from_dict(
            {**jwt.algorithms.RSAAlgorithm.to_jwk(KEY.public_key(), as_dict=True), "kid": "k1"}
        )


@pytest.fixture(autouse=True)
def fake_jwks(monkeypatch):
    monkeypatch.setattr(auth, "_jwks_client", lambda url: FakeJwks())


def token(key=KEY, kid="k1", **overrides):
    now = int(time.time())
    claims = {
        "sub": "user-1",
        "iss": ISSUER,
        "client_id": CLIENT,
        "token_use": "access",
        "iat": now,
        "exp": now + 3600,
        "cognito:groups": ["buyer"],
    } | overrides
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid})


app = FastAPI()
app.dependency_overrides[auth.get_auth_settings] = lambda: SETTINGS


@app.get("/any")
def any_user(p: auth.AnyUser):
    return {"sub": p.sub, "tenant": str(p.tenant_id) if p.tenant_id else None}


@app.get("/buyer")
def buyer_only(p: Buyer):
    return {"ok": True}


@app.get("/org")
def organiser_only(p: Organiser):
    return {"tenant": str(p.tenant_id)}


client = TestClient(app)


def call(path, tok):
    return client.get(path, headers={"Authorization": f"Bearer {tok}"} if tok else {})


def test_valid_buyer_token_is_accepted():
    r = call("/buyer", token())
    assert r.status_code == 200


def test_missing_token_is_401():
    r = call("/any", None)
    assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    ("tok", "detail"),
    [
        (token(exp=int(time.time()) - 120), "token expired"),
        (
            token(iss="https://cognito-idp.ap-south-1.amazonaws.com/ap-south-1_EVIL"),
            "invalid token",
        ),
        (token(client_id="someone-elses-client"), "unknown client"),
        (token(token_use="id"), "access token required"),  # noqa: S106
        (token(key=OTHER_KEY), "invalid token"),  # right kid, wrong signature
        (token(kid="unknown"), "unknown signing key"),
        (token(token_use=None), "invalid token"),  # required claim missing
        ("not-a-jwt", "invalid token"),
    ],
    ids=[
        "expired",
        "wrong-issuer",
        "wrong-client",
        "id-token",
        "bad-signature",
        "unknown-kid",
        "no-token_use",
        "garbage",
    ],
)
def test_bad_tokens_are_rejected(tok, detail):
    r = call("/any", tok)
    assert r.status_code == 401
    assert r.json()["detail"] == detail


def test_hs256_token_signed_with_public_key_is_rejected():
    """Algorithm confusion: only RS256 is accepted."""
    forged = jwt.encode(
        {
            "sub": "x",
            "iss": ISSUER,
            "client_id": CLIENT,
            "token_use": "access",
            "iat": int(time.time()),
            "exp": int(time.time()) + 60,
        },
        "secret",
        algorithm="HS256",
        headers={"kid": "k1"},
    )
    assert call("/any", forged).status_code == 401


def test_buyer_cannot_call_organiser_route():
    r = call("/org", token(**{"cognito:groups": ["buyer"], "tenant_id": str(TENANT)}))
    assert r.status_code == 403 and r.json()["detail"] == "organiser role required"


def test_organiser_without_tenant_is_refused():
    r = call("/org", token(**{"cognito:groups": ["organiser"]}))
    assert r.status_code == 403 and r.json()["detail"] == "organiser has no tenant"


def test_organiser_with_tenant_gets_tenant_from_the_token():
    r = call("/org", token(**{"cognito:groups": ["organiser"], "tenant_id": str(TENANT)}))
    assert r.status_code == 200 and r.json() == {"tenant": str(TENANT)}


def test_organiser_is_not_a_buyer():
    r = call("/buyer", token(**{"cognito:groups": ["organiser"], "tenant_id": str(TENANT)}))
    assert r.status_code == 403


def test_malformed_tenant_claim_is_rejected():
    r = call("/any", token(tenant_id="not-a-uuid"))
    assert r.status_code == 401 and r.json()["detail"] == "invalid tenant claim"


def test_unconfigured_auth_fails_closed():
    with pytest.raises(auth.HTTPException) as exc:
        auth.verify_access_token(token(), AuthSettings(issuer="", client_ids=frozenset()))
    assert exc.value.status_code == 503
