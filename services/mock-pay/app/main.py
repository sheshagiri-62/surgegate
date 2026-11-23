"""mock-pay: a Razorpay-shaped mock payment provider (ADR 004). DEV/TEST ONLY.

What it copies from Razorpay (so the booking API code is the same for both):
  POST /v1/orders          HTTP Basic key_id:key_secret -> {"id": "order_...", "entity": "order"}
  GET  /v1/orders/{id}     the order
  webhook                  POST <WEBHOOK_URL> with Razorpay's payload shape, headers
                           X-Razorpay-Signature = hex HMAC-SHA256(webhook_secret, RAW body)
                           X-Razorpay-Event-Id  = unique per event (a re-send repeats it)

Reachability (ALB rule in infra/modules/edge):
  /mockpay/checkout/*      PUBLIC through CloudFront -> ALB (the buyer's browser)
  /v1/*, /mockpay/test/*   cluster only (booking API; kubectl port-forward for scripts/demo)

The checkout page can only pay an EXISTING order, for THAT order's amount (the form carries
no amount), and an order can be paid only once.

Test switches (cluster-only test API): success / fail, delay N seconds, send the webhook twice,
wrong signature, re-send a past webhook.

State is in memory (one replica): a restart forgets mock orders. Dev only.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import logging
import os
import secrets
import string
import threading
import time
import urllib.error
import urllib.request
from typing import Literal
from urllib.parse import parse_qs, urlencode, urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

log = logging.getLogger("mock-pay")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

app = FastAPI(title="mock-pay (Razorpay-shaped, dev only)", version=os.getenv("APP_VERSION", "dev"))

ORDERS: dict[str, dict] = {}
PAYMENTS: dict[str, dict] = {}
EVENTS: dict[str, tuple[str, bytes]] = {}  # payment id -> (event id, raw body) for re-sends
DELIVERIES: dict[str, list[dict]] = {}  # order id -> webhook delivery attempts
LOCK = threading.Lock()
SECRET_CACHE_SECONDS = 300
_secret: tuple[float, dict] | None = None
ALPHABET = string.ascii_letters + string.digits


# --- configuration ------------------------------------------------------------------------
def secret() -> dict:
    """{key_id, key_secret, webhook_secret}: SECRET_JSON (tests) or Secrets Manager SECRET_ID."""
    global _secret
    if raw := os.getenv("SECRET_JSON"):
        return json.loads(raw)
    if _secret and time.monotonic() - _secret[0] < SECRET_CACHE_SECONDS:
        return _secret[1]
    import boto3

    sm = boto3.client("secretsmanager", region_name=os.getenv("AWS_REGION", "ap-south-1"))
    value = json.loads(sm.get_secret_value(SecretId=os.environ["SECRET_ID"])["SecretString"])
    _secret = (time.monotonic(), value)
    return value


def allowed_origins() -> set[str]:
    raw = os.getenv("CALLBACK_ALLOW_ORIGINS", "")
    return {o.strip().rstrip("/") for o in raw.split(",") if o.strip()}


def callback_allowed(url: str) -> bool:
    if not url:
        return True
    p = urlsplit(url)
    return f"{p.scheme}://{p.netloc}" in allowed_origins()


def new_id(prefix: str) -> str:
    return prefix + "".join(secrets.choice(ALPHABET) for _ in range(14))


def sign(raw_body: bytes, webhook_secret: str) -> str:
    return hmac.new(webhook_secret.encode(), raw_body, hashlib.sha256).hexdigest()


def razorpay_error(status: int, description: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": "BAD_REQUEST_ERROR", "description": description}},
    )


def check_auth(request: Request) -> None:
    s = secret()
    expected = base64.b64encode(f"{s['key_id']}:{s['key_secret']}".encode()).decode()
    given = request.headers.get("authorization", "").removeprefix("Basic ")
    if not hmac.compare_digest(given, expected):
        raise HTTPException(401, "Authentication failed")


@app.exception_handler(HTTPException)
async def _http_error(request: Request, exc: HTTPException):
    if request.url.path.startswith("/mockpay/checkout/"):
        return HTMLResponse(
            page("Payment", f"<p>{html.escape(str(exc.detail))}</p>"), exc.status_code
        )
    return razorpay_error(exc.status_code, str(exc.detail))


# --- Razorpay-shaped API (cluster only) ---------------------------------------------------
class OrderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: int = Field(ge=100)  # paise; Razorpay's minimum is 100 (INR 1)
    currency: Literal["INR"] = "INR"
    receipt: str = Field(max_length=40)
    notes: dict[str, str] = Field(default_factory=dict, max_length=15)


@app.post("/v1/orders")
def create_order(body: OrderIn, request: Request):
    check_auth(request)
    if not callback_allowed(body.notes.get("callback_url", "")):
        return razorpay_error(400, "callback_url is not an allowed origin")
    order = {
        "id": new_id("order_"),
        "entity": "order",
        "amount": body.amount,
        "amount_paid": 0,
        "amount_due": body.amount,
        "currency": body.currency,
        "receipt": body.receipt,
        "status": "created",
        "attempts": 0,
        "notes": body.notes,
        "created_at": int(time.time()),
    }
    with LOCK:
        ORDERS[order["id"]] = order
        DELIVERIES[order["id"]] = []
    log.info("order %s created: %d paise, receipt %s", order["id"], body.amount, body.receipt)
    return order


@app.get("/v1/orders/{order_id}")
def get_order(order_id: str, request: Request):
    check_auth(request)
    if order_id not in ORDERS:
        raise HTTPException(404, "The id provided does not exist")
    return ORDERS[order_id]


# --- paying ---------------------------------------------------------------------------------
def http_send(url: str, raw: bytes, headers: dict[str, str]) -> int:
    req = urllib.request.Request(url, data=raw, headers=headers, method="POST")  # noqa: S310 - http(s) URL from config
    try:
        with urllib.request.urlopen(req, timeout=10) as r:  # noqa: S310 - http(s) URL from config
            return r.status
    except urllib.error.HTTPError as err:
        return err.code


def spawn(fn, *args) -> None:
    threading.Thread(target=fn, args=args, daemon=True).start()


def deliver(order_id: str, event_id: str, raw: bytes, times: int, delay: int, bad_sig: bool):
    """Send the SAME event (same body, same event id) `times` times, like Razorpay retries."""
    if delay:
        time.sleep(delay)
    url = os.getenv("WEBHOOK_URL", "")
    signature = sign(raw, "wrong-secret" if bad_sig else secret()["webhook_secret"])
    headers = {
        "Content-Type": "application/json",
        "X-Razorpay-Signature": signature,
        "X-Razorpay-Event-Id": event_id,
        "User-Agent": "mock-pay (Razorpay-shaped)",
    }
    for attempt in range(1, times + 1):
        record = {
            "at": int(time.time()),
            "attempt": attempt,
            "event_id": event_id,
            "bad_signature": bad_sig,
        }
        if not url:
            record["result"] = "skipped: WEBHOOK_URL not set"
        else:
            try:
                record["result"] = http_send(url, raw, headers)
            except (urllib.error.URLError, TimeoutError) as exc:
                record["result"] = f"error: {type(exc).__name__}"
        with LOCK:
            DELIVERIES.setdefault(order_id, []).append(record)
        log.info(
            "webhook %s attempt %d for %s -> %s", event_id, attempt, order_id, record["result"]
        )


def pay(
    order_id: str,
    outcome: Literal["success", "fail"],
    delay: int = 0,
    duplicate: bool = False,
    bad_signature: bool = False,
) -> dict:
    with LOCK:
        order = ORDERS.get(order_id)
        if order is None:
            raise HTTPException(404, "This order does not exist")
        if order["status"] == "paid":
            raise HTTPException(409, "This order is already paid")
        captured = outcome == "success"
        payment = {
            "id": new_id("pay_"),
            "entity": "payment",
            "amount": order["amount"],  # always the order's own amount
            "currency": order["currency"],
            "status": "captured" if captured else "failed",
            "order_id": order_id,
            "method": "upi",
            "captured": captured,
            "description": order["receipt"],
            "error_code": None if captured else "BAD_REQUEST_ERROR",
            "error_description": None if captured else "Payment failed (mock)",
            "notes": order["notes"],
            "created_at": int(time.time()),
        }
        order["attempts"] += 1
        if captured:
            order.update(status="paid", amount_paid=order["amount"], amount_due=0)
        else:
            order["status"] = "attempted"
        PAYMENTS[payment["id"]] = payment
        event = {
            "entity": "event",
            "account_id": "acc_mock0000000001",
            "event": "payment.captured" if captured else "payment.failed",
            "contains": ["payment"],
            "payload": {"payment": {"entity": payment}},
            "created_at": int(time.time()),
        }
        event_id = new_id("evt_")
        raw = json.dumps(event, separators=(",", ":")).encode()
        EVENTS[payment["id"]] = (event_id, raw)
    log.info("order %s %s by %s", order_id, payment["status"], payment["id"])
    spawn(deliver, order_id, event_id, raw, 2 if duplicate else 1, delay, bad_signature)
    return {"payment": payment, "event_id": event_id}


# --- public checkout page (through CloudFront) --------------------------------------------
CSS = """
body { font-family: system-ui, sans-serif; max-width: 28rem; margin: 3rem auto;
  padding: 0 1rem; color: #0f172a }
.card { border: 1px solid #cbd5e1; border-radius: .75rem; padding: 1.25rem }
.tag { display: inline-block; background: #fef3c7; color: #92400e; border-radius: .25rem;
  padding: .1rem .4rem; font-size: .8rem }
button { width: 100%; padding: .7rem; margin-top: .6rem; border: 0; border-radius: .5rem;
  font-size: 1rem; cursor: pointer }
.ok { background: #059669; color: #fff }
.no { background: #e2e8f0; color: #0f172a }
@media (prefers-color-scheme: dark) {
  body { background: #020617; color: #e2e8f0 }
  .card { border-color: #334155 }
  .no { background: #334155; color: #e2e8f0 }
}
"""


def page(title: str, body: str) -> str:
    t = html.escape(title)
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{t}</title><style>{CSS}</style></head><body>"
        '<p class="tag">TEST MODE &middot; mock payment provider (no real money)</p>'
        f"<h1>{t}</h1>{body}</body></html>"
    )


@app.get("/mockpay/checkout/{order_id}", response_class=HTMLResponse)
def checkout_page(order_id: str):
    order = ORDERS.get(order_id)
    if order is None:
        raise HTTPException(404, "This order does not exist (mock orders are lost on restart).")
    rupees = f"&#8377;{order['amount'] / 100:,.2f}"
    if order["status"] == "paid":
        return page("Already paid", f"<div class='card'><p>{rupees} was already paid.</p></div>")
    action = f"/mockpay/checkout/{html.escape(order_id)}/pay"
    return page(
        "Pay SurgeGate",
        f"""<div class="card"><p>Amount <strong>{rupees}</strong></p>
<p>Order <code>{html.escape(order_id)}</code></p>
<form method="post" action="{action}"><input type="hidden" name="outcome" value="success">
<button class="ok" type="submit">Pay success</button></form>
<form method="post" action="{action}"><input type="hidden" name="outcome" value="fail">
<button class="no" type="submit">Pay fail</button></form></div>""",
    )


@app.post("/mockpay/checkout/{order_id}/pay")
async def checkout_pay(order_id: str, request: Request):
    form = parse_qs((await request.body()).decode(), max_num_fields=5)
    outcome = (form.get("outcome") or [""])[0]
    if outcome not in ("success", "fail"):
        raise HTTPException(400, "outcome must be success or fail")
    result = pay(order_id, outcome)  # amount comes from the stored order, never the form
    payment, order = result["payment"], ORDERS[order_id]
    callback = order["notes"].get("callback_url", "")
    if callback and callback_allowed(callback):
        if payment["captured"]:
            params = {
                "razorpay_payment_id": payment["id"],
                "razorpay_order_id": order_id,
                # Razorpay's checkout signature: HMAC(key_secret, "order_id|payment_id")
                "razorpay_signature": hmac.new(
                    secret()["key_secret"].encode(),
                    f"{order_id}|{payment['id']}".encode(),
                    hashlib.sha256,
                ).hexdigest(),
            }
        else:
            params = {"payment": "failed"}
        sep = "&" if urlsplit(callback).query else "?"
        return RedirectResponse(f"{callback}{sep}{urlencode(params)}", status_code=303)
    word = "captured" if payment["captured"] else "failed"
    return HTMLResponse(page(f"Payment {word}", "<p>You can close this page.</p>"))


# --- test API (cluster only: kubectl port-forward) ----------------------------------------
class TestPay(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: str
    outcome: Literal["success", "fail"] = "success"
    delay_seconds: int = Field(default=0, ge=0, le=900)
    duplicate: bool = False  # send the same webhook twice
    bad_signature: bool = False


class Resend(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bad_signature: bool = False
    delay_seconds: int = Field(default=0, ge=0, le=900)


@app.post("/mockpay/test/pay")
def test_pay(body: TestPay):
    return pay(body.order_id, body.outcome, body.delay_seconds, body.duplicate, body.bad_signature)


@app.post("/mockpay/test/webhooks/{payment_id}/resend")
def test_resend(payment_id: str, body: Resend):
    """Re-send a past webhook exactly (same body and event id): the duplicate-webhook demo."""
    if payment_id not in EVENTS:
        raise HTTPException(404, "unknown payment")
    event_id, raw = EVENTS[payment_id]
    spawn(
        deliver,
        PAYMENTS[payment_id]["order_id"],
        event_id,
        raw,
        1,
        body.delay_seconds,
        body.bad_signature,
    )
    return {"resent": event_id}


@app.get("/mockpay/test/orders/{order_id}")
def test_order(order_id: str):
    if order_id not in ORDERS:
        raise HTTPException(404, "unknown order")
    return {
        "order": ORDERS[order_id],
        "payments": [p for p in PAYMENTS.values() if p["order_id"] == order_id],
        "deliveries": DELIVERIES.get(order_id, []),
    }


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
