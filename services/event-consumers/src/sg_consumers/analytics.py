"""analytics consumer (Day 8 Task 3b): sale events -> S3 (gzip JSON lines) for Athena.

Kinesis event source (in order, batched up to 60 s). Each batch is written as one object per
hour of event time:

    s3://<analytics bucket>/events/dt=YYYY-MM-DD/hour=HH/<shard>-<first seq>-<last seq>.json.gz

The key is DETERMINISTIC (shard + sequence range), so a retried batch overwrites the same
object instead of adding a copy. A bisected batch can still repeat records under another key,
so the saved queries de-duplicate by `id` (each envelope's unique message id).

Each line is a flat row (Glue table `sale_events`, partition projection on dt/hour):
    id, type, sale_event_id, at, seq, sub, seats, amount_paise, data (the raw JSON)
"""

from __future__ import annotations

import base64
import gzip
import json
import logging
import os
from collections import defaultdict

from sg_consumers.common import OK, client, failure

log = logging.getLogger()
log.setLevel(logging.INFO)


def row(envelope: dict, seq: str) -> dict:
    d = envelope.get("data") or {}
    seats = d.get("seats") or d.get("released_seats") or d.get("tickets") or []
    return {
        "id": envelope.get("id"),
        "type": envelope.get("type"),
        "sale_event_id": envelope.get("sale_event_id"),
        "at": envelope.get("at"),
        "seq": seq,
        "sub": d.get("sub"),
        "seats": len(seats) if isinstance(seats, list) else None,
        "amount_paise": d.get("amount_paise"),
        "data": json.dumps(d, separators=(",", ":"), sort_keys=True),
    }


def objects(event: dict) -> dict[str, bytes]:
    """{s3 key: gzip body} for one Kinesis batch, grouped by the event-time hour."""
    groups: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for r in event.get("Records", []):
        k = r["kinesis"]
        shard = r.get("eventID", "shardId-unknown:").split(":")[0]
        env = json.loads(base64.b64decode(k["data"]))
        at = env.get("at") or "1970-01-01T00:00:00"
        groups[(shard, at[:10], at[11:13])].append(row(env, k["sequenceNumber"]))
    out = {}
    for (shard, dt, hour), rows in groups.items():
        key = f"events/dt={dt}/hour={hour}/{shard}-{rows[0]['seq']}-{rows[-1]['seq']}.json.gz"
        body = "".join(json.dumps(x, separators=(",", ":")) + "\n" for x in rows).encode()
        out[key] = gzip.compress(body, mtime=0)  # mtime=0: the same batch gives the same bytes
    return out


def handler(event, context):
    recs = event.get("Records", [])
    if not recs:
        return OK
    try:
        files = objects(event)
        s3 = client("s3")
        for key, body in files.items():
            s3.put_object(
                Bucket=os.environ["ANALYTICS_BUCKET"],
                Key=key,
                Body=body,
                ContentType="application/x-ndjson",
                ContentEncoding="gzip",
                ServerSideEncryption="aws:kms",
            )
    except Exception as exc:
        log.error(json.dumps({"error": repr(exc)}))
        return failure(recs[0]["kinesis"]["sequenceNumber"])  # retry the whole batch (same keys)
    log.info(json.dumps({"records": len(recs), "objects": len(files)}))
    return OK
