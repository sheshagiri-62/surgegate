"""SurgeGate booking API.

Routes are added task by task: auth (/me), organiser endpoints, seat map, holds, orders.
"""

import os
import random

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.auth import AnyUser
from app.routes import buyer, gate, orders, organiser, tickets, webhooks  # noqa: F401 (gate adds /org routes)
from app.telemetry import setup_logging, setup_tracing

APP_VERSION = os.getenv("APP_VERSION", "dev")

app = FastAPI(title="SurgeGate booking API", version=APP_VERSION)
setup_logging()  # JSON lines (Day 9 Task 3)
setup_tracing(app)  # OpenTelemetry -> X-Ray, only when OTEL_EXPORTER_OTLP_ENDPOINT is set

# Broken-release test (Day 10 Task 2): FAULT_ERROR_RATE=0.5 makes half the requests fail with
# 500 while /healthz stays green, i.e. a bad release that passes its health checks. Only the
# canary's metric analysis can catch it. Never set outside that test (default off).
_FAULT_RATE = float(os.getenv("FAULT_ERROR_RATE", "0") or 0)
if _FAULT_RATE > 0:

    @app.middleware("http")
    async def fault_injection(request: Request, call_next):
        if request.url.path != "/healthz" and random.random() < _FAULT_RATE:  # noqa: S311 - test fault, not security
            return JSONResponse(
                status_code=500, content={"detail": "injected fault (broken-release test)"}
            )
        return await call_next(request)


# CORS: only the origins listed in CORS_ALLOW_ORIGINS (dev: the buyer app on localhost:3000).
# Behind CloudFront the site and API share one origin and the list can be empty.
_origins = [o.strip() for o in os.getenv("CORS_ALLOW_ORIGINS", "").split(",") if o.strip()]
if _origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["Authorization", "Content-Type", "X-Booking-Pass", "Idempotency-Key"],
        allow_credentials=False,  # bearer tokens, no cookies
        max_age=600,
    )
app.include_router(organiser.router)
app.include_router(buyer.router)
app.include_router(orders.book)
app.include_router(orders.mine)
app.include_router(webhooks.router)
app.include_router(tickets.router)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness/readiness probe and the M1 check (https://<api>/healthz)."""
    return {"status": "ok"}


@app.get("/")
def root() -> dict[str, str]:
    return {"service": "booking-api", "version": APP_VERSION}


@app.get("/me")
def me(principal: AnyUser) -> dict:
    """Who am I? Proves the JWT checks: 401 without a valid Cognito access token."""
    return {
        "sub": principal.sub,
        "groups": sorted(principal.groups),
        "tenant_id": str(principal.tenant_id) if principal.tenant_id else None,
    }
