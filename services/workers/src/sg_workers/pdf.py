"""A very small PDF writer for tickets: one A4 page per seat, text + a vector QR code.

No dependencies (the QR matrix comes from segno, pure Python), so the Lambda zip needs no native
builds. Only what tickets need: Helvetica text (WinAnsi; other characters become "?") and
filled squares. Each QR is drawn as one `x y w h re` per dark module, inside a marked block
(`% qr-begin <modules> <module size>` ... `% qr-end`) so tests can read the matrix back.
"""

from __future__ import annotations

PAGE_W, PAGE_H = 595, 842  # A4 in points
QR_SIZE = 320.0  # points (about 11 cm): easy to scan from a phone screen


def _text(s: str) -> str:
    raw = s.encode("cp1252", errors="replace").decode("latin-1")
    return raw.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _page_stream(title: str, lines: list[str], matrix: list[list[int]]) -> bytes:
    out = ["BT /F2 22 Tf 50 780 Td (" + _text(title) + ") Tj ET"]
    y = 745
    for line in lines:
        out.append(f"BT /F1 13 Tf 50 {y} Td ({_text(line)}) Tj ET")
        y -= 20
    n = len(matrix)
    m = QR_SIZE / n
    x0, y0 = (PAGE_W - QR_SIZE) / 2, 120.0
    out.append(f"% qr-begin {n} {m:.4f}")
    out.append("0 g")
    for r, row in enumerate(matrix):
        for c, dark in enumerate(row):
            if dark:
                # PDF y grows upwards: row 0 is the TOP of the code
                out.append(f"{x0 + c * m:.3f} {y0 + (n - 1 - r) * m:.3f} {m:.3f} {m:.3f} re")
    out.append("f")
    out.append("% qr-end")
    out.append("BT /F1 10 Tf 50 90 Td (Show this code at the gate. Each code works once.) Tj ET")
    return ("\n".join(out) + "\n").encode("latin-1")


def ticket_pdf(pages: list[dict]) -> bytes:
    """pages: [{"title": str, "lines": [str], "matrix": [[0/1, ...], ...]}] -> PDF bytes."""
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)  # object numbers start at 1

    catalog = add(b"")  # filled in below
    pages_obj = add(b"")
    f1 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    f2 = add(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>"
    )
    kids = []
    for p in pages:
        stream = _page_stream(p["title"], p["lines"], p["matrix"])
        content = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"endstream")
        kids.append(
            add(
                (
                    f"<< /Type /Page /Parent {pages_obj} 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] "
                    f"/Resources << /Font << /F1 {f1} 0 R /F2 {f2} 0 R >> >> "
                    f"/Contents {content} 0 R >>"
                ).encode()
            )
        )
    objects[catalog - 1] = f"<< /Type /Catalog /Pages {pages_obj} 0 R >>".encode()
    objects[pages_obj - 1] = (
        f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(kids)} >>"
    ).encode()

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        catalog,
        xref,
    )
    return bytes(out)
