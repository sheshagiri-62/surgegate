"""Mint this shard's 1-hour load-test tokens (k6 Job init container, demo only).

Runs in the booking-api image (it already has PyJWT[crypto] + boto3) with the k6 service
account, whose Pod Identity role may read ONLY the issuer key secret. Writes /work/tokens.json
for the k6 container next to it; the private key never leaves this pod's memory.

Each fan gets its own subject "lt-<run>-<shard>-<n>", so the queue gives one place per fan.
Claims: iss = the issuer URL, aud = the load-test audience, token_use = access, 1-hour lifetime,
cognito:groups = [buyer] (the queue's join checks it; the booking API forces buyer anyway).
"""

from __future__ import annotations

import json
import os
import time

import boto3
import jwt
from cryptography.hazmat.primitives.serialization import load_pem_private_key

LIFETIME = 3600  # the booking API refuses longer-lived test tokens


def main() -> None:
    secret = json.loads(
        boto3.client(
            "secretsmanager", region_name=os.getenv("AWS_REGION", "ap-south-1")
        ).get_secret_value(SecretId=os.environ["KEY_SECRET_ID"])["SecretString"]
    )
    issuer, audience = os.environ["ISSUER"], os.environ["AUDIENCE"]
    run, shard, count = (
        os.environ["RUN_ID"],
        int(os.environ["JOB_COMPLETION_INDEX"]),
        int(os.environ["VUS"]),
    )
    # Parse the key ONCE: PyJWT re-parses a PEM string on every encode (~0.1 s each).
    key = load_pem_private_key(secret["private_key_pem"].encode(), password=None)
    now = int(time.time())
    tokens = [
        jwt.encode(
            {
                "iss": issuer,
                "aud": audience,
                "sub": f"lt-{run}-{shard:02d}-{n:05d}",
                "token_use": "access",
                "iat": now,
                "exp": now + LIFETIME,
                "cognito:groups": ["buyer"],
            },
            key,
            algorithm="RS256",
            headers={"kid": secret["kid"]},
        )
        for n in range(count)
    ]
    out = os.getenv("OUT", "/work/tokens.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(tokens, f)
    print(json.dumps({"minted": len(tokens), "shard": shard, "expires_in_s": LIFETIME, "out": out}))


if __name__ == "__main__":
    main()
