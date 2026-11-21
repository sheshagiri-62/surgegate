import pytest

from app.seatmap_csv import MAX_ZONES, SeatMapError, parse_seat_map

HEADER = "section,row,number,zone,price_inr\n"


def csv(*rows: str) -> bytes:
    return (HEADER + "\n".join(rows) + "\n").encode()


def test_valid_map_with_labels_and_paise():
    seats = parse_seat_map(csv("A,1,1,Gold,1500", "A,1,2,gold,1500", "B,10,1,silver,750.50"))
    assert [s.label for s in seats] == ["A-1-1", "A-1-2", "B-10-1"]
    assert [s.price_paise for s in seats] == [150000, 150000, 75050]
    assert {s.zone for s in seats} == {"gold", "silver"}  # zone names are case-insensitive


def test_utf8_bom_from_excel_is_accepted():
    assert len(parse_seat_map(b"\xef\xbb\xbf" + csv("A,1,1,gold,10"))) == 1


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"a,b,c\n1,2,3\n", "header must be exactly"),
        (HEADER.encode(), "no seats"),
        (csv("A,1,1,gold,10", "A,1,1,gold,10"), "seat A-1-1 appears twice"),
        (csv("A,1,1,gold,10", "A,1,2,gold,20"), "zone 'gold' has two different prices"),
        (
            csv("A,1,1,a,1", "A,1,2,b,2", "A,1,3,c,3", "A,1,4,d,4"),
            f"at most {MAX_ZONES} price zones",
        ),
        (csv("A,1,1,gold,10.005"), "more than 2 decimals"),
        (csv("A,1,1,gold,-1"), "must not be negative"),
        (csv("A,1,1,gold,ten"), "is not a number"),
        (csv("A,1,x,gold,10"), "is not a whole number"),
        (csv("A,1,0,gold,10"), "1 or more"),
        (csv("A-B,1,1,gold,10"), "contains '-'"),
        (csv(",1,1,gold,10"), "section is empty"),
        (csv("A,1,1,gold"), "expected 5 columns"),
        (b"\xff\xfe", "not UTF-8"),
    ],
)
def test_invalid_maps_are_rejected_with_a_clear_message(data, message):
    with pytest.raises(SeatMapError, match=message):
        parse_seat_map(data)
