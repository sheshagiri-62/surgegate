"""Demo-only load-test issuer (Day 10 Task 4): trusted only when configured, always a buyer."""

import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

from app import auth
from app.auth import AuthSettings, verify_access_token

COGNITO = "https://cognito-idp.ap-south-1.amazonaws.com/ap-south-1_TEST"
LT_ISSUER = "https://abc123.lambda-url.ap-south-1.on.aws"
LT_AUD = "surgegate-demo-loadtest"
LT_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)

ON = AuthSettings(
    issuer=COGNITO,
    client_ids=frozenset({"buyer-web"}),
    loadtest_issuer=LT_ISSUER,
    loadtest_audience=LT_AUD,
)
OFF = AuthSettings(issuer=COGNITO, client_ids=frozenset({"buyer-web"}))  # dev: no test issuer


class FakeJwks:
    def __init__(self, url):
        self.url = url

    def get_signing_key_from_jwt(self, token):
        if self.url != f"{LT_ISSUER}/.well-known/jwks.json":
            raise jwt.PyJWKClientError("wrong JWKS asked")
        return jwt.PyJWK.from_dict(
            {**jwt.algorithms.RSAAlgorithm.to_jwk(LT_KEY.public_key(), as_dict=True), "kid": "lt"}
        )


@pytest.fixture(autouse=True)
def fake_jwks(monkeypatch):
    monkeypatch.setattr(auth, "_jwks_client", FakeJwks)


def lt_token(key=LT_KEY, lifetime=3600, **overrides):
    now = int(time.time())
    claims = {
        "iss": LT_ISSUER,
        "aud": LT_AUD,
        "sub": "lt-0001",
        "token_use": "access",
        "iat": now,
        "exp": now + lifetime,
        "cognito:groups": ["buyer"],
    } | overrides
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "lt"})


def test_valid_loadtest_token_is_a_plain_buyer():
    p = verify_access_token(lt_token(), ON)
    assert p.sub == "lt-0001" and p.is_buyer and not p.is_organiser
    assert p.tenant_id is None and p.email is None


def test_groups_and_tenant_claims_are_ignored():
    org_claims = {"cognito:groups": ["organiser"], "tenant_id": str(uuid.uuid4())}
    tok = lt_token(**org_claims)
    p = verify_access_token(tok, ON)
    assert p.groups == frozenset({"buyer"}) and p.tenant_id is None


@pytest.mark.parametrize(
    "tok, detail",
    [
        (lambda: lt_token(lifetime=3601), "load-test token lives longer than one hour"),
        (lambda: lt_token(aud="someone-else"), "invalid token"),
        (lambda: lt_token(aud=None), "invalid token"),
        (lambda: lt_token(key=OTHER_KEY), "invalid token"),
        (lambda: lt_token(token_use="id"), "access token required"),  # noqa: S106
        (lambda: lt_token(lifetime=-120), "token expired"),
    ],
)
def test_bad_loadtest_tokens_are_rejected(tok, detail):
    with pytest.raises(HTTPException) as err:
        verify_access_token(tok(), ON)
    assert err.value.status_code == 401 and err.value.detail == detail


def test_not_trusted_when_not_configured():
    # dev (and demo after the test): the test issuer is just an unknown issuer -> Cognito path.
    with pytest.raises(HTTPException) as err:
        verify_access_token(lt_token(), OFF)
    assert err.value.status_code == 401


def test_settings_read_from_env(monkeypatch):
    auth.get_auth_settings.cache_clear()
    monkeypatch.setenv("COGNITO_USER_POOL_ID", "ap-south-1_TEST")
    monkeypatch.setenv("COGNITO_CLIENT_IDS", "a,b")
    monkeypatch.setenv("LOADTEST_ISSUER", LT_ISSUER + "/")
    monkeypatch.setenv("LOADTEST_AUDIENCE", LT_AUD)
    s = auth.get_auth_settings()
    auth.get_auth_settings.cache_clear()
    assert s.loadtest_enabled and s.loadtest_issuer == LT_ISSUER


def test_settings_off_by_default(monkeypatch):
    auth.get_auth_settings.cache_clear()
    monkeypatch.delenv("LOADTEST_ISSUER", raising=False)
    monkeypatch.delenv("LOADTEST_AUDIENCE", raising=False)
    s = auth.get_auth_settings()
    auth.get_auth_settings.cache_clear()
    assert not s.loadtest_enabled
