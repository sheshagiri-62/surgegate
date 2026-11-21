"""CORS: only configured origins may call the API from a browser."""

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "http://localhost:3000")
    import app.main

    module = importlib.reload(app.main)
    yield TestClient(module.app)
    monkeypatch.delenv("CORS_ALLOW_ORIGINS")
    importlib.reload(app.main)


def preflight(client, origin):
    return client.options(
        "/book/00000000-0000-0000-0000-000000000000/holds",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type,x-booking-pass",
        },
    )


def test_allowed_origin_gets_cors_headers(client):
    r = preflight(client, "http://localhost:3000")
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "access-control-allow-credentials" not in r.headers


def test_other_origins_are_refused(client):
    r = preflight(client, "https://evil.example")
    assert r.status_code == 400
    assert "access-control-allow-origin" not in r.headers
