"""GET /queue/{event}/serving — the one number every waiting browser polls (blueprint step 5).

"Now serving up to N" is identical for everyone, so it is public (no sign-in) and cacheable:
`Cache-Control: public, max-age=5` lets CloudFront answer 5,000 polls a second from its cache
(pending CloudFront verification; until then API Gateway calls this function directly). The
queue state is also cached in the function for 2 s, so DynamoDB sees at most one read per warm
instance every 2 s.
"""

from __future__ import annotations

from sg_queue.common import edge_only, queue_meta, response, valid_event_id

CACHE_SECONDS = 5
STATE_CACHE_SECONDS = 2


@edge_only
def handler(event, context):
    event_id = (event.get("pathParameters") or {}).get("event")
    if not valid_event_id(event_id):
        return response(404, {"detail": "event not found"}, {"Cache-Control": "public, max-age=60"})
    meta = queue_meta(event_id, max_age=STATE_CACHE_SECONDS)
    if meta is None:
        return response(
            404,
            {"detail": "no waiting room for this event"},
            {"Cache-Control": "public, max-age=10"},
        )
    status = meta.get("status")
    return response(
        200,
        {
            "event_id": event_id,
            "status": status,
            "serving_up_to": int(meta.get("serving_up_to", 0)),
            "admission_rate": 0 if status == "paused" else int(meta.get("admission_rate", 0)),
            "sale_starts_at": meta.get("sale_starts_at"),
        },
        {"Cache-Control": f"public, max-age={CACHE_SECONDS}"},
    )
