"""Cognito users for waiting-room load tests (dev only).

Every virtual user needs its own account: the queue gives one place per account and API Gateway
checks a real Cognito access token. This tool creates N buyer accounts on the reserved .test
domain (no email is ever sent), signs them in with the dev-only password client, writes the
tokens for k6, and deletes the accounts afterwards.

    python load_users.py create 1000          # accounts + tokens -> .load_tokens.json (gitignored)
    python load_users.py tokens 1000          # refresh tokens (they last 60 minutes)
    python load_users.py delete 1000

Cost note: each account that signs in counts as one Cognito monthly active user (MAU).
Passwords are random per run and never written to disk; only the short-lived tokens are.
"""

from __future__ import annotations

import json
import secrets
import sys
from concurrent.futures import ThreadPoolExecutor

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

REGION = "ap-south-1"
TOKENS_FILE = ".load_tokens.json"
cfg = Config(region_name=REGION, retries={"mode": "adaptive", "max_attempts": 10})
idp = boto3.client("cognito-idp", config=cfg)


def settings() -> tuple[str, str]:
    sm = boto3.client("secretsmanager", region_name=REGION)
    client_id = json.loads(
        sm.get_secret_value(SecretId="surgegate/dev/test-users")["SecretString"]
    )["client_id"]
    pools = idp.list_user_pools(MaxResults=20)["UserPools"]
    pool_id = next(p["Id"] for p in pools if p["Name"] == "surgegate-dev")
    return pool_id, client_id


def email(i: int) -> str:
    return f"load-{i:04d}@surgegate.test"


def make(pool_id: str, client_id: str, i: int, password: str) -> str:
    try:
        idp.admin_create_user(
            UserPoolId=pool_id,
            Username=email(i),
            UserAttributes=[
                {"Name": "email", "Value": email(i)},
                {"Name": "email_verified", "Value": "true"},
            ],
            MessageAction="SUPPRESS",
        )
        idp.admin_add_user_to_group(UserPoolId=pool_id, Username=email(i), GroupName="buyer")
    except ClientError as err:
        if err.response["Error"]["Code"] != "UsernameExistsException":
            raise
    idp.admin_set_user_password(
        UserPoolId=pool_id, Username=email(i), Password=password, Permanent=True
    )
    return sign_in(client_id, i, password)


def sign_in(client_id: str, i: int, password: str) -> str:
    out = idp.initiate_auth(
        ClientId=client_id,
        AuthFlow="USER_PASSWORD_AUTH",
        AuthParameters={"USERNAME": email(i), "PASSWORD": password},
    )
    return out["AuthenticationResult"]["AccessToken"]


def main() -> None:
    action, n = sys.argv[1], int(sys.argv[2])
    pool_id, client_id = settings()
    if action == "delete":

        def drop(i: int) -> None:
            try:
                idp.admin_delete_user(UserPoolId=pool_id, Username=email(i))
            except ClientError as err:
                if err.response["Error"]["Code"] != "UserNotFoundException":
                    raise

        with ThreadPoolExecutor(8) as pool:
            list(pool.map(drop, range(1, n + 1)))
        print(f"deleted {n} load-test users")
        return
    password = "Lt-" + secrets.token_urlsafe(18) + "9a"  # random per run, kept in memory only
    with ThreadPoolExecutor(8) as pool:
        tokens = list(pool.map(lambda i: make(pool_id, client_id, i, password), range(1, n + 1)))
    with open(TOKENS_FILE, "w") as f:
        json.dump(tokens, f)
    print(f"{action}: {len(tokens)} tokens -> {TOKENS_FILE} (valid 60 minutes)")


if __name__ == "__main__":
    main()
