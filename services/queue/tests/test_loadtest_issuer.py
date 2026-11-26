"""Load-test issuer: serves only public discovery + JWKS, never private key fields."""

import json

import boto3
import pytest
from moto import mock_aws

from sg_queue import loadtest_issuer

PUBLIC = {"kty": "RSA", "kid": "lt-1", "use": "sig", "alg": "RS256", "n": "AQAB", "e": "AQAB"}


def event(path, method="GET"):
    return {
        "rawPath": path,
        "requestContext": {
            "domainName": "abc.lambda-url.ap-south-1.on.aws",
            "http": {"method": method},
        },
    }


@pytest.fixture
def ssm(monkeypatch):
    with mock_aws():
        monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-south-1")
        monkeypatch.setenv("JWKS_PARAM", "/surgegate/demo/loadtest/jwks")
        loadtest_issuer._cache.clear()
        client = boto3.client("ssm", region_name="ap-south-1")
        yield client


def put(ssm, keys):
    ssm.put_parameter(
        Name="/surgegate/demo/loadtest/jwks",
        Value=json.dumps({"keys": keys}),
        Type="String",
        Overwrite=True,
    )


def test_discovery_points_at_itself(ssm):
    r = loadtest_issuer.handler(event("/.well-known/openid-configuration"), None)
    body = json.loads(r["body"])
    assert r["statusCode"] == 200
    assert body["issuer"] == "https://abc.lambda-url.ap-south-1.on.aws"
    assert body["jwks_uri"] == "https://abc.lambda-url.ap-south-1.on.aws/.well-known/jwks.json"


def test_jwks_serves_public_key(ssm):
    put(ssm, [PUBLIC])
    r = loadtest_issuer.handler(event("/.well-known/jwks.json"), None)
    assert r["statusCode"] == 200 and json.loads(r["body"]) == {"keys": [PUBLIC]}


def test_jwks_refuses_private_fields(ssm):
    put(ssm, [PUBLIC | {"d": "secret"}])
    with pytest.raises(ValueError):
        loadtest_issuer.handler(event("/.well-known/jwks.json"), None)


def test_no_key_yet_is_503(ssm):
    put(ssm, [])
    assert loadtest_issuer.handler(event("/.well-known/jwks.json"), None)["statusCode"] == 503


@pytest.mark.parametrize(
    "path, method, status", [("/token", "GET", 404), ("/.well-known/jwks.json", "POST", 405)]
)
def test_nothing_else(ssm, path, method, status):
    assert loadtest_issuer.handler(event(path, method), None)["statusCode"] == status
