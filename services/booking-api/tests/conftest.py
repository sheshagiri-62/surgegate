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
def api(migrated_engine, monkeypatch):
    """The real app, real JWT checks (local signing key) and the test database."""
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker
    from tests.helpers import SETTINGS, FakeJwks

    from app import auth, db
    from app.main import app

    factory = sessionmaker(bind=migrated_engine, expire_on_commit=False)

    def session():
        s = factory()
        try:
            yield s
        finally:
            s.close()

    monkeypatch.setattr(auth, "_jwks_client", lambda url: FakeJwks())
    app.dependency_overrides[auth.get_auth_settings] = lambda: SETTINGS
    app.dependency_overrides[db.get_session] = session
    yield TestClient(app)
    app.dependency_overrides.clear()
