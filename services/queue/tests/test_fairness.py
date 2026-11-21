"""One place per account, and the pre-queue shuffle at sale start."""

import json
import uuid
from datetime import UTC, datetime, timedelta

from sg_queue import join, positions, sequencer, starter
from tests.conftest import api_event, drain, open_queue


def entries(table, event_id):
    return table.query(
        KeyConditionExpression="PK = :p AND begins_with(SK, :u)",
        ExpressionAttributeValues={":p": f"EVENT#{event_id}", ":u": "USER#"},
    )["Items"]


def meta(table, event_id):
    return table.get_item(Key={"PK": f"EVENT#{event_id}", "SK": "META"})["Item"]


def iso(dt):
    return dt.astimezone(UTC).isoformat()


def message(event_id, sub, joined_at, request_id=None):
    body = {
        "event_id": event_id,
        "sub": sub,
        "request_id": request_id or str(uuid.uuid4()),
        "joined_at": joined_at,
    }
    return {"messageId": str(uuid.uuid4()), "body": json.dumps(body)}


# --- one place per account -----------------------------------------------------------------


def test_joining_five_times_gives_one_place_and_no_gaps(aws):
    ev = open_queue(aws["table"])
    for _ in range(5):
        join.handler(api_event(ev, sub="repeat"), None)
    join.handler(api_event(ev, sub="other"), None)
    sequencer.handler(drain(aws["queue_url"]), None)
    places = entries(aws["table"], ev)
    assert sorted(e["SK"] for e in places) == ["USER#other", "USER#repeat"]
    assert sorted(int(e["position"]) for e in places) == [1, 2]  # duplicates leave no gaps
    assert meta(aws["table"], ev)["next_position"] == 2


def test_duplicate_in_a_later_batch_keeps_the_first_place(aws):
    ev = open_queue(aws["table"])
    join.handler(api_event(ev, sub="early"), None)
    sequencer.handler(drain(aws["queue_url"]), None)
    first = entries(aws["table"], ev)[0]
    join.handler(api_event(ev, sub="early"), None)
    sequencer.handler(drain(aws["queue_url"]), None)
    (again,) = entries(aws["table"], ev)
    assert again["position"] == first["position"]
    assert again["request_id"] == first["request_id"]  # the first join's place is kept


def test_a_retried_half_done_message_still_gets_its_number(aws):
    """Crash after claiming but before numbering: the SQS retry must not lose the person."""
    ev = open_queue(aws["table"])
    msg = message(ev, "crashy", iso(datetime.now(UTC)))
    positions.claim(json.loads(msg["body"]), pre_queue=False)  # claimed, no position
    sequencer.handler({"Records": [msg]}, None)  # the retry
    (e,) = entries(aws["table"], ev)
    assert int(e["position"]) == 1


# --- pre-queue and shuffle ---------------------------------------------------------------------


def pre_queue_event(table, starts_in=timedelta(minutes=-1)):
    return open_queue(table, status="pre-queue", sale_starts_at=iso(datetime.now(UTC) + starts_in))


def test_before_the_sale_places_have_no_position_and_a_random_key(aws):
    ev = pre_queue_event(aws["table"], starts_in=timedelta(minutes=10))
    for i in range(5):
        join.handler(api_event(ev, sub=f"p{i}"), None)
    sequencer.handler(drain(aws["queue_url"]), None)
    places = entries(aws["table"], ev)
    assert len(places) == 5
    assert all("position" not in e and "shuffle_key" in e for e in places)
    assert starter.handler({}, None) == {"started": []}  # not time yet


def test_sale_start_shuffles_early_joiners_then_appends_late_ones(aws):
    start = datetime.now(UTC) - timedelta(seconds=30)
    ev = open_queue(aws["table"], status="pre-queue", sale_starts_at=iso(start))
    early = [
        message(ev, f"early-{i:02d}", iso(start - timedelta(seconds=600 - 10 * i)))
        for i in range(40)
    ]
    late = [message(ev, f"late-{i}", iso(start + timedelta(seconds=1 + i))) for i in range(3)]
    sequencer.handler({"Records": early + late}, None)  # queue still says pre-queue

    out = starter.handler({}, None)
    assert out["started"][0]["shuffled"] == 43
    assert meta(aws["table"], ev)["status"] == "open"
    by_pos = sorted(entries(aws["table"], ev), key=lambda e: int(e["position"]))
    assert [int(e["position"]) for e in by_pos] == list(range(1, 44))
    order = [e["SK"].removeprefix("USER#") for e in by_pos]
    assert set(order[:40]) == {f"early-{i:02d}" for i in range(40)}
    assert order[40:] == ["late-0", "late-1", "late-2"]  # after the start: join order
    assert order[:40] != sorted(order[:40])  # early joiners were really shuffled
    assert all("shuffle_key" not in e for e in by_pos)


