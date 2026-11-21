"""Organiser waiting-room controls: open (pre-queue or open), pause, resume, rate."""

from datetime import UTC, datetime, timedelta

import pytest
from tests.helpers import buyer, organiser
from tests.test_organiser import create

pytestmark = pytest.mark.integration


def url(event_id):
    return f"/org/events/{event_id}/queue"


def test_opening_before_the_sale_gives_a_pre_queue(api, queue_table):
    org = organiser()
    ev = create(api, org)  # sale starts tomorrow
    r = api.put(url(ev["id"]), json={"admission_rate": 125}, headers=org)
    assert r.status_code == 201, r.text
    assert r.json() | {"sale_starts_at": "x"} == {
        "status": "pre-queue",
        "admission_rate": 125,
        "sale_starts_at": "x",
        "in_line": 0,
        "admitted": 0,
        "waiting": 0,
    }
    item = queue_table.get_item(Key={"PK": f"EVENT#{ev['id']}", "SK": "META"})["Item"]
    assert item["active"] == "1"  # the starter and the valve will find it


def test_opening_after_the_sale_started_is_open_at_once(api):
    org = organiser()
    now = datetime.now(UTC)
    ev = create(
        api,
        org,
        sale_starts_at=(now - timedelta(minutes=1)).isoformat(),
        starts_at=(now + timedelta(days=1)).isoformat(),
    )
    assert (
        api.put(url(ev["id"]), json={"admission_rate": 50}, headers=org).json()["status"] == "open"
    )


def test_open_twice_is_409(api):
    org = organiser()
    ev = create(api, org)
    api.put(url(ev["id"]), json={"admission_rate": 125}, headers=org)
    r = api.put(url(ev["id"]), json={"admission_rate": 1}, headers=org)
    assert r.status_code == 409


def test_pause_resume_and_rate(api):
    org = organiser()
    now = datetime.now(UTC)
    ev = create(
        api,
        org,
        sale_starts_at=(now - timedelta(minutes=1)).isoformat(),
        starts_at=(now + timedelta(days=1)).isoformat(),
    )
    api.put(url(ev["id"]), json={"admission_rate": 125}, headers=org)
    r = api.patch(url(ev["id"]), json={"action": "pause"}, headers=org)
    assert r.json()["status"] == "paused"
    assert api.patch(url(ev["id"]), json={"action": "pause"}, headers=org).status_code == 409
    r = api.patch(url(ev["id"]), json={"action": "resume", "admission_rate": 300}, headers=org)
    assert (r.json()["status"], r.json()["admission_rate"]) == ("open", 300)
    assert api.get(url(ev["id"]), headers=org).json()["admission_rate"] == 300


def test_cannot_pause_a_pre_queue(api):
    org = organiser()
    ev = create(api, org)
    api.put(url(ev["id"]), json={"admission_rate": 125}, headers=org)
    assert api.patch(url(ev["id"]), json={"action": "pause"}, headers=org).status_code == 409


def test_validation_and_roles(api):
    org = organiser()
    ev = create(api, org)
    assert api.put(url(ev["id"]), json={"admission_rate": 0}, headers=org).status_code == 422
    assert api.patch(url(ev["id"]), json={}, headers=org).status_code == 422
    assert api.patch(url(ev["id"]), json={"action": "fly"}, headers=org).status_code == 422
    assert api.get(url(ev["id"]), headers=org).status_code == 404  # not opened yet
    assert api.put(url(ev["id"]), json={"admission_rate": 9}, headers=buyer()).status_code == 403
