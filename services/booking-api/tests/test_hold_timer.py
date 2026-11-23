"""Every committed hold starts its 10-minute timer; if the timer can't start, the seats go back."""

import json

import pytest
from tests.test_holds import hold, open_event, statuses

from app import hold_timer

pytestmark = pytest.mark.integration


class FakeSfn:
    def __init__(self, fail=None):
        self.calls, self.fail = [], fail

    def start_execution(self, **kw):
        self.calls.append(kw)
        if self.fail:
            raise type(self.fail, (Exception,), {})("boom")


@pytest.fixture
def timer(monkeypatch):
    def install(fail=None):
        fake = FakeSfn(fail)
        monkeypatch.setenv("HOLD_TIMER_ARN", "arn:aws:states:ap-south-1:1:stateMachine:hold-timer")
        monkeypatch.setattr(hold_timer, "_sfn", lambda: fake)
        return fake

    return install


def test_each_hold_starts_one_timer_named_by_the_hold(api, timer):
    fake = timer()
    event_id, seats = open_event(api)
    r = hold(api, event_id, seats[:2])
    assert r.status_code == 201
    (call,) = fake.calls
    assert call["name"] == r.json()["hold_id"]  # same name twice = rejected by Step Functions
    assert json.loads(call["input"]) == {
        "hold_id": r.json()["hold_id"],
        "event_id": event_id,
        "wait_seconds": 600,
    }


def test_already_started_counts_as_started(api, timer):
    timer(fail="ExecutionAlreadyExists")
    event_id, seats = open_event(api)
    assert hold(api, event_id, seats[:1]).status_code == 201


def test_timer_failure_gives_the_seats_back(api, timer):
    timer(fail="ServiceUnavailable")
    event_id, seats = open_event(api)
    r = hold(api, event_id, seats[:2])
    assert r.status_code == 503
    st = statuses(api, event_id)
    assert st[seats[0]] == "available" and st[seats[1]] == "available"
