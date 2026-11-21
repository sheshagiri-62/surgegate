"""Cross-tenant isolation (plan: "organiser A can never read or change organiser B's events").

The test discovers EVERY organiser route that takes an event id from the app itself, so a route
added later is covered automatically. If a new route has no request recipe below, the test fails
on purpose: whoever adds an organiser route must also say how to attack it.

For each route, organiser B (another tenant) calls it on organiser A's event. The answer must be
404, exactly as for an event that does not exist, and A's event and seats must be byte-for-byte
unchanged in the database afterwards.
"""

import uuid

import pytest
from sqlalchemy import text
from tests.helpers import organiser
from tests.test_organiser import SEATS_CSV, create, upload

from app.main import app

pytestmark = pytest.mark.integration

# How to call each organiser route with a VALID request (so only the tenant check can stop it).
# "prepare": calls the OWNER makes first, so the route has something to act on.
OPEN_QUEUE = ("PUT", "/org/events/{event_id}/queue", {"admission_rate": 100})
RECIPES = {
    ("GET", "/org/events/{event_id}"): {},
    ("PUT", "/org/events/{event_id}/queue"): {"json": {"admission_rate": 100}},
    ("PATCH", "/org/events/{event_id}/queue"): {
        "json": {"admission_rate": 1},  # a write that is valid in any queue state
        "prepare": [OPEN_QUEUE],
    },
    ("GET", "/org/events/{event_id}/queue"): {"prepare": [OPEN_QUEUE]},
    ("PUT", "/org/events/{event_id}/seats"): {
        "content": b"section,row,number,zone,price_inr\nX,1,1,gold,1\n",
        "headers": {"Content-Type": "text/csv"},
    },
}


def organiser_event_routes():
    # From the OpenAPI schema: it lists every route, including those in included routers
    # (app.routes holds router wrappers in this FastAPI version, not flat APIRoutes).
    routes = sorted(
        (method.upper(), path)
        for path, ops in app.openapi()["paths"].items()
        if path.startswith("/org/") and "{event_id}" in path
        for method in ops
    )
    assert routes, "no organiser routes found: route discovery is broken"
    return routes


def snapshot(engine, event_id, queue_table=None):
    """Everything about the event that a cross-tenant call could change (PostgreSQL rows and
    the waiting-room state in DynamoDB)."""
    with engine.connect() as conn:
        event = conn.execute(
            text("SELECT to_jsonb(e) FROM events e WHERE id = :e"), {"e": event_id}
        ).scalar()
        seats = (
            conn.execute(
                text("SELECT to_jsonb(s) FROM seats s WHERE event_id = :e ORDER BY id"),
                {"e": event_id},
            )
            .scalars()
            .all()
        )
    queue = None
    if queue_table is not None:
        queue = queue_table.get_item(Key={"PK": f"EVENT#{event_id}", "SK": "META"}).get("Item")
    return event, seats, queue


def test_every_organiser_route_has_an_attack_recipe():
    missing = set(organiser_event_routes()) - set(RECIPES)
    assert not missing, f"add a cross-tenant recipe for: {sorted(missing)}"


@pytest.mark.parametrize(("method", "path"), organiser_event_routes())
def test_other_tenant_gets_404_and_changes_nothing(api, migrated_engine, queue_table, method, path):
    org_a, org_b = organiser(), organiser()
    event_id = create(api, org_a)["id"]
    assert upload(api, org_a, event_id, SEATS_CSV).status_code == 200
    recipe = RECIPES[(method, path)]
    for prep_method, prep_path, prep_json in recipe.get("prepare", []):
        prep_url = prep_path.replace("{event_id}", event_id)
        r = api.request(prep_method, prep_url, json=prep_json, headers=org_a)
        assert r.status_code < 300, r.text
    before = snapshot(migrated_engine, event_id, queue_table)

    url = path.replace("{event_id}", event_id)
    r = api.request(
        method,
        url,
        content=recipe.get("content"),
        json=recipe.get("json"),
        headers=org_b | recipe.get("headers", {}),
    )
    assert r.status_code == 404, f"{method} {path} as another tenant -> {r.status_code}"
    assert r.json() == {"detail": "event not found"}  # same as a missing event: no leak

    # The same call on a random id gives the identical answer (cannot probe for existence).
    r2 = api.request(
        method,
        path.replace("{event_id}", str(uuid.uuid4())),
        content=recipe.get("content"),
        json=recipe.get("json"),
        headers=org_b | recipe.get("headers", {}),
    )
    assert (r2.status_code, r2.json()) == (r.status_code, r.json())

    assert snapshot(migrated_engine, event_id, queue_table) == before  # A's data untouched

    # And the recipe is valid: the owner CAN make the same call.
    owner = api.request(
        method,
        url,
        content=recipe.get("content"),
        json=recipe.get("json"),
        headers=org_a | recipe.get("headers", {}),
    )
    assert owner.status_code < 300, f"recipe for {method} {path} is wrong: {owner.text}"


def test_lists_never_include_other_tenants_events(api):
    tenants = [uuid.uuid4() for _ in range(3)]
    created = {t: {create(api, organiser(t))["id"] for _ in range(2)} for t in tenants}
    for t in tenants:
        listed = {e["id"] for e in api.get("/org/events", headers=organiser(t)).json()}
        assert listed == created[t]


def test_tenant_in_body_or_query_is_ignored_or_refused(api):
    org_a, tenant_b = organiser(), uuid.uuid4()
    event_b = create(api, organiser(tenant_b))["id"]
    # A query parameter naming tenant B changes nothing.
    listed = api.get(f"/org/events?tenant_id={tenant_b}", headers=org_a).json()
    assert event_b not in {e["id"] for e in listed}
    # A body field naming tenant B is refused outright.
    r = api.post(
        "/org/events",
        headers=org_a,
        json={
            "name": "x",
            "venue": "y",
            "starts_at": "2030-01-02T00:00:00Z",
            "sale_starts_at": "2030-01-01T00:00:00Z",
            "tenant_id": str(tenant_b),
        },
    )
    assert r.status_code == 422


def test_every_event_row_belongs_to_exactly_one_tenant(migrated_engine):
    with migrated_engine.connect() as conn:
        orphans = conn.execute(
            text(
                "SELECT count(*) FROM events e LEFT JOIN tenants t ON t.id = e.tenant_id "
                "WHERE t.id IS NULL"
            )
        ).scalar()
    assert orphans == 0
