"""Claiming queue places and handing out positions (shared by the sequencer and the starter).

One place per account: every entry is the item (EVENT#<id>, USER#<sub>), created with a
conditional write, so a second join by the same account can never create a second place.

Positions are only ever given to CLAIMED entries that have none yet, by reserving a block
with one atomic counter update; so duplicates never leave gaps in the numbering.
"""

from __future__ import annotations

import secrets
import time

from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

from sg_queue.common import META, parse_iso, pk, table, user_sk

ENTRY_TTL_SECONDS = 2 * 24 * 3600  # entries clean themselves up two days after joining


def _conditional_failed(err: ClientError) -> bool:
    return err.response["Error"]["Code"] == "ConditionalCheckFailedException"


def claim(join: dict, pre_queue: bool) -> bool:
    """Create this account's place. False = the account already has one (duplicate join).

    A retry of the SAME join (same request_id) that has no position yet is accepted again, so
    a sequencer that crashed half-way never loses anyone.
    """
    item = {
        "PK": pk(join["event_id"]),
        "SK": user_sk(join["sub"]),
        "request_id": join["request_id"],
        "joined_at": join["joined_at"],
        "expires_at": int(time.time()) + ENTRY_TTL_SECONDS,
    }
    if pre_queue:
        item["shuffle_key"] = secrets.randbits(63)  # random order at sale start
    try:
        table().put_item(
            Item=item,
            ConditionExpression="attribute_not_exists(SK) OR "
            "(request_id = :rid AND attribute_not_exists(#pos))",
            ExpressionAttributeNames={"#pos": "position"},
            ExpressionAttributeValues={":rid": join["request_id"]},
        )
        return True
    except ClientError as err:
        if _conditional_failed(err):
            return False
        raise


def reserve(event_id: str, count: int) -> int:
    """Atomically reserve `count` positions (ONE write per batch); returns the first one."""
    out = table().update_item(
        Key={"PK": pk(event_id), "SK": META},
        UpdateExpression="ADD next_position :n",
        ConditionExpression="attribute_exists(PK)",
        ExpressionAttributeValues={":n": count},
        ReturnValues="UPDATED_NEW",
    )
    return int(out["Attributes"]["next_position"]) - count + 1


def assign(event_id: str, subs: list[str]) -> int:
    """Give positions, in the order given, to entries that have none. Returns how many."""
    if not subs:
        return 0
    first = reserve(event_id, len(subs))
    done = 0
    for offset, sub in enumerate(subs):
        try:
            table().update_item(
                Key={"PK": pk(event_id), "SK": user_sk(sub)},
                UpdateExpression="SET #pos = :p REMOVE shuffle_key",
                ConditionExpression="attribute_exists(SK) AND attribute_not_exists(#pos)",
                ExpressionAttributeNames={"#pos": "position"},
                ExpressionAttributeValues={":p": first + offset},
            )
            done += 1
        except ClientError as err:
            if not _conditional_failed(err):
                raise
            # Someone else positioned it in the same instant: that number stays unused.
    return done


def unpositioned(event_id: str) -> list[dict]:
    """Every claimed entry still waiting for a number (consistent read, all pages)."""
    items, kwargs = (
        [],
        {
            "KeyConditionExpression": Key("PK").eq(pk(event_id)) & Key("SK").begins_with("USER#"),
            "FilterExpression": Attr("position").not_exists(),
            "ConsistentRead": True,
        },
    )
    while True:
        page = table().query(**kwargs)
        items.extend(page["Items"])
        if "LastEvaluatedKey" not in page:
            return items
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def shuffle_order(entries: list[dict], sale_starts_at: str) -> list[str]:
    """Fair order at sale start: everyone who joined BEFORE the start in random order
    (their random shuffle_key), then later arrivals first-come-first-served."""
    start = parse_iso(sale_starts_at)
    early = [e for e in entries if parse_iso(e["joined_at"]) < start]
    late = [e for e in entries if parse_iso(e["joined_at"]) >= start]
    early.sort(key=lambda e: int(e.get("shuffle_key", 0)))
    late.sort(key=lambda e: e["joined_at"])
    return [e["SK"].removeprefix("USER#") for e in early + late]
