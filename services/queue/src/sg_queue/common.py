"""Shared helpers for the waiting-room Lambdas (API Gateway HTTP API, payload v2.0).

DynamoDB single table (blueprint "Data model"):
  PK = EVENT#<event id>, SK = META          queue state: status, sale_starts_at, next_position,
                                             serving_up_to, admission_rate
  PK = EVENT#<event id>, SK = USER#<sub>    queue entry: request_id, joined_at, position, ...
"""

from __future__ import annotations

import functools
import hmac
import json
import os
import time
import uuid
from datetime import UTC, datetime
from functools import lru_cache

import boto3

META = "META"
BUYER = "buyer"


def pk(event_id: str) -> str:
    return f"EVENT#{event_id}"


def user_sk(sub: str) -> str:
    return f"USER#{sub}"


@lru_cache(maxsize=1)
def table():
    return boto3.resource("dynamodb").Table(os.environ["QUEUE_TABLE"])


@lru_cache(maxsize=1)
def sqs():
    return boto3.client("sqs")


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def valid_event_id(value: str | None) -> bool:
    try:
        return value is not None and str(uuid.UUID(value)) == value.lower()
    except ValueError:
        return False


def response(status: int, body: dict, headers: dict | None = None) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json", "Cache-Control": "no-store"}
        | (headers or {}),
        "body": json.dumps(body, default=str),
    }


def claims(event: dict) -> dict:
    """Verified JWT claims (API Gateway's JWT authorizer already checked the signature)."""
    return event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})


def groups(c: dict) -> set[str]:
    # HTTP API passes array claims as a string like "[buyer organiser]".
    raw = c.get("cognito:groups", "")
    if isinstance(raw, list):
        return set(raw)
    return set(raw.strip("[]").replace(",", " ").split())


_meta_cache: dict[str, tuple[float, dict | None]] = {}
META_CACHE_SECONDS = 5


def queue_meta(event_id: str, max_age: float = META_CACHE_SECONDS) -> dict | None:
    """Queue state for an event, cached in this Lambda instance for a few seconds.

    Joins arrive in bursts; caching the (rarely changing) state means a burst of joins does
    not turn into a burst of DynamoDB reads.
    """
    hit = _meta_cache.get(event_id)
    if hit and time.monotonic() - hit[0] < max_age:
        return hit[1]
    item = table().get_item(Key={"PK": pk(event_id), "SK": META}).get("Item")
    _meta_cache[event_id] = (time.monotonic(), item)
    return item


def from_edge(event: dict) -> bool:
    """True if the request came through our CloudFront (its secret origin header), or if the
    check is switched off. WAF can only protect the CloudFront path; a request sent straight to
    the execute-api URL would skip WAF, so with ORIGIN_VERIFY_REQUIRED=true it is refused."""
    if os.getenv("ORIGIN_VERIFY_REQUIRED", "false") != "true":
        return True
    secret = os.getenv("ORIGIN_VERIFY_SECRET", "")
    name = os.getenv("ORIGIN_VERIFY_HEADER", "x-origin-verify")
    sent = (event.get("headers") or {}).get(name, "")
    return bool(secret) and hmac.compare_digest(sent.encode(), secret.encode())


def edge_only(handler):
    """Decorator for the public API handlers (join, position, admit, serving)."""

    @functools.wraps(handler)
    def wrapper(event, context):
        if not from_edge(event):
            return response(403, {"detail": "use the site's address, not the API's"})
        return handler(event, context)

    return wrapper
