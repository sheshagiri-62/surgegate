"""Start the 10-minute hold timer (Step Functions) for a committed hold.

One Standard execution per hold, NAMED BY THE HOLD ID, so starting it twice is harmless
(ExecutionAlreadyExists). The state machine waits, then the release worker frees the seats only
if they are still held by this hold (services/workers/src/sg_workers/release_hold.py).

If the timer cannot be started, the hold must not stay forever: the caller releases it at once
(release_now) and the buyer is asked to try again. No-op when HOLD_TIMER_ARN is unset (tests).
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

HOLD_SECONDS = int(os.getenv("HOLD_SECONDS", "600"))


@lru_cache(maxsize=1)
def _sfn():
    import boto3
    from botocore.config import Config

    return boto3.client(
        "stepfunctions",
        region_name=os.getenv("AWS_REGION", "ap-south-1"),
        config=Config(connect_timeout=2, read_timeout=5, retries={"max_attempts": 3}),
    )


def start(hold_id: uuid.UUID, event_id: uuid.UUID, wait_seconds: int = HOLD_SECONDS) -> bool:
    """True if the timer runs (or already ran) for this hold."""
    arn = os.getenv("HOLD_TIMER_ARN")
    if not arn:
        return True  # no timer configured (tests, local)
    try:
        _sfn().start_execution(
            stateMachineArn=arn,
            name=str(hold_id),
            input=json.dumps(
                {"hold_id": str(hold_id), "event_id": str(event_id), "wait_seconds": wait_seconds}
            ),
        )
        return True
    except Exception as exc:
        if type(exc).__name__ == "ExecutionAlreadyExists":
            return True
        log.error("hold timer not started for %s: %s", hold_id, type(exc).__name__)
        return False


def release_now(db: Session, hold_id: uuid.UUID) -> None:
    """Same rule as the release worker: only seats still held by THIS hold."""
    db.execute(
        text(
            "UPDATE seats SET status = 'available', hold_id = NULL, held_until = NULL "
            "WHERE hold_id = :h AND status = 'held'"
        ),
        {"h": hold_id},
    )
    db.execute(
        text("UPDATE holds SET status = 'released' WHERE id = :h AND status = 'active'"),
        {"h": hold_id},
    )
    db.commit()
