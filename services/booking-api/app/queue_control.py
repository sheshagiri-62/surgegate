"""The organiser's controls for an event's waiting room (blueprint: PATCH /org/events/{id}/queue,
"Booking API -> DynamoDB").

The waiting room itself runs serverless (API Gateway + Lambda + DynamoDB). Its state lives in
one item per event in the queue table: (PK=EVENT#<id>, SK=META). The booking API writes that
item for the organiser; the Lambdas read it:

  open     create the item; status "pre-queue" before the sale start (the starter shuffles and
           opens it at the start), "open" if the sale has already started
  pause    open -> paused   (the valve stops admitting; people can still join)
  resume   paused -> open
  rate     change how many buyers are let in per minute

The pod reaches DynamoDB through the VPC gateway endpoint with its Pod Identity role.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from functools import lru_cache

import boto3
from botocore.exceptions import ClientError

META = "META"


class QueueError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


@lru_cache(maxsize=1)
def table():
    region = os.getenv("AWS_REGION", "ap-south-1")
    return boto3.resource("dynamodb", region_name=region).Table(
        os.getenv("QUEUE_TABLE", "surgegate-dev-queue")
    )


def _key(event_id: uuid.UUID) -> dict:
    return {"PK": f"EVENT#{event_id}", "SK": META}


def _failed(err: ClientError) -> bool:
    return err.response["Error"]["Code"] == "ConditionalCheckFailedException"


def get(event_id: uuid.UUID) -> dict | None:
    return table().get_item(Key=_key(event_id), ConsistentRead=True).get("Item")


def summary(item: dict) -> dict:
    serving = int(item.get("serving_up_to", 0))
    in_line = int(item.get("next_position", 0))
    return {
        "status": item["status"],
        "admission_rate": int(item.get("admission_rate", 0)),
        "sale_starts_at": item["sale_starts_at"],
        "in_line": in_line,
        "admitted": min(serving, in_line),
        "waiting": max(in_line - serving, 0),
    }


def open_queue(event_id: uuid.UUID, sale_starts_at: datetime, admission_rate: int) -> dict:
    status = "pre-queue" if datetime.now(UTC) < sale_starts_at else "open"
    item = _key(event_id) | {
        "status": status,
        "sale_starts_at": sale_starts_at.astimezone(UTC).isoformat(),
        "admission_rate": admission_rate,
        # The organiser's rate: backpressure (Day 10) may lower admission_rate, never above this.
        "max_admission_rate": admission_rate,
        "next_position": 0,
        "serving_up_to": 0,
        "active": "1",  # listed in the active-queues index (starter, valve)
    }
    try:
        table().put_item(Item=item, ConditionExpression="attribute_not_exists(PK)")
    except ClientError as err:
        if _failed(err):
            raise QueueError(
                409, "the waiting room is already open; use PATCH to change it"
            ) from err
        raise
    return summary(item)


def change(event_id: uuid.UUID, action: str | None, admission_rate: int | None) -> dict:
    if get(event_id) is None:
        raise QueueError(404, "no waiting room for this event")
    sets, cond, names, values = [], ["attribute_exists(PK)"], {}, {}
    if action == "pause":
        sets.append("#s = :paused")
        cond.append("#s = :open")
        values |= {":paused": "paused", ":open": "open"}
    elif action == "resume":
        sets.append("#s = :open")
        cond.append("#s = :paused")
        values |= {":paused": "paused", ":open": "open"}
    if action:
        names["#s"] = "status"
    if admission_rate is not None:
        sets.append("admission_rate = :rate")
        sets.append("max_admission_rate = :rate")  # the organiser's choice is the new ceiling
        values[":rate"] = admission_rate
    request = {
        "Key": _key(event_id),
        "UpdateExpression": "SET " + ", ".join(sets),
        "ConditionExpression": " AND ".join(cond),
        "ExpressionAttributeValues": values,
        "ReturnValues": "ALL_NEW",
    }
    if names:
        request["ExpressionAttributeNames"] = names
    try:
        out = table().update_item(**request)
    except ClientError as err:
        if _failed(err):
            want = "open" if action == "pause" else "paused"
            raise QueueError(409, f"can only {action} a queue that is {want}") from err
        raise
    return summary(out["Attributes"])
