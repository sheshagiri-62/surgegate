"""POST /org/events/{id}/live-token: own events only, 60 s, verifiable by the WebSocket."""

import json

import pytest
from tests.helpers import organiser
from tests.test_organiser import create

from app import live_token

KEY = {"kid": "l1", "key": "L" * 40}
EV = "9abf74ae-c14f-46e1-9e8f-8ee9872b7995"
# Same string as services/event-consumers (the authorizer's copy): the two must agree.
VECTOR = (
    "eyJldiI6IjlhYmY3NGFlLWMxNGYtNDZlMS05ZThmLThlZTk4NzJiNzk5NSIsImV4cCI6MTgwMDAwMDA2MCwiaWF0Ijox"
    "ODAwMDAwMDAwLCJraWQiOiJsMSIsInN1YiI6Im9yZy0xIiwidHlwIjoibGl2ZSJ9.tPWE8_XJnJiU6Y-dMsTed6qPmgaVbimnh0rSp15aD30"
)


def test_shared_vector():
    assert live_token.issue(EV, "org-1", KEY, now=1_800_000_000) == VECTOR
    assert live_token.verify(VECTOR, KEY, now=1_800_000_059)["sub"] == "org-1"


@pytest.mark.integration
def test_organiser_gets_a_60_second_token_for_own_event(api, monkeypatch):
    monkeypatch.setenv("LIVE_KEY_JSON", json.dumps(KEY))
    monkeypatch.setenv("LIVE_WS_URL", "wss://ws.test/live")
    org = organiser()
    ev = create(api, org)
    r = api.post(f"/org/events/{ev['id']}/live-token", headers=org)
    assert r.status_code == 200
    body = r.json()
    claims = live_token.verify(body["token"], KEY)
    assert claims["ev"] == ev["id"] and claims["exp"] - claims["iat"] == 60
    assert (
        body["ws_url"] == f"wss://ws.test/live?token={body['token']}" and body["expires_in"] == 60
    )
    assert api.post(f"/org/events/{ev['id']}/live-token", headers=organiser()).status_code == 404
