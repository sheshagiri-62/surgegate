"""The broken-release switch: off by default; on, it fails requests but never /healthz."""

import importlib


def _client(monkeypatch, rate):
    from fastapi.testclient import TestClient

    import app.main as main

    if rate is None:
        monkeypatch.delenv("FAULT_ERROR_RATE", raising=False)
    else:
        monkeypatch.setenv("FAULT_ERROR_RATE", rate)
    return TestClient(importlib.reload(main).app)


def test_off_by_default(monkeypatch):
    c = _client(monkeypatch, None)
    assert all(c.get("/").status_code == 200 for _ in range(20))


def test_on_fails_requests_but_keeps_health_green(monkeypatch):
    c = _client(monkeypatch, "1")
    r = c.get("/")
    assert r.status_code == 500 and "injected fault" in r.json()["detail"]
    assert c.get("/healthz").status_code == 200
    _client(monkeypatch, None)  # reload without the fault for the other tests
