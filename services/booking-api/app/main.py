"""SurgeGate booking API.

Routes are added task by task: auth (/me), organiser endpoints, seat map, holds, orders.
"""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth import AnyUser
from app.routes import buyer, orders, organiser, webhooks

APP_VERSION = os.getenv("APP_VERSION", "dev")

app = FastAPI(title="SurgeGate booking API", version=APP_VERSION)
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
