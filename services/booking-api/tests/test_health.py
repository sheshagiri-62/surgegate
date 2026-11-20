from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_healthz_returns_ok():
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_root_reports_service_and_version():
    response = client.get("/")
    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "booking-api"
    assert body["version"]
