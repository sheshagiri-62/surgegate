"""Redis connection and the seat-map cache (blueprint: seat map read from Redis, may lag ~2 s).

Keys
  seatmap:{event}        fresh copy, TTL 2 s. Deleted on every change we make (hold, upload),
                         so buyers normally see changes at once; the TTL bounds the lag for
                         changes made elsewhere (e.g. the hold-release timer, Day 7).
  seatmap:{event}:stale  same JSON, TTL 60 s. Served while another request rebuilds.
  seatmap:{event}:lock   SET NX, 2 s: only ONE request rebuilds from PostgreSQL after a miss,
                         so a popular event does not send thousands of queries at once.

Redis is only a cache: if it is down or slow, every call falls back to PostgreSQL.

Connection
  REDIS_URL set (tests, CI): used as is.
  Otherwise (cluster): REDIS_HOST + AUTH token from Secrets Manager (REDIS_AUTH_SECRET_ID),
  read with the pod's IAM role; TLS with certificate verification (rediss://).
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from functools import lru_cache

import redis

log = logging.getLogger(__name__)

FRESH_TTL_SECONDS = 2
STALE_TTL_SECONDS = 60
LOCK_TTL_SECONDS = 2


@lru_cache(maxsize=1)
def get_redis() -> redis.Redis | None:
    """A shared client, or None when no Redis is configured (cache disabled)."""
    common = {"socket_timeout": 0.5, "socket_connect_timeout": 0.5, "health_check_interval": 30}
    if url := os.getenv("REDIS_URL"):
        return redis.Redis.from_url(url, **common)
    host = os.getenv("REDIS_HOST")
    if not host:
        return None
    import boto3

    sm = boto3.client("secretsmanager", region_name=os.getenv("AWS_REGION", "ap-south-1"))
    token = sm.get_secret_value(SecretId=os.environ["REDIS_AUTH_SECRET_ID"])["SecretString"]
    return redis.Redis(host=host, port=6379, password=token, ssl=True, **common)


def _key(event_id: str) -> str:
    return f"seatmap:{event_id}"


def get_seat_map(event_id: str, load: Callable[[], dict | None]) -> tuple[dict | None, str]:
    """Return (seat map, source) where source is hit | miss | stale | db (Redis unavailable)."""
    r = get_redis()
    if r is None:
        return load(), "db"
    key = _key(event_id)
    try:
        if cached := r.get(key):
            return json.loads(cached), "hit"
        if not r.set(f"{key}:lock", "1", nx=True, ex=LOCK_TTL_SECONDS):
            if stale := r.get(f"{key}:stale"):
                return json.loads(stale), "stale"
    except redis.RedisError as exc:
        log.warning("redis unavailable, reading seat map from PostgreSQL: %s", exc)
        return load(), "db"

    data = load()
    if data is not None:
        try:
            blob = json.dumps(data, separators=(",", ":"))
            with r.pipeline(transaction=False) as p:
                p.set(key, blob, ex=FRESH_TTL_SECONDS)
                p.set(f"{key}:stale", blob, ex=STALE_TTL_SECONDS)
                p.delete(f"{key}:lock")
                p.execute()
        except redis.RedisError as exc:
            log.warning("could not cache seat map: %s", exc)
    return data, "miss"


def invalidate_seat_map(event_id: str) -> None:
    """Called after every committed change to an event's seats."""
    r = get_redis()
    if r is None:
        return
    try:
        r.delete(_key(event_id))
    except redis.RedisError as exc:
        log.warning("could not invalidate seat map (TTL will expire it): %s", exc)
