"""Ticket tokens (shared vector with the booking API) and the PDF: one page and one QR per seat,
and the QR drawn in the PDF is exactly segno's matrix for a freshly signed token."""

import re

import pytest
import segno

from sg_workers import pdf, ticket_token, ticket_worker

KEY = {"kid": "vector", "key": "k" * 32}
PAYLOAD = {
    "typ": "ticket",
    "tid": "11111111-1111-1111-1111-111111111111",
    "ord": "22222222-2222-2222-2222-222222222222",
    "ev": "33333333-3333-3333-3333-333333333333",
    "seat": {"id": "44444444-4444-4444-4444-444444444444", "label": "A-1-3"},
    "iat": 1795468958,
}
# The booking API's tests (tests/test_tickets.py) check the SAME string.
VECTOR = (
    "eyJldiI6IjMzMzMzMzMzLTMzMzMtMzMzMy0zMzMzLTMzMzMzMzMzMzMzMyIsImlhdCI6MTc5NTQ2ODk1OCwia2lkIjoi"
    "dmVjdG9yIiwib3JkIjoiMjIyMjIyMjItMjIyMi0yMjIyLTIyMjItMjIyMjIyMjIyMjIyIiwic2VhdCI6eyJpZCI6IjQ0"
    "NDQ0NDQ0LTQ0NDQtNDQ0NC00NDQ0LTQ0NDQ0NDQ0NDQ0NCIsImxhYmVsIjoiQS0xLTMifSwidGlkIjoiMTExMTExMTEt"
    "MTExMS0xMTExLTExMTEtMTExMTExMTExMTExIiwidHlwIjoidGlja2V0In0.vt9FtVohOkTRC0EhwYQPqpuLMaTRcf-_zOGKRUIyoEg"
)


def test_token_matches_the_shared_vector_and_is_deterministic():
    assert ticket_token.sign(PAYLOAD, KEY) == VECTOR
    assert ticket_token.sign(dict(reversed(list(PAYLOAD.items()))), KEY) == VECTOR  # key order


def test_verify_accepts_the_real_token_only():
    keys = {"vector": KEY["key"]}
    assert ticket_token.verify(VECTOR, keys, PAYLOAD["ev"])["tid"] == PAYLOAD["tid"]
    body, sig = VECTOR.split(".")
    forged = ticket_token.sign(
        PAYLOAD | {"seat": {"id": "x", "label": "VIP-1"}}, {"kid": "vector", "key": "attacker"}
    )
    cases = {
        "forged": forged,
        "tampered body": body[:-2] + "AA." + sig,
        "garbage": "not-a-ticket",
        "unknown key": ticket_token.sign(PAYLOAD, {"kid": "old", "key": "k" * 32}),
        "not a ticket": ticket_token.sign(PAYLOAD | {"typ": "pass"}, KEY),
    }
    for name, token in cases.items():
        with pytest.raises(ValueError):
            ticket_token.verify(token, keys)
            pytest.fail(name)
    with pytest.raises(ValueError, match="another event"):
        ticket_token.verify(VECTOR, keys, "99999999-9999-9999-9999-999999999999")


def read_qr_blocks(data: bytes) -> list[list[list[int]]]:
    """Rebuild each QR matrix from the PDF's `x y w h re` squares."""
    text = data.decode("latin-1")
    out = []
    for block in re.findall(r"% qr-begin (\d+) ([\d.]+)\n(.*?)% qr-end", text, re.S):
        n, m = int(block[0]), float(block[1])
        rects = re.findall(r"([\d.]+) ([\d.]+) [\d.]+ [\d.]+ re", block[2])
        xs = [float(x) for x, _ in rects]
        ys = [float(y) for _, y in rects]
        x0 = min(xs) - round((min(xs) - (pdf.PAGE_W - pdf.QR_SIZE) / 2) / m) * m
        y0 = 120.0
        grid = [[0] * n for _ in range(n)]
        for x, y in zip(xs, ys, strict=True):
            c = round((x - x0) / m)
            r = n - 1 - round((y - y0) / m)
            grid[r][c] = 1
        out.append(grid)
    return out


def test_pdf_has_one_page_and_one_correct_qr_per_seat():
    order = {
        "id": PAYLOAD["ord"],
        "event_id": PAYLOAD["ev"],
        "event_name": "SurgeGate Fest",
        "venue": "Mumbai",
        "starts_at": __import__("datetime").datetime(2026, 12, 1, 18, 30),
        "paid_at": __import__("datetime").datetime.fromtimestamp(
            PAYLOAD["iat"], tz=__import__("datetime").UTC
        ),
    }
    tickets = [
        {
            "ticket_id": PAYLOAD["tid"],
            "seat_id": PAYLOAD["seat"]["id"],
            "label": "A-1-3",
            "section": "A",
            "row": "1",
            "number": 3,
        },
        {
            "ticket_id": "55555555-5555-5555-5555-555555555555",
            "seat_id": "66666666-6666-6666-6666-666666666666",
            "label": "A-1-4",
            "section": "A",
            "row": "1",
            "number": 4,
        },
    ]
    data, tokens = ticket_worker.render(order, tickets, KEY)
    assert data.startswith(b"%PDF-1.4") and data.rstrip().endswith(b"%%EOF")
    assert data.count(b"/Type /Page ") == 2 and b"/Count 2" in data
    assert tokens[0] == VECTOR  # the first seat's QR carries exactly the shared vector
    drawn = read_qr_blocks(data)
    assert len(drawn) == 2
    for grid, t in zip(drawn, tickets, strict=True):
        # Regenerate the token independently and compare segno's matrix with what was drawn.
        token = ticket_token.sign(
            {
                "typ": "ticket",
                "tid": t["ticket_id"],
                "ord": order["id"],
                "ev": order["event_id"],
                "seat": {"id": t["seat_id"], "label": t["label"]},
                "iat": PAYLOAD["iat"],
            },
            KEY,
        )
        expected = [list(r) for r in segno.make(token, error="m").matrix_iter(scale=1, border=4)]
        assert grid == expected


def test_pdf_xref_offsets_point_at_objects():
    data = pdf.ticket_pdf([{"title": "T (x)", "lines": ["café"], "matrix": [[1, 0], [0, 1]]}])
    xref = int(re.search(rb"startxref\n(\d+)", data).group(1))
    offsets = [int(o) for o in re.findall(rb"(\d{10}) 00000 n", data[xref:])]
    for i, off in enumerate(offsets, start=1):
        assert data[off:].startswith(b"%d 0 obj" % i)
    assert b"(T \\(x\\))" in data  # parentheses escaped
