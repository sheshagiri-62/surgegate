"""Ticket tokens (shared vector with services/workers) and GET /me/tickets."""

import uuid

import pytest
from sqlalchemy import text
from tests.helpers import buyer
from tests.test_payment_flow import drain, flow, held_order, post, webhook_body  # noqa: F401

from app import ticket_token
from app.routes import tickets as tickets_route

KEY = {"kid": "vector", "key": "k" * 32}
PAYLOAD = {
    "typ": "ticket",
    "tid": "11111111-1111-1111-1111-111111111111",
    "ord": "22222222-2222-2222-2222-222222222222",
    "ev": "33333333-3333-3333-3333-333333333333",
    "seat": {"id": "44444444-4444-4444-4444-444444444444", "label": "A-1-3"},
    "iat": 1795468958,
}
# Same string as services/workers/tests/test_ticket_token_pdf.py: the two copies must agree.
VECTOR = (
    "eyJldiI6IjMzMzMzMzMzLTMzMzMtMzMzMy0zMzMzLTMzMzMzMzMzMzMzMyIsImlhdCI6MTc5NTQ2ODk1OCwia2lkIjoi"
    "dmVjdG9yIiwib3JkIjoiMjIyMjIyMjItMjIyMi0yMjIyLTIyMjItMjIyMjIyMjIyMjIyIiwic2VhdCI6eyJpZCI6IjQ0"
    "NDQ0NDQ0LTQ0NDQtNDQ0NC00NDQ0LTQ0NDQ0NDQ0NDQ0NCIsImxhYmVsIjoiQS0xLTMifSwidGlkIjoiMTExMTExMTEt"
    "MTExMS0xMTExLTExMTEtMTExMTExMTExMTExIiwidHlwIjoidGlja2V0In0.vt9FtVohOkTRC0EhwYQPqpuLMaTRcf-_zOGKRUIyoEg"
)


def test_shared_vector_signs_and_verifies():
    assert ticket_token.sign(PAYLOAD, KEY) == VECTOR
    assert (
        ticket_token.verify(VECTOR, {"vector": KEY["key"]}, PAYLOAD["ev"])["seat"]["label"]
        == "A-1-3"
    )
    with pytest.raises(ValueError, match="forged"):
        ticket_token.verify(VECTOR, {"vector": "other"})


@pytest.mark.integration
def test_my_tickets_lists_only_my_paid_orders_with_a_short_link(flow, monkeypatch):  # noqa: F811
    monkeypatch.setattr(
        tickets_route, "presign", lambda key: f"https://s3.test/{key}?X-Amz-Expires=300"
    )
    event_id, _, headers, h, o = held_order(flow)
    post(flow, webhook_body(o))
    drain(flow)  # -> paid
    key = f"tickets/{event_id}/{o['order_id']}.pdf"
    with flow.engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO tickets (id, order_item_id, order_id, event_id, seat_id, kid, s3_key) "
                "SELECT gen_random_uuid(), i.id, i.order_id, :e, i.seat_id, 'k1', :key "
                "FROM order_items i WHERE i.order_id = :o"
            ),
            {"e": event_id, "o": o["order_id"], "key": key},
        )
    mine = flow.api.get("/me/tickets", headers=headers).json()
    (order,) = mine["orders"]
    assert order["order_id"] == o["order_id"] and len(order["tickets"]) == 2
    assert order["pdf_url"] == f"https://s3.test/{key}?X-Amz-Expires=300"
    assert mine["link_expires_in"] == 300
    assert flow.api.get("/me/tickets", headers=buyer()).json()["orders"] == []  # someone else
    assert flow.api.get("/me/tickets").status_code == 401


def test_presigned_link_expires_in_5_minutes(monkeypatch):
    monkeypatch.setenv("TICKETS_BUCKET", "surgegate-test-tickets")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    tickets_route._s3.cache_clear()
    url = tickets_route.presign(f"tickets/e/{uuid.uuid4()}.pdf")
    tickets_route._s3.cache_clear()
    assert "X-Amz-Expires=300" in url and "surgegate-test-tickets" in url
