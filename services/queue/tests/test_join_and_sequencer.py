import json
import uuid

from sg_queue import join, sequencer
from tests.conftest import api_event, body, drain, open_queue


def entries(table, event_id):
    return table.query(
        KeyConditionExpression="PK = :p AND begins_with(SK, :u)",
        ExpressionAttributeValues={":p": f"EVENT#{event_id}", ":u": "USER#"},
    )["Items"]


def test_join_answers_202_and_only_queues_the_request(aws):
    ev = open_queue(aws["table"])
    r = join.handler(api_event(ev, sub="u1"), None)
    assert r["statusCode"] == 202
    rid = body(r)["request_id"]
    (msg,) = drain(aws["queue_url"])["Records"]
    sent = json.loads(msg["body"])
    assert sent["event_id"] == ev and sent["sub"] == "u1" and sent["request_id"] == rid
    assert entries(aws["table"], ev) == []  # the join itself writes nothing to the table


def test_join_needs_a_buyer_and_an_open_queue(aws):
    ev = open_queue(aws["table"])
    assert join.handler(api_event(ev, groups="[organiser]"), None)["statusCode"] == 403
    assert join.handler(api_event(str(uuid.uuid4())), None)["statusCode"] == 404
    assert join.handler(api_event("not-a-uuid"), None)["statusCode"] == 404
    closed = open_queue(aws["table"], status="sold_out")
    r = join.handler(api_event(closed), None)
    assert r["statusCode"] == 409
    assert body(r)["detail"] == "the queue is sold_out"


def test_sequencer_assigns_positions_in_join_order_with_one_counter_update(aws, monkeypatch):
    ev = open_queue(aws["table"])
    for i in range(25):
        join.handler(api_event(ev, sub=f"u{i:02d}"), None)
    calls = []
    real = sequencer.reserve_positions
    monkeypatch.setattr(sequencer, "reserve_positions", lambda e, n: calls.append(n) or real(e, n))
    out = sequencer.handler(drain(aws["queue_url"]), None)
    assert out == {"batchItemFailures": []}
    assert calls == [25]  # ONE counter update for the whole batch, not 25
    by_time = sorted(entries(aws["table"], ev), key=lambda i: i["joined_at"])
    assert [int(i["position"]) for i in by_time] == list(range(1, 26))
    meta = aws["table"].get_item(Key={"PK": f"EVENT#{ev}", "SK": "META"})["Item"]
    assert meta["next_position"] == 25


def test_next_batch_continues_after_the_last_position(aws):
    ev = open_queue(aws["table"])
    for batch in range(2):
        for i in range(3):
            join.handler(api_event(ev, sub=f"b{batch}-{i}"), None)
        sequencer.handler(drain(aws["queue_url"]), None)
    assert sorted(int(i["position"]) for i in entries(aws["table"], ev)) == [1, 2, 3, 4, 5, 6]


def test_batch_with_two_events_and_a_bad_message(aws):
    a, b = open_queue(aws["table"]), open_queue(aws["table"])
    join.handler(api_event(a, sub="x"), None)
    join.handler(api_event(b, sub="y"), None)
    records = drain(aws["queue_url"])["Records"] + [{"messageId": "bad", "body": "{not json"}]
    out = sequencer.handler({"Records": records}, None)
    assert out == {"batchItemFailures": [{"itemIdentifier": "bad"}]}  # only the bad one retried
    assert len(entries(aws["table"], a)) == 1
    assert len(entries(aws["table"], b)) == 1


def test_unknown_event_is_retried_not_lost(aws):
    msg = {
        "event_id": str(uuid.uuid4()),  # no META item
        "sub": "z",
        "request_id": "r",
        "joined_at": "2026-01-01T00:00:00+00:00",
    }
    out = sequencer.handler({"Records": [{"messageId": "m1", "body": json.dumps(msg)}]}, None)
    assert out == {"batchItemFailures": [{"itemIdentifier": "m1"}]}
