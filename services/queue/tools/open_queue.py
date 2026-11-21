"""Dev tool: create (or reset) the waiting room for an event, i.e. the queue's META item.

Until the organiser endpoint exists (Day 6: PATCH /org/events/{id}/queue), this opens a queue:

    python tools/open_queue.py <event-id> --sale-starts-at 2026-11-21T18:00:00+00:00 --rate 125

Uses your AWS profile (AWS_PROFILE=surgegate); table from --table (default surgegate-dev-queue).
"""

import argparse
from datetime import UTC, datetime

import boto3

p = argparse.ArgumentParser()
p.add_argument("event_id")
p.add_argument("--sale-starts-at", default=datetime.now(UTC).isoformat())
p.add_argument("--rate", type=int, default=125, help="buyers admitted per minute")
p.add_argument("--status", default="open", choices=["pre-queue", "open", "paused"])
p.add_argument("--table", default="surgegate-dev-queue")
a = p.parse_args()

boto3.resource("dynamodb").Table(a.table).put_item(
    Item={
        "PK": f"EVENT#{a.event_id}",
        "SK": "META",
        "status": a.status,
        "sale_starts_at": datetime.fromisoformat(a.sale_starts_at).astimezone(UTC).isoformat(),
        "admission_rate": a.rate,
        "next_position": 0,
        "serving_up_to": 0,
        "active": "1",  # listed in the active-queues index (the starter and valve read it)
    }
)
print(f"queue for {a.event_id}: status={a.status}, rate={a.rate}/min, sale at {a.sale_starts_at}")
