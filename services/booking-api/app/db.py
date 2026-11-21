"""Database connection.

Two ways to connect:

* DATABASE_URL set (tests, CI, a laptop): used as is.
* Otherwise (in the cluster): DB_INSTANCE_ID names the RDS instance. The pod's IAM role
  (EKS Pod Identity) may call rds:DescribeDBInstances on that instance and read ONLY the
  master secret RDS manages for it. Host, port, database name and the secret ARN are looked
  up at start-up, so nothing changes when make up restores the database from a snapshot
  (a restored instance gets a new RDS-managed secret).

The password is fetched again every few minutes through a SQLAlchemy "do_connect" hook, so
RDS's automatic password rotation never breaks new connections. TLS is required and the
server certificate is verified against the RDS CA bundle baked into the image.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker

RDS_CA_BUNDLE = os.getenv("RDS_CA_BUNDLE", "/srv/certs/rds-global-bundle.pem")
PASSWORD_TTL_SECONDS = 300


@dataclass(frozen=True)
class RdsTarget:
    host: str
    port: int
    dbname: str
    secret_arn: str


def _region() -> str:
    return os.getenv("AWS_REGION", "ap-south-1")


def discover_rds(instance_id: str) -> RdsTarget:
    import boto3  # imported lazily: tests with DATABASE_URL never need AWS

    rds = boto3.client("rds", region_name=_region())
    db = rds.describe_db_instances(DBInstanceIdentifier=instance_id)["DBInstances"][0]
    return RdsTarget(
        host=db["Endpoint"]["Address"],
        port=int(db["Endpoint"]["Port"]),
        dbname=db.get("DBName") or "surgegate",
        secret_arn=db["MasterUserSecret"]["SecretArn"],
    )


class _SecretCache:
    """RDS-managed secret {"username", "password"}, re-read at most every few minutes."""

    def __init__(self, secret_arn: str) -> None:
        self._arn = secret_arn
        self._lock = threading.Lock()
        self._value: dict[str, str] | None = None
        self._fetched = 0.0

    def get(self) -> dict[str, str]:
        with self._lock:
            if self._value is None or time.monotonic() - self._fetched > PASSWORD_TTL_SECONDS:
                import boto3

                sm = boto3.client("secretsmanager", region_name=_region())
                raw = sm.get_secret_value(SecretId=self._arn)["SecretString"]
                self._value = json.loads(raw)
                self._fetched = time.monotonic()
            return self._value


def database_url() -> str | URL:
    """URL for Alembic and the engine. In the cluster the password is added per connection."""
    if url := os.getenv("DATABASE_URL"):
        return url
    target = _rds_target()
    return URL.create(
        "postgresql+psycopg",
        username=_secret_cache(target.secret_arn).get()["username"],
        host=target.host,
        port=target.port,
        database=target.dbname,
        query={"sslmode": "verify-full", "sslrootcert": RDS_CA_BUNDLE},
    )


@lru_cache(maxsize=1)
def _rds_target() -> RdsTarget:
    instance_id = os.getenv("DB_INSTANCE_ID")
    if not instance_id:
        raise RuntimeError("Set DATABASE_URL (local/CI) or DB_INSTANCE_ID (cluster).")
    return discover_rds(instance_id)


@lru_cache(maxsize=4)
def _secret_cache(secret_arn: str) -> _SecretCache:
    return _SecretCache(secret_arn)


def make_engine(url: str | URL | None = None, **kwargs) -> Engine:
    url = url or database_url()
    options = {
        "pool_size": int(os.getenv("DB_POOL_SIZE", "5")),
        "max_overflow": int(os.getenv("DB_MAX_OVERFLOW", "5")),
        "pool_pre_ping": True,
        "pool_recycle": 1800,
    } | kwargs  # explicit arguments win
    engine = create_engine(url, **options)
    if isinstance(url, URL) and not os.getenv("DATABASE_URL"):  # cluster: RDS-managed secret
        cache = _secret_cache(_rds_target().secret_arn)

        @event.listens_for(engine, "do_connect")
        def _inject_password(dialect, conn_rec, cargs, cparams):  # noqa: ANN001
            cparams["password"] = cache.get()["password"]

    return engine


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return make_engine()


@lru_cache(maxsize=1)
def _session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request, always closed."""
    session = _session_factory()()
    try:
        yield session
    finally:
        session.close()
