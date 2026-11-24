"""POST /webhooks/razorpay: the payment provider's server-to-server callback (Day 7 Task 4).

No Cognito and no booking pass: the SIGNATURE is the authentication.
  1. body > 64 KB                       -> 413
  2. no X-Razorpay-Signature            -> 400
  3. HMAC-SHA256 over the RAW body does not match (constant-time compare) -> 400, nothing queued
  4. payment.captured / payment.failed  -> SQS, 200 ("queued");  other events -> 200 ("ignored")
  5. SQS unavailable                    -> 503, so the provider retries later
The order worker (app/order_worker.py) does the database work.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from app import payment_queue
from app.routes.orders import Provider

log = logging.getLogger(__name__)
router = APIRouter(tags=["webhooks"])

MAX_BODY = 64 * 1024
QUEUED = {"payment.captured", "payment.failed"}


def _error(status: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail})


@router.post("/webhooks/razorpay", responses={400: {}, 413: {}, 503: {}})
async def razorpay(request: Request, provider: Provider):
    if int(request.headers.get("content-length") or 0) > MAX_BODY:
        return _error(413, "body too large")
    raw = await request.body()  # the exact bytes the provider signed: never re-serialise
    if len(raw) > MAX_BODY:
        return _error(413, "body too large")
    signature = request.headers.get("x-razorpay-signature")
    if not signature:
        return _error(400, "missing signature")
    if not await run_in_threadpool(provider.verify_webhook_signature, raw, signature):
        log.warning("webhook refused: bad signature")
        return _error(400, "invalid signature")
    try:
        kind = json.loads(raw)["event"]
    except (ValueError, KeyError, TypeError):
        return _error(400, "malformed event")
    if kind not in QUEUED:
        return {"status": "ignored", "event": kind}
    event_id = request.headers.get("x-razorpay-event-id", "")
    try:
        await run_in_threadpool(payment_queue.send, raw, event_id, kind)
    except Exception as exc:
        log.error("webhook %s not queued: %s", event_id, type(exc).__name__)
        return _error(503, "try again later")
    log.info("webhook %s (%s) queued", event_id, kind)
    return {"status": "queued"}
