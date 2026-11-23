"""PostgreSQL for the workers (Lambda in the VPC), with the pure-Python driver pg8000 (vendored).

Same rules as the booking API (services/booking-api/app/db.py):
  * DATABASE_URL set (tests, CI): use it (postgresql://user:password@host:port/db).
  * Otherwise: DB_INSTANCE_ID names the RDS instance; endpoint and the RDS-managed master
    secret are looked up with the function's IAM role. TLS with certificate verification
    against the RDS CA bundle shipped in this package (rds.force_ssl is on).
"""

from __future__ import annotations

import json
import os
import ssl
import sys
from functools import lru_cache
from pathlib import Path
from urllib.parse import unquote, urlparse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "_vendor"))  # pg8000 and its pure-Python dependencies

import pg8000.native  # noqa: E402


@lru_cache(maxsize=1)
def _rds_params() -> dict:
    import boto3

    region = os.getenv("AWS_REGION", "ap-south-1")
    db = boto3.client("rds", region_name=region).describe_db_instances(
        DBInstanceIdentifier=os.environ["DB_INSTANCE_ID"]
    )["DBInstances"][0]
    secret = json.loads(
        boto3.client("secretsmanager", region_name=region).get_secret_value(
            SecretId=db["MasterUserSecret"]["SecretArn"]
        )["SecretString"]
    )
    context = ssl.create_default_context(cafile=str(HERE / "rds-global-bundle.pem"))
    return {
        "host": db["Endpoint"]["Address"],
        "port": int(db["Endpoint"]["Port"]),
        "database": db.get("DBName") or "surgegate",
        "user": secret["username"],
        "password": secret["password"],
        "ssl_context": context,
    }


def connect() -> pg8000.native.Connection:
    if url := os.getenv("DATABASE_URL"):
        u = urlparse(url.replace("postgresql+psycopg://", "postgresql://"))
        return pg8000.native.Connection(
            user=unquote(u.username or ""),
            password=unquote(u.password or ""),
            host=u.hostname,
            port=u.port or 5432,
            database=u.path.lstrip("/"),
            timeout=10,
        )
    try:
        return pg8000.native.Connection(**_rds_params(), timeout=10)
    except pg8000.native.DatabaseError:
        _rds_params.cache_clear()  # the RDS-managed password may have rotated: re-read once
        return pg8000.native.Connection(**_rds_params(), timeout=10)