def test_arriving_early_gives_no_advantage(aws):
    """Over many sales, the very first joiner lands anywhere, not at the front."""
    first_positions = []
    for _ in range(30):
        start = datetime.now(UTC) - timedelta(seconds=1)
        ev = open_queue(aws["table"], status="pre-queue", sale_starts_at=iso(start))
        joins = [message(ev, f"u{i}", iso(start - timedelta(minutes=30 - i))) for i in range(20)]
        sequencer.handler({"Records": joins}, None)
        starter.start_sale(ev, iso(start))
        first = aws["table"].get_item(Key={"PK": f"EVENT#{ev}", "SK": "USER#u0"})["Item"]
        first_positions.append(int(first["position"]))
    assert len(set(first_positions)) > 5  # all over the queue, not always #1


def test_only_one_starter_shuffles(aws):
    start = datetime.now(UTC) - timedelta(seconds=5)
    ev = open_queue(aws["table"], status="pre-queue", sale_starts_at=iso(start))
    sequencer.handler(
        {"Records": [message(ev, f"u{i}", iso(start - timedelta(minutes=1))) for i in range(5)]},
        None,
    )
    assert starter.start_sale(ev, iso(start))["started"] is True
    assert starter.start_sale(ev, iso(start)) == {"event": ev, "started": False}
    assert sorted(int(e["position"]) for e in entries(aws["table"], ev)) == [1, 2, 3, 4, 5]


def test_joins_after_the_sale_opened_are_numbered_by_the_sequencer(aws):
    start = datetime.now(UTC) - timedelta(seconds=5)
    ev = open_queue(aws["table"], status="pre-queue", sale_starts_at=iso(start))
    starter.handler({}, None)  # opens the (empty) queue
    sequencer.handler({"Records": [message(ev, "after", iso(datetime.now(UTC)))]}, None)
    (e,) = entries(aws["table"], ev)
    assert int(e["position"]) == 1


def test_place_claimed_during_the_shuffle_is_swept(aws, monkeypatch):
    """A sequencer read 'pre-queue', then the starter shuffled, then the claim landed."""
    start = datetime.now(UTC) - timedelta(seconds=5)
    ev = open_queue(aws["table"], status="pre-queue", sale_starts_at=iso(start))
    real_unpositioned = positions.unpositioned
    calls = {"n": 0}

    def unpositioned_then_claim(event_id):
        calls["n"] += 1
        found = real_unpositioned(event_id)
        if calls["n"] == 1:  # right after the shuffle query, a late claim lands
            positions.claim(json.loads(message(ev, "racer", iso(start))["body"]), pre_queue=True)
        return found

    monkeypatch.setattr(positions, "unpositioned", unpositioned_then_claim)
    starter.start_sale(ev, iso(start))
    (e,) = entries(aws["table"], ev)
    assert int(e["position"]) == 1  # caught by the sweep after opening


def test_starter_finishes_an_interrupted_shuffle(aws):
    start = datetime.now(UTC) - timedelta(seconds=5)
    ev = open_queue(aws["table"], status="shuffling", sale_starts_at=iso(start))
    positions.claim(json.loads(message(ev, "stuck", iso(start))["body"]), pre_queue=True)
    starter.handler({}, None)
    assert meta(aws["table"], ev)["status"] == "open"
    assert int(entries(aws["table"], ev)[0]["position"]) == 1


def test_closed_queues_are_not_in_the_active_index(aws):
    open_queue(aws["table"], status="pre-queue", sale_starts_at=iso(datetime.now(UTC)))
    closed = open_queue(aws["table"], status="sold_out")
    aws["table"].update_item(
        Key={"PK": f"EVENT#{closed}", "SK": "META"}, UpdateExpression="REMOVE active"
    )
    assert len(starter.active_queues()) == 1
