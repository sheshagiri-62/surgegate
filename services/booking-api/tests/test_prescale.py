"""Pre-scaling: HPA minReplicas up 15 minutes before a sale, back down an hour after it started."""

from datetime import UTC, datetime, timedelta

import pytest

from app import prescale


class FakeKube:
    def __init__(self, current):
        self.current, self.patched = current, []

    def hpa_min(self, name):
        return self.current

    def set_hpa_min(self, name, value):
        self.patched.append((name, value))
        self.current = value


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("BASE_MIN_REPLICAS", "2")
    monkeypatch.setenv("PRESCALE_MIN_REPLICAS", "4")


def test_desired_min():
    assert prescale.desired_min([], 2, 4) == 2
    assert prescale.desired_min([{"id": "x"}], 2, 4) == 4


def test_upcoming_sale_raises_the_minimum_once(env, monkeypatch):
    monkeypatch.setattr(prescale, "sales_in_window", lambda *a: [{"id": "e1"}])
    kube = FakeKube(2)
    assert prescale.run(None, kube)["changed"] is True
    assert prescale.run(None, kube)["changed"] is False  # already there: no second patch
    assert kube.patched == [("booking-api", 4)]


def test_no_sale_puts_it_back(env, monkeypatch):
    monkeypatch.setattr(prescale, "sales_in_window", lambda *a: [])
    kube = FakeKube(4)
    prescale.run(None, kube)
    assert kube.patched == [("booking-api", 2)]


@pytest.mark.integration
def test_window_query(migrated_engine):
    """15 minutes ahead and 60 minutes after the start count; outside that, nothing."""
    from sqlalchemy import text
    from sqlalchemy.orm import Session

    now = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
    with migrated_engine.begin() as c:
        tenant = c.execute(
            text("INSERT INTO tenants (id, name) VALUES (gen_random_uuid(), 't') RETURNING id")
        ).scalar()
        for name, delta in (("soon", 10), ("too-early", 20), ("running", -50), ("over", -70)):
            c.execute(
                text(
                    "INSERT INTO events (id, tenant_id, name, venue, starts_at, sale_starts_at, "
                    "per_buyer_limit) "
                    "VALUES (gen_random_uuid(), :t, :n, 'v', :s + interval '1 day', :s, 4)"
                ),
                {"t": tenant, "n": f"prescale-{name}", "s": now + timedelta(minutes=delta)},
            )
    with Session(migrated_engine) as db:
        names = {s["name"] for s in prescale.sales_in_window(db, now, 15, 60)}
    assert {n for n in names if n.startswith("prescale-")} == {"prescale-soon", "prescale-running"}
