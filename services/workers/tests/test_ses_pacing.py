"""SES send pacing (demo load tests: sandbox rate 1 email/s)."""

from sg_workers import ticket_worker


def test_pace_sends_keeps_the_interval(monkeypatch):
    clock, slept = [100.0], []

    def sleep(seconds):
        slept.append(round(seconds, 3))
        clock[0] += seconds

    monkeypatch.setenv("SES_MIN_SEND_INTERVAL_SECONDS", "2")
    monkeypatch.setattr(ticket_worker, "_last_send", 0.0)
    ticket_worker.pace_sends(now=lambda: clock[0], sleep=sleep)  # first send: no wait
    clock[0] += 0.5
    ticket_worker.pace_sends(now=lambda: clock[0], sleep=sleep)  # 0.5 s later: waits 1.5 s
    assert slept == [1.5]


def test_pace_sends_off_by_default(monkeypatch):
    monkeypatch.delenv("SES_MIN_SEND_INTERVAL_SECONDS", raising=False)
    ticket_worker.pace_sends(sleep=lambda s: (_ for _ in ()).throw(AssertionError("slept")))
