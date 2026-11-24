"""WebSocket API for the organiser live dashboard (Day 8 Task 3).

  wss://<api>.execute-api.<region>.amazonaws.com/live?token=<60-second live token>

authorizer  $connect REQUEST authorizer: verify the live token (HMAC, typ "live", not expired)
            -> Allow with context {event_id, sub}; anything else -> Deny (HTTP 403)
$connect    remember the connection: SUBS#<event>/<conn> and CONN#<conn> (TTL 2 h)
$disconnect forget it
snapshot    {"action": "snapshot"}: send the current numbers to this connection now
"""

from __future__ import annotations

import json
import logging
import os
import time
from functools import lru_cache

from sg_consumers import live_dashboard, live_token
from sg_consumers.common import client

log = logging.getLogger()
log.setLevel(logging.INFO)

CONN_TTL_SECONDS = 2 * 3600


@lru_cache(maxsize=1)
def live_key() -> dict:
    if raw := os.getenv("LIVE_KEY_JSON"):
        return json.loads(raw)
    value = client("secretsmanager").get_secret_value(SecretId=os.environ["LIVE_KEY_SECRET_ID"])
    return json.loads(value["SecretString"])


def authorizer(event, context):
    token = (event.get("queryStringParameters") or {}).get("token", "")
    try:
        claims = live_token.verify(token, live_key())
    except ValueError as exc:
        log.info(json.dumps({"connect_refused": str(exc)}))
        return _policy("Deny", event["methodArn"], "anonymous", {})
    return _policy(
        "Allow", event["methodArn"], claims["sub"], {"event_id": claims["ev"], "sub": claims["sub"]}
    )


def _policy(effect: str, arn: str, principal: str, ctx: dict) -> dict:
    return {
        "principalId": principal,
        "policyDocument": {
            "Version": "2012-10-17",
            "Statement": [{"Action": "execute-api:Invoke", "Effect": effect, "Resource": arn}],
        },
        "context": ctx,
    }


def handler(event, context):
    rc = event["requestContext"]
    route, cid = rc["routeKey"], rc["connectionId"]
    ddb, table = client("dynamodb"), os.environ["STATS_TABLE"]
    if route == "$connect":
        ev = rc["authorizer"]["event_id"]
        ttl = str(int(time.time()) + CONN_TTL_SECONDS)
        ddb.put_item(
            TableName=table,
            Item={"PK": {"S": f"SUBS#{ev}"}, "SK": {"S": cid}, "expires": {"N": ttl}},
        )
        ddb.put_item(
            TableName=table,
            Item={
                "PK": {"S": f"CONN#{cid}"},
                "SK": {"S": "-"},
                "event_id": {"S": ev},
                "expires": {"N": ttl},
            },
        )
        log.info(json.dumps({"connected": cid, "event": ev, "sub": rc["authorizer"].get("sub")}))
        return {"statusCode": 200}
    if route == "$disconnect":
        item = ddb.get_item(
            TableName=table, Key={"PK": {"S": f"CONN#{cid}"}, "SK": {"S": "-"}}
        ).get("Item")
        if item:
            ev = item["event_id"]["S"]
            ddb.delete_item(TableName=table, Key={"PK": {"S": f"SUBS#{ev}"}, "SK": {"S": cid}})
            ddb.delete_item(TableName=table, Key={"PK": {"S": f"CONN#{cid}"}, "SK": {"S": "-"}})
        return {"statusCode": 200}
    if route == "snapshot":
        item = ddb.get_item(
            TableName=table, Key={"PK": {"S": f"CONN#{cid}"}, "SK": {"S": "-"}}
        ).get("Item")
        if item:
            api = client("apigatewaymanagementapi", endpoint_url=os.environ["WS_ENDPOINT"])
            api.post_to_connection(
                ConnectionId=cid,
                Data=json.dumps(live_dashboard.snapshot(item["event_id"]["S"])).encode(),
            )
        return {"statusCode": 200}
    return {"statusCode": 400}
