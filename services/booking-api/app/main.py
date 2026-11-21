"""SurgeGate booking API.

Routes are added task by task (Phase 2): auth (/me), organiser endpoints, seat map, holds.
"""

import os

from fastapi import FastAPI

from app.auth import AnyUser
from app.routes import buyer, organiser

APP_VERSION = os.getenv("APP_VERSION", "dev")

app = FastAPI(title="SurgeGate booking API", version=APP_VERSION)
app.include_router(organiser.router)
app.include_router(buyer.router)


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
