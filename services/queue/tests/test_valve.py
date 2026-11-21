from sg_queue import valve
from tests.conftest import open_queue


def state(table, ev):
    return table.get_item(Key={"PK": f"EVENT#{ev}", "SK": "META"})["Item"]


def run(table, ev, minute):
    return valve.tick(state(table, ev), minute)


def test_each_minute_admits_the_admission_rate(aws):
    ev = open_queue(aws["table"], admission_rate=125, next_position=1000)
    for i, expected in enumerate([125, 250, 375], start=1):
        run(aws["table"], ev, f"2026-11-21T18:0{i}")
        assert state(aws["table"], ev)["serving_up_to"] == expected


def test_never_runs_ahead_of_the_people_in_line(aws):
    ev = open_queue(aws["table"], admission_rate=125, next_position=40)
    run(aws["table"], ev, "2026-11-21T18:01")
    assert state(aws["table"], ev)["serving_up_to"] == 40


def test_a_repeated_tick_in_the_same_minute_admits_nobody_extra(aws):
    ev = open_queue(aws["table"], admission_rate=100, next_position=1000)
    assert run(aws["table"], ev, "2026-11-21T18:01") is not None
    assert run(aws["table"], ev, "2026-11-21T18:01") is None  # retry / duplicate
    assert state(aws["table"], ev)["serving_up_to"] == 100


def test_stale_reading_cannot_double_admit(aws):
    """Two ticks read the same old value; only one update can win."""
    ev = open_queue(aws["table"], admission_rate=100, next_position=1000)
    stale = state(aws["table"], ev)
    valve.tick(stale, "2026-11-21T18:01")
    assert valve.tick(stale, "2026-11-21T18:02") is None  # old serving_up_to no longer matches
    assert state(aws["table"], ev)["serving_up_to"] == 100


def test_paused_and_pre_queue_queues_do_not_move(aws):
    paused = open_queue(aws["table"], status="paused", admission_rate=100, next_position=500)
    pre = open_queue(aws["table"], status="pre-queue", admission_rate=100, next_position=500)
    out = valve.handler({}, None)
    assert out["advanced"] == []
    assert state(aws["table"], paused)["serving_up_to"] == 0
    assert state(aws["table"], pre)["serving_up_to"] == 0


def test_pause_between_read_and_write_wins(aws):
    ev = open_queue(aws["table"], admission_rate=100, next_position=500)
    seen = state(aws["table"], ev)
    aws["table"].update_item(
        Key={"PK": f"EVENT#{ev}", "SK": "META"},
        UpdateExpression="SET #s = :p",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":p": "paused"},
    )
    assert valve.tick(seen, "2026-11-21T18:01") is None
    assert state(aws["table"], ev)["serving_up_to"] == 0


def test_handler_advances_every_open_queue(aws):
    a = open_queue(aws["table"], admission_rate=10, next_position=100)
    b = open_queue(aws["table"], admission_rate=20, next_position=100)
    out = valve.handler({}, None)
    assert {m["event"]: m["to"] for m in out["advanced"]} == {a: 10, b: 20}
