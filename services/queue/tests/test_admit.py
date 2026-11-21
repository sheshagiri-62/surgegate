import json
import time
from datetime import UTC, datetime, timedelta

import boto3
import pytest

from sg_queue import admit, tokens
from tests.conftest import TEST_KEY, api_event, body, open_queue

PASS_KEY = {"kid": "pass-1", "key": "p" * 64}


@pytest.fixture
def pass_key(aws, monkeypatch):
    sm = boto3.client("secretsmanager", region_name="ap-south-1")
    sm.create_secret(Name="pass-key", SecretString=json.dumps(PASS_KEY))
    monkeypatch.setenv("PASS_KEY_SECRET", "pass-key")


def place(table, ev, sub, pos, **extra):
    table.put_item(
        Item={
            "PK": f"EVENT#{ev}",
            "SK": f"USER#{sub}",
            "request_id": "r",
            "joined_at": "2026-01-01T00:00:00+00:00",
            "position": pos,
        }
        | extra
    )


def queue_token(ev, sub, pos, **overrides):
    now = int(time.time())
    return tokens.sign(
        {"typ": "queue", "ev": ev, "sub": sub, "pos": pos, "iat": now, "exp": now + 600}
        | overrides,
        TEST_KEY,
    )


def call(ev, sub, token):
    return admit.handler(api_event(ev, sub=sub, body=json.dumps({"queue_token": token})), None)


def test_admitted_buyer_gets_a_15_minute_pass_bound_to_them(aws, pass_key):
    ev = open_queue(aws["table"], serving_up_to=10)
    place(aws["table"], ev, "me", 7)
    r = call(ev, "me", queue_token(ev, "me", 7))
    assert r["statusCode"] == 200
    p = tokens.verify(body(r)["booking_pass"], PASS_KEY, typ="pass", sub="me", event_id=ev)
    assert 14 * 60 < p["exp"] - time.time() <= 15 * 60
    with pytest.raises(tokens.TokenError):  # not a queue token, not signed with the queue key
        tokens.verify(body(r)["booking_pass"], TEST_KEY, typ="pass", sub="me", event_id=ev)


def test_not_your_turn_yet_is_409(aws, pass_key):
    ev = open_queue(aws["table"], serving_up_to=5)
    place(aws["table"], ev, "me", 7)
    r = call(ev, "me", queue_token(ev, "me", 7))
    assert r["statusCode"] == 409
    assert body(r)["detail"] == "not your turn yet"


def test_someone_elses_token_is_useless(aws, pass_key):
    ev = open_queue(aws["table"], serving_up_to=100)
    place(aws["table"], ev, "owner", 1)
    r = call(ev, "thief", queue_token(ev, "owner", 1))
    assert r["statusCode"] == 403
    assert "another user" in body(r)["detail"]


def test_forged_position_is_refused(aws, pass_key):
    ev = open_queue(aws["table"], serving_up_to=10)
    place(aws["table"], ev, "me", 900)
    forged = tokens.sign(
        {"typ": "queue", "ev": ev, "sub": "me", "pos": 1, "exp": int(time.time()) + 60},
        {"kid": TEST_KEY["kid"], "key": "guess"},
    )
    assert call(ev, "me", forged)["statusCode"] == 403
    # a genuine token whose position doesn't match the stored place is refused too
    assert call(ev, "me", queue_token(ev, "me", 1))["statusCode"] == 403


def test_expiry_counts_from_the_first_admission(aws, pass_key):
    ev = open_queue(aws["table"], serving_up_to=10)
    first = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
    place(aws["table"], ev, "me", 3, admitted_at=first)
    r = call(ev, "me", queue_token(ev, "me", 3))
    p = tokens.verify(body(r)["booking_pass"], PASS_KEY, typ="pass", sub="me", event_id=ev)
    assert 4 * 60 < p["exp"] - time.time() <= 5 * 60  # only the 5 minutes left, not a new 15


def test_window_over_is_410(aws, pass_key):
    ev = open_queue(aws["table"], serving_up_to=10)
    place(
        aws["table"],
        ev,
        "me",
        3,
        admitted_at=(datetime.now(UTC) - timedelta(minutes=16)).isoformat(),
    )
    assert call(ev, "me", queue_token(ev, "me", 3))["statusCode"] == 410


def test_bad_body_is_422(aws, pass_key):
    ev = open_queue(aws["table"])
    r = admit.handler(api_event(ev, sub="me", body="nope"), None)
    assert r["statusCode"] == 422
