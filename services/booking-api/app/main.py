"""SurgeGate booking API (hello-world stage, Day 2).

Seat map, holds and orders arrive in Phase 2; for now the service only proves the
build → ECR → Argo CD → EKS → ALB path.
"""

import os

from fastapi import FastAPI

APP_VERSION = os.getenv("APP_VERSION", "dev")

app = FastAPI(title="SurgeGate booking API", version=APP_VERSION)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness/readiness probe and the M1 check (https://<api>/healthz)."""
    return {"status": "ok"}


@app.get("/")
def root() -> dict[str, str]:
    return {"service": "booking-api", "version": APP_VERSION}
