import time

import pytest

from sg_queue import position, tokens
from tests.conftest import TEST_KEY, api_event, body, open_queue


def place(table, event_id, sub, pos=None):
    item = {
        "PK": f"EVENT#{event_id}",
        "SK": f"USER#{sub}",
        "request_id": "r",
        "joined_at": "2026-01-01T00:00:00+00:00",
    }
    if pos is not None:
        item["position"] = pos
    table.put_item(Item=item)


def get(event_id, sub="me", **qs):
    return position.handler(api_event(event_id, sub=sub, queryStringParameters=qs or None), None)


# --- tokens ---------------------------------------------------------------------------------


def new_token(**overrides):
    now = int(time.time())
    payload = {"typ": "queue", "ev": "e1", "sub": "u1", "pos": 7, "iat": now, "exp": now + 60}
    return tokens.sign(payload | overrides, TEST_KEY)


def test_a_genuine_token_verifies():
    assert tokens.verify(new_token(), TEST_KEY, typ="queue", sub="u1", event_id="e1")["pos"] == 7


@pytest.mark.parametrize(
    ("make", "kwargs", "error"),
    [
        (lambda: new_token(exp=int(time.time()) - 1), {}, "token expired"),
        (lambda: new_token(), {"sub": "someone-else"}, "another user or event"),
        (lambda: new_token(), {"event_id": "e2"}, "another user or event"),
        (lambda: new_token(typ="pass"), {}, "wrong token type"),
        (lambda: "garbage", {}, "malformed"),
        (
            lambda: tokens.sign({"typ": "queue"}, {"kid": "other", "key": "y" * 64}),
            {},
            "unknown key",
        ),
    ],
    ids=["expired", "other-user", "other-event", "wrong-type", "garbage", "unknown-kid"],
)
def test_bad_tokens_are_refused(make, kwargs, error):
    args = {"typ": "queue", "sub": "u1", "event_id": "e1"} | kwargs
    with pytest.raises(tokens.TokenError, match=error):
        tokens.verify(make(), TEST_KEY, **args)


def test_editing_the_position_breaks_the_signature():
    body_part, sig = new_token(pos=500).split(".")
    forged_body = tokens.sign(
        {"typ": "queue", "ev": "e1", "sub": "u1", "pos": 1, "exp": int(time.time()) + 60},
        {"kid": TEST_KEY["kid"], "key": "attacker-guess"},
    ).split(".")[0]
    with pytest.raises(tokens.TokenError, match="bad signature"):
        tokens.verify(f"{forged_body}.{sig}", TEST_KEY, typ="queue", sub="u1", event_id="e1")


def test_key_comes_from_secrets_manager_and_is_cached(aws, monkeypatch):
    calls = []
    real = tokens._secrets().get_secret_value
    monkeypatch.setattr(
        tokens._secrets(), "get_secret_value", lambda **kw: calls.append(kw) or real(**kw)
    )
    assert tokens.signing_key() == TEST_KEY
    assert tokens.signing_key() == TEST_KEY
    assert len(calls) == 1  # cached for KEY_CACHE_SECONDS


# --- position endpoint -------------------------------------------------------------------------


def test_not_in_queue_is_404_and_just_joined_is_202(aws):
    ev = open_queue(aws["table"])
    assert get(ev)["statusCode"] == 404
    r = get(ev, req="some-request-id")
    assert r["statusCode"] == 202 and body(r) == {"status": "joining"}


def test_pre_queue_place_has_no_number_and_no_token(aws):
    ev = open_queue(aws["table"], status="pre-queue")
    place(aws["table"], ev, "me")
    r = body(get(ev))
    assert r["status"] == "pre-queue" and "queue_token" not in r and "position" not in r


def test_queued_place_gets_position_estimate_and_a_token_bound_to_me(aws):
    ev = open_queue(aws["table"], serving_up_to=100, admission_rate=125)
    place(aws["table"], ev, "me", pos=600)
    r = body(get(ev))
    assert r["status"] == "queued"
    assert (r["position"], r["serving_up_to"], r["ahead"]) == (600, 100, 499)
    assert r["estimated_wait_seconds"] == 4 * 60  # 500 / 125 per minute = 4 minutes
    payload = tokens.verify(r["queue_token"], TEST_KEY, typ="queue", sub="me", event_id=ev)
    assert payload["pos"] == 600
    with pytest.raises(tokens.TokenError):  # useless to anyone else
        tokens.verify(r["queue_token"], TEST_KEY, typ="queue", sub="thief", event_id=ev)


def test_admitted_when_serving_reaches_my_number(aws):
    ev = open_queue(aws["table"], serving_up_to=600)
    place(aws["table"], ev, "me", pos=600)
    r = body(get(ev))
    assert r["status"] == "admitted" and r["ahead"] == 0 and r["estimated_wait_seconds"] == 0


def test_paused_queue_gives_no_estimate(aws):
    ev = open_queue(aws["table"], status="paused", serving_up_to=0)
    place(aws["table"], ev, "me", pos=10)
    assert body(get(ev))["estimated_wait_seconds"] is None


def test_unknown_queue_is_404(aws):
    assert get("00000000-0000-4000-8000-000000000000")["statusCode"] == 404
