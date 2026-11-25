"""Backpressure: admission rate down when the booking API is slow, back up (never above the
organiser's rate) when it recovers."""

import pytest

from sg_queue import backpressure
from tests.conftest import open_queue


def meta(table, ev):
    return table.get_item(Key={"PK": f"EVENT#{ev}", "SK": "META"})["Item"]


@pytest.mark.parametrize(
    ("p95", "requests", "errors", "state"),
    [
        (0.8, 500, 0, "unhealthy"),  # slow
        (0.1, 500, 10, "unhealthy"),  # 2% 5xx
        (0.1, 500, 0, "healthy"),
        (0.4, 500, 0, "steady"),  # between 300 and 500 ms: hold
        (2.0, 5, 0, "idle"),  # 5 requests say nothing
    ],
)
def test_classify(p95, requests, errors, state):
    assert backpressure.classify(p95, requests, errors)["state"] == state


def test_next_rate_steps():
    assert backpressure.next_rate(250, 250, "unhealthy") == 175
    assert backpressure.next_rate(25, 250, "unhealthy") == 20  # floor
    assert backpressure.next_rate(10, 250, "unhealthy") == 10  # never raised by "slowing down"
    assert backpressure.next_rate(175, 250, "healthy") == 211
    assert backpressure.next_rate(240, 250, "healthy") == 250  # capped at the organiser's rate
    assert backpressure.next_rate(250, 250, "healthy") == 250
    assert backpressure.next_rate(175, 250, "steady") == 175
    assert backpressure.next_rate(175, 250, "idle") == 211


def test_slow_api_lowers_then_recovery_restores_the_organisers_rate(aws, monkeypatch):
    t = aws["table"]
    ev = open_queue(t, admission_rate=250, max_admission_rate=250)
    monkeypatch.setattr(backpressure, "booking_health", lambda: {"state": "unhealthy"})
    seen = [backpressure.handler({}, None) and int(meta(t, ev)["admission_rate"]) for _ in range(3)]
    assert seen == [175, 122, 85]
    monkeypatch.setattr(backpressure, "booking_health", lambda: {"state": "healthy"})
    for _ in range(10):
        backpressure.handler({}, None)
    assert int(meta(t, ev)["admission_rate"]) == 250  # never above max_admission_rate


def test_paused_queues_and_missing_alb_are_left_alone(aws, monkeypatch):
    real_health = backpressure.booking_health
    t = aws["table"]
    ev = open_queue(t, admission_rate=250, status="paused")
    monkeypatch.setattr(backpressure, "booking_health", lambda: {"state": "unhealthy"})
    backpressure.handler({}, None)
    assert int(meta(t, ev)["admission_rate"]) == 250
    monkeypatch.delenv("ALB_ARN_SUFFIX", raising=False)
    assert real_health()["state"] == "unknown"  # environment down: no ALB, no change


def test_an_organiser_change_in_between_wins(aws):
    t = aws["table"]
    ev = open_queue(t, admission_rate=250, max_admission_rate=250)
    stale = meta(t, ev)
    t.update_item(
        Key={"PK": f"EVENT#{ev}", "SK": "META"},
        UpdateExpression="SET admission_rate = :r, max_admission_rate = :r",
        ExpressionAttributeValues={":r": 100},
    )
    assert backpressure.adjust(stale, "unhealthy") is None  # stale read: no overwrite
    assert int(meta(t, ev)["admission_rate"]) == 100


def test_old_queues_without_max_use_their_rate_as_the_ceiling(aws):
    t = aws["table"]
    ev = open_queue(t, admission_rate=100)
    m = meta(t, ev)
    m.pop("max_admission_rate", None)
    assert backpressure.adjust(m, "healthy") is None  # already at its own ceiling
    assert backpressure.adjust(m, "unhealthy")["to"] == 70
    assert int(meta(t, ev)["max_admission_rate"]) == 100
