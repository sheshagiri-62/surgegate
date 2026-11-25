"""Pre-scaling (Day 10 Task 1, blueprint step 2): autoscaling reacts after load arrives, which
is too late for a crowd that lands at exactly 12:00. So every minute (Kubernetes CronJob):

    a sale starts within PRESCALE_LEAD_MINUTES (15) or started less than
    PRESCALE_HOLD_MINUTES (60) ago  -> HPA minReplicas = PRESCALE_MIN_REPLICAS
    otherwise                       -> HPA minReplicas = BASE_MIN_REPLICAS

The HPA still scales above the minimum on CPU; Karpenter (demo) adds the nodes the extra pods
need. Only the HPA's minReplicas is patched (Argo CD ignores that field). The job's service
account may get/patch that one HPA and nothing else.

    python -m app.prescale
"""

from __future__ import annotations

import json
import logging
import os
import ssl
import urllib.request
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

log = logging.getLogger("prescale")

SA = "/var/run/secrets/kubernetes.io/serviceaccount"


def sales_in_window(db, now: datetime, lead_min: int, hold_min: int) -> list[dict]:
    rows = db.execute(
        text(
            "SELECT id::text, name, sale_starts_at FROM events "
            "WHERE sale_starts_at BETWEEN :lo AND :hi ORDER BY sale_starts_at"
        ),
        {"lo": now - timedelta(minutes=hold_min), "hi": now + timedelta(minutes=lead_min)},
    ).all()
    return [{"id": r[0], "name": r[1], "sale_starts_at": r[2].isoformat()} for r in rows]


def desired_min(sales: list[dict], base: int, boosted: int) -> int:
    return boosted if sales else base


class Kube:
    """Just enough of the Kubernetes API: read and patch one HPA, in-cluster credentials."""

    def __init__(self, namespace: str):
        host = os.environ["KUBERNETES_SERVICE_HOST"]
        self.base = f"https://{host}:{os.environ.get('KUBERNETES_SERVICE_PORT', '443')}"
        self.ns = namespace
        self.token = open(f"{SA}/token").read().strip()
        self.ctx = ssl.create_default_context(cafile=f"{SA}/ca.crt")

    def _call(
        self, method: str, path: str, body: dict | None = None, ctype: str = "application/json"
    ):
        req = urllib.request.Request(  # noqa: S310 - fixed https base (the in-cluster API server)
            self.base + path,
            method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": ctype},
        )
        with urllib.request.urlopen(req, context=self.ctx, timeout=10) as r:  # noqa: S310 (https, in-cluster)
            return json.loads(r.read())

    def hpa_min(self, name: str) -> int:
        hpa = self._call(
            "GET", f"/apis/autoscaling/v2/namespaces/{self.ns}/horizontalpodautoscalers/{name}"
        )
        return int(hpa["spec"].get("minReplicas", 1))

    def set_hpa_min(self, name: str, value: int) -> None:
        self._call(
            "PATCH",
            f"/apis/autoscaling/v2/namespaces/{self.ns}/horizontalpodautoscalers/{name}",
            {"spec": {"minReplicas": value}},
            "application/merge-patch+json",
        )


def run(db, kube, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    hpa = os.getenv("PRESCALE_HPA", "booking-api")
    sales = sales_in_window(
        db,
        now,
        int(os.getenv("PRESCALE_LEAD_MINUTES", "15")),
        int(os.getenv("PRESCALE_HOLD_MINUTES", "60")),
    )
    want = desired_min(
        sales,
        int(os.getenv("BASE_MIN_REPLICAS", "2")),
        int(os.getenv("PRESCALE_MIN_REPLICAS", "4")),
    )
    have = kube.hpa_min(hpa)
    if want != have:
        kube.set_hpa_min(hpa, want)
    result = {
        "sales_in_window": sales[:5],
        "hpa": hpa,
        "min_from": have,
        "min_to": want,
        "changed": want != have,
    }
    log.info(json.dumps({"prescale": result}, default=str))
    return result


def main() -> None:  # pragma: no cover - runs in the cluster
    from app.db import _session_factory
    from app.telemetry import setup_logging

    setup_logging()
    with _session_factory()() as db:
        run(db, Kube(os.getenv("POD_NAMESPACE", "booking")))


if __name__ == "__main__":  # pragma: no cover
    main()
