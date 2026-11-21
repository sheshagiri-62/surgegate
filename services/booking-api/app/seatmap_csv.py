"""Seat-map CSV parsing and validation (organiser upload).

Format (header required, UTF-8):

    section,row,number,zone,price_inr
    A,1,1,gold,1500
    A,1,2,gold,1500
    B,10,1,silver,750.50

Rules: up to 3 price zones, one price per zone, every seat unique, price in whole paise,
at most MAX_SEATS seats. Each seat's label is "<section>-<row>-<number>", e.g. "A-1-2".
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

COLUMNS = ("section", "row", "number", "zone", "price_inr")
MAX_SEATS = 20_000
MAX_ZONES = 3


class SeatMapError(ValueError):
    """The upload is invalid; the message is shown to the organiser."""


@dataclass(frozen=True)
class SeatRow:
    section: str
    row: str
    number: int
    zone: str
    price_paise: int

    @property
    def label(self) -> str:
        return f"{self.section}-{self.row}-{self.number}"


def _paise(raw: str, line: int) -> int:
    try:
        value = Decimal(raw.strip())
    except InvalidOperation as exc:
        raise SeatMapError(f"line {line}: price_inr '{raw}' is not a number") from exc
    if value < 0:
        raise SeatMapError(f"line {line}: price_inr must not be negative")
    paise = value * 100
    if paise != paise.to_integral_value():
        raise SeatMapError(f"line {line}: price_inr has more than 2 decimals")
    return int(paise)


def _text(raw: str | None, name: str, line: int, max_len: int) -> str:
    value = (raw or "").strip()
    if not value:
        raise SeatMapError(f"line {line}: {name} is empty")
    if len(value) > max_len or ("-" in value and name in {"section", "row"}):
        raise SeatMapError(f"line {line}: {name} '{value}' is too long or contains '-'")
    return value


def parse_seat_map(data: bytes) -> list[SeatRow]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SeatMapError("file is not UTF-8 text") from exc

    reader = csv.DictReader(io.StringIO(text))
    header = tuple(h.strip().lower() for h in (reader.fieldnames or ()))
    if header != COLUMNS:
        raise SeatMapError(f"header must be exactly: {','.join(COLUMNS)}")

    seats: list[SeatRow] = []
    labels: set[str] = set()
    zone_price: dict[str, int] = {}
    for line, rec in enumerate(reader, start=2):
        if None in rec or any(v is None for v in rec.values()):
            raise SeatMapError(f"line {line}: expected {len(COLUMNS)} columns")
        try:
            number = int(rec["number"].strip())
        except ValueError as exc:
            raise SeatMapError(
                f"line {line}: number '{rec['number']}' is not a whole number"
            ) from exc
        if number < 1:
            raise SeatMapError(f"line {line}: number must be 1 or more")
        seat = SeatRow(
            section=_text(rec["section"], "section", line, 50),
            row=_text(rec["row"], "row", line, 10),
            number=number,
            zone=_text(rec["zone"], "zone", line, 30).lower(),
            price_paise=_paise(rec["price_inr"], line),
        )
        if seat.label in labels:
            raise SeatMapError(f"line {line}: seat {seat.label} appears twice")
        if zone_price.setdefault(seat.zone, seat.price_paise) != seat.price_paise:
            raise SeatMapError(f"line {line}: zone '{seat.zone}' has two different prices")
        if len(zone_price) > MAX_ZONES:
            raise SeatMapError(f"at most {MAX_ZONES} price zones are allowed")
        labels.add(seat.label)
        seats.append(seat)
        if len(seats) > MAX_SEATS:
            raise SeatMapError(f"at most {MAX_SEATS} seats per event")

    if not seats:
        raise SeatMapError("the file has no seats")
    return seats
