"""Shared fixtures.

Integration tests need a real PostgreSQL (the hold logic depends on its row locking), so they
run only when DATABASE_URL is set: in CI (postgres service container) or against dev RDS from
the cluster. Without it they are skipped and only the unit tests run.
"""

import os
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def pytest_collection_modifyitems(config, items):
    if os.getenv("DATABASE_URL"):
        return
    skip = pytest.mark.skip(reason="integration test: set DATABASE_URL to a PostgreSQL database")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def alembic_cfg():
    from alembic.config import Config

    return Config(str(ROOT / "alembic.ini"))


@pytest.fixture(scope="session")
def migrated_engine(alembic_cfg):
    """A database migrated to head once per test session (from an empty schema)."""
    from alembic import command

    from app.db import make_engine

    command.downgrade(alembic_cfg, "base")
    command.upgrade(alembic_cfg, "head")
    engine = make_engine(os.environ["DATABASE_URL"])
    yield engine
    engine.dispose()


@pytest.fixture
def queue_table(monkeypatch):
    """A moto DynamoDB queue table (the waiting room's state; the real one is in AWS)."""
    import boto3
    from moto import mock_aws

    from app import queue_control

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("QUEUE_TABLE", "queue-test")
    with mock_aws():
        boto3.resource("dynamodb", region_name="ap-south-1").create_table(
            TableName="queue-test",
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        queue_control.table.cache_clear()
        yield queue_control.table()
        queue_control.table.cache_clear()


@pytest.fixture
def api(migrated_engine, monkeypatch, queue_table):
    """The real app, real JWT checks (local signing key) and the test database."""
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker
    from tests.helpers import SETTINGS, FakeJwks

    from app import auth, cache, db
    from app.main import app

    factory = sessionmaker(bind=migrated_engine, expire_on_commit=False)

    def session():
        s = factory()
        try:
            yield s
        finally:
            s.close()

    monkeypatch.setattr(auth, "_jwks_client", lambda url: FakeJwks())
    cache.get_redis.cache_clear()
    if r := cache.get_redis():
        r.flushdb()
    app.dependency_overrides[auth.get_auth_settings] = lambda: SETTINGS
    app.dependency_overrides[db.get_session] = session
    yield TestClient(app)
    app.dependency_overrides.clear()
