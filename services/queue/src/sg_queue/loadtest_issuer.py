"""Demo-only load-test token issuer: the PUBLIC half (Day 10 Task 4).

Served from a Lambda function URL that exists only during a demo load-test window. It answers
exactly two paths, which is all an OpenID-style JWT checker needs:

    GET /.well-known/openid-configuration   {"issuer": <this URL>, "jwks_uri": ...}
    GET /.well-known/jwks.json              the public key(s), from SSM JWKS_PARAM

API Gateway's JWT authorizer (demo queue API) and the demo booking API fetch these to check the
signature of the test tokens. The PRIVATE key never comes here: it is in Secrets Manager, read
only by the k6 pods that mint the tokens. Nothing in this function can sign anything.
"""

from __future__ import annotations

import json
import os
import time

import boto3

CACHE_SECONDS = 300
_cache: dict[str, tuple[float, str]] = {}


def jwks() -> str:
    hit = _cache.get("jwks")
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    value = boto3.client("ssm").get_parameter(Name=os.environ["JWKS_PARAM"])["Parameter"]["Value"]
    keys = json.loads(value).get("keys", [])
    # Public keys only: refuse to publish anything that looks like private key material.
    if any(set(k) & {"d", "p", "q", "dp", "dq", "qi"} for k in keys):
        raise ValueError("JWKS parameter contains private key fields")
    body = json.dumps({"keys": keys})
    _cache["jwks"] = (time.monotonic(), body)
    return body


def _reply(status: int, body: str, max_age: int = 300) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json", "Cache-Control": f"max-age={max_age}"},
        "body": body,
    }


def handler(event, context):
    http = event.get("requestContext", {}).get("http", {})
    if http.get("method") != "GET":
        return _reply(405, json.dumps({"detail": "GET only"}), 0)
    base = "https://" + event["requestContext"]["domainName"]
    path = event.get("rawPath", "")
    if path == "/.well-known/openid-configuration":
        return _reply(
            200,
            json.dumps(
                {
                    "issuer": base,
                    "jwks_uri": f"{base}/.well-known/jwks.json",
                    "id_token_signing_alg_values_supported": ["RS256"],
                    "response_types_supported": ["token"],
                    "subject_types_supported": ["public"],
                }
            ),
        )
    if path == "/.well-known/jwks.json":
        keys = jwks()
        if not json.loads(keys)["keys"]:
            return _reply(503, json.dumps({"detail": "no key published yet"}), 0)
        return _reply(200, keys)
    return _reply(404, json.dumps({"detail": "not found"}), 60)
