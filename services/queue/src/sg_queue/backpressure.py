"""Backpressure (Day 10 Task 1, blueprint step 4): every minute, slow the waiting room down when
the booking API struggles, and speed it back up when it recovers.

    unhealthy = booking p95 > 500 ms  or  5xx > 1%   (the last full minute, from the ALB)
    unhealthy -> admission_rate = max(FLOOR, rate * 0.7)
    healthy   -> admission_rate = min(max_admission_rate, rate * 1.2 + 1)
                 (healthy = p95 < 300 ms and 5xx < 0.5%)
    idle (< 20 requests/min) -> recover like healthy; in between, or no ALB -> no change

max_admission_rate is what the organiser set (the booking API stores it); backpressure never
goes above it. The queue gets longer instead of the site falling over. Each update is
conditional on the old value, so a retried run or a concurrent organiser change can't be
overwritten with a stale number.
"""

from __future__ import annotations

import json
import logging
import math
import os
from datetime import UTC, datetime, timedelta
from functools import lru_cache

import boto3
from botocore.exceptions import ClientError

from sg_queue.common import META, table
from sg_queue.starter import active_queues

log = logging.getLogger()
log.setLevel(logging.INFO)

SLOW_P95 = float(os.getenv("BACKPRESSURE_SLOW_P95", "0.5"))
OK_P95 = float(os.getenv("BACKPRESSURE_OK_P95", "0.3"))
BAD_5XX = float(os.getenv("BACKPRESSURE_BAD_5XX_PCT", "1"))
OK_5XX = float(os.getenv("BACKPRESSURE_OK_5XX_PCT", "0.5"))
FLOOR = int(os.getenv("BACKPRESSURE_FLOOR", "20"))
MIN_REQUESTS = 20  # fewer requests in a minute say nothing about health


@lru_cache(maxsize=1)
def cloudwatch():
    return boto3.client("cloudwatch")


def booking_health(now: datetime | None = None) -> dict:
    """p95 (s), 5xx %, requests over the last full minute, from the ALB target group."""
    lb, tg = os.getenv("ALB_ARN_SUFFIX", ""), os.getenv("TARGET_GROUP_ARN_SUFFIX", "")
    if not lb or not tg:
        return {"state": "unknown", "reason": "no ALB (environment down)"}
    now = (now or datetime.now(UTC)).replace(second=0, microsecond=0)
    dims = [{"Name": "LoadBalancer", "Value": lb}, {"Name": "TargetGroup", "Value": tg}]

    def q(qid, metric, stat):
        return {
            "Id": qid,
            "MetricStat": {
                "Metric": {
                    "Namespace": "AWS/ApplicationELB",
                    "MetricName": metric,
                    "Dimensions": dims,
                },
                "Period": 60,
                "Stat": stat,
            },
        }

    out = cloudwatch().get_metric_data(
        MetricDataQueries=[
            q("p95", "TargetResponseTime", "p95"),
            q("req", "RequestCount", "Sum"),
            q("e5", "HTTPCode_Target_5XX_Count", "Sum"),
        ],
        StartTime=now - timedelta(minutes=2),
        EndTime=now,
    )
    last = {r["Id"]: (r["Values"][0] if r["Values"] else 0.0) for r in out["MetricDataResults"]}
    return classify(last.get("p95", 0.0), last.get("req", 0.0), last.get("e5", 0.0))


def classify(p95: float, requests: float, errors: float) -> dict:
    if requests < MIN_REQUESTS:
        # Little traffic is no stress: a lowered rate may recover.
        return {"state": "idle", "requests": int(requests)}
    pct = 100.0 * errors / requests
    h = {"p95": round(p95, 3), "requests": int(requests), "5xx_pct": round(pct, 2)}
    if p95 > SLOW_P95 or pct > BAD_5XX:
        return h | {"state": "unhealthy"}
    if p95 < OK_P95 and pct < OK_5XX:
        return h | {"state": "healthy"}
    return h | {"state": "steady"}


def next_rate(rate: int, ceiling: int, state: str) -> int:
    if state == "unhealthy":
        return max(min(FLOOR, rate), int(rate * 0.7))
    if state in ("healthy", "idle") and rate < ceiling:
        return min(ceiling, math.ceil(rate * 1.2) + 1)
    return rate


def adjust(meta: dict, state: str) -> dict | None:
    if meta.get("status") != "open":
        return None
    rate = int(meta.get("admission_rate", 0))
    ceiling = int(meta.get("max_admission_rate", rate))
    new = next_rate(rate, ceiling, state)
    if new == rate:
        return None
    try:
        table().update_item(
            Key={"PK": meta["PK"], "SK": META},
            UpdateExpression="SET admission_rate = :new, max_admission_rate = :max",
            ConditionExpression="admission_rate = :old AND #s = :open",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":new": new, ":old": rate, ":max": ceiling, ":open": "open"},
        )
    except ClientError as err:
        if err.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return None  # the organiser changed it meanwhile: theirs wins
        raise
    return {"event": meta["PK"].removeprefix("EVENT#"), "from": rate, "to": new, "max": ceiling}


def handler(event, context):
    health = booking_health()
    changed = []
    if health["state"] in ("unhealthy", "healthy", "idle"):
        changed = [c for meta in active_queues() if (c := adjust(meta, health["state"]))]
    log.info(json.dumps({"backpressure": health, "changed": changed}))
    return {"health": health, "changed": changed}
