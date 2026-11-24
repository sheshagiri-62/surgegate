"""live-dashboard consumer, live tokens and the WebSocket handlers (moto DynamoDB)."""

import base64
import json
import uuid

import boto3
import pytest
from moto import mock_aws

from sg_consumers import common, live_dashboard, live_token, ws

KEY = {"kid": "l1", "key": "L" * 40}
EV = "9abf74ae-c14f-46e1-9e8f-8ee9872b7995"


class FakeApi:
    class exceptions:  # noqa: N801 - mimics botocore's client.exceptions
        class GoneException(Exception):
            pass

    def __init__(self, gone=()):
        self.sent, self.gone = [], set(gone)

    def post_to_connection(self, ConnectionId, Data):  # noqa: N803 - boto3 names
        if ConnectionId in self.gone:
            raise self.exceptions.GoneException(ConnectionId)
        self.sent.append((ConnectionId, json.loads(Data)))


@pytest.fixture
def aws(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("STATS_TABLE", "stats")
    monkeypatch.setenv("QUEUE_TABLE", "queue")
    monkeypatch.setenv("WS_ENDPOINT", "https://ws.test/live")
    monkeypatch.setenv("LIVE_KEY_JSON", json.dumps(KEY))
    common.client.cache_clear()
    ws.live_key.cache_clear()
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name="ap-south-1")
        for name in ("stats", "queue"):
            ddb.create_table(
                TableName=name,
                KeySchema=[
                    {"AttributeName": "PK", "KeyType": "HASH"},
                    {"AttributeName": "SK", "KeyType": "RANGE"},
                ],
                AttributeDefinitions=[
                    {"AttributeName": "PK", "AttributeType": "S"},
                    {"AttributeName": "SK", "AttributeType": "S"},
                ],
                BillingMode="PAY_PER_REQUEST",
            )
        ddb.put_item(
            TableName="queue",
            Item={
                "PK": {"S": f"EVENT#{EV}"},
                "SK": {"S": "META"},
                "status": {"S": "open"},
                "admission_rate": {"N": "250"},
            },
        )
        api = FakeApi(gone={"gone-conn"})
        real = common.client

        def fake_client(name, **kw):
            return api if name == "apigatewaymanagementapi" else real(name, **kw)

        monkeypatch.setattr(live_dashboard, "client", fake_client)
        monkeypatch.setattr(ws, "client", fake_client)
        yield ddb, api
    common.client.cache_clear()
    ws.live_key.cache_clear()


def env(kind, data, eid=None):
    return {
        "id": eid or str(uuid.uuid4()),
        "type": kind,
        "sale_event_id": EV,
        "at": "2026-11-24T18:00:00Z",
        "data": data,
    }


def batch(*envs):
    return {
        "Records": [
            {
                "kinesis": {
                    "sequenceNumber": str(1000 + i),
                    "data": base64.b64encode(json.dumps(e).encode()).decode(),
                }
            }
            for i, e in enumerate(envs)
        ]
    }


def connect(cid, event_id=EV):
    return ws.handler(
        {
            "requestContext": {
                "routeKey": "$connect",
                "connectionId": cid,
                "authorizer": {"event_id": event_id, "sub": "org"},
            }
        },
        None,
    )


SALE = [
    env("joined", {}),
    env("joined", {}),
    env("joined", {}),
    env("admitted", {"sub": "a"}),
    env("admitted", {"sub": "b"}),
    env("seat_held", {"seats": ["A-1-1", "A-1-2"], "amount_paise": 300000}),
    env("seat_held", {"seats": ["A-1-3"], "amount_paise": 150000}),
    env("order_paid", {"seats": ["A-1-1", "A-1-2"], "amount_paise": 300000, "late": False}),
    env("hold_released", {"released_seats": ["A-1-3"]}),
    env("order_paid", {"seats": ["A-1-3"], "amount_paise": 150000, "late": True}),
    env("payment_refunded", {"amount_paise": 99}),
    env("ticket_issued", {"tickets": ["t1", "t2"]}),
]


def test_a_sale_adds_up_and_is_pushed(aws):
    _, api = aws
    connect("org-conn")
    assert live_dashboard.handler(batch(*SALE), None) == {"batchItemFailures": []}
    (cid, numbers) = api.sent[-1]
    assert cid == "org-conn"
    assert numbers | {"updated_at": None} == {
        "type": "stats",
        "event_id": EV,
        "waiting": 1,
        "admitted": 2,
        "held_seats": 0,  # 3 held: 2 sold, 1 released; its late payment re-held + sold it
        "sold_seats": 3,
        "orders_paid": 2,
        "revenue_paise": 450000,
        "refunds": 1,
        "tickets": 2,
        "queue_status": "open",
        "admission_rate": 250,
        "updated_at": None,
    }


def test_duplicates_and_replays_count_once(aws):
    _, api = aws
    connect("org-conn")
    live_dashboard.handler(batch(*SALE), None)
    first = api.sent[-1][1]
    live_dashboard.handler(batch(*SALE), None)  # the same records again (retry / archive replay)
    live_dashboard.handler(batch(SALE[0], SALE[0]), None)  # a duplicate inside one batch
    assert api.sent[-1][1] == first


def test_failure_reports_the_failing_record_so_lambda_retries_from_there(aws, monkeypatch):
    real = live_dashboard.apply
    calls = []

    def flaky(e, table, now=None):
        calls.append(e["id"])
        if len(calls) == 2:
            raise RuntimeError("throttled")
        return real(e, table, now)

    monkeypatch.setattr(live_dashboard, "apply", flaky)
    assert live_dashboard.handler(batch(*SALE[:3]), None) == {
        "batchItemFailures": [{"itemIdentifier": "1001"}]
    }
    monkeypatch.setattr(live_dashboard, "apply", real)
    live_dashboard.handler(
        batch(*SALE[:3]), None
    )  # Lambda's retry: the first one is a duplicate now
    assert live_dashboard.snapshot(EV)["waiting"] == 3


def test_gone_connections_are_removed_and_others_still_get_it(aws):
    ddb, api = aws
    connect("org-conn")
    connect("gone-conn")
    live_dashboard.handler(batch(SALE[0]), None)
    assert [c for c, _ in api.sent] == ["org-conn"]
    left = ddb.query(
        TableName="stats",
        KeyConditionExpression="PK = :p",
        ExpressionAttributeValues={":p": {"S": f"SUBS#{EV}"}},
    )
    assert [i["SK"]["S"] for i in left["Items"]] == ["org-conn"]


def test_only_subscribers_of_that_sale_get_it(aws):
    _, api = aws
    connect("other-sale", event_id=str(uuid.uuid4()))
    live_dashboard.handler(batch(SALE[0]), None)
    assert api.sent == []


def test_disconnect_and_snapshot(aws):
    _, api = aws
    connect("org-conn")
    live_dashboard.handler(batch(SALE[0]), None)
    ws.handler({"requestContext": {"routeKey": "snapshot", "connectionId": "org-conn"}}, None)
    assert api.sent[-1][1]["waiting"] == 1
    ws.handler({"requestContext": {"routeKey": "$disconnect", "connectionId": "org-conn"}}, None)
    n = len(api.sent)
    live_dashboard.handler(batch(env("joined", {})), None)
    assert len(api.sent) == n  # nobody subscribed any more


def test_live_token_and_authorizer():
    now = 1_800_000_000
    t = live_token.issue(EV, "org-1", KEY, now=now)
    assert live_token.verify(t, KEY, now=now + 59)["ev"] == EV
    with pytest.raises(ValueError, match="expired"):
        live_token.verify(t, KEY, now=now + 61)
    with pytest.raises(ValueError, match="forged"):
        live_token.verify(t, {"kid": "l1", "key": "other"}, now=now)
    body, _ = t.split(".")
    with pytest.raises(ValueError):
        live_token.verify(body + ".AAAA", KEY, now=now)
    with pytest.raises(ValueError, match="not a live token"):
        bad = live_token.issue(EV, "x", KEY, now=now)  # re-sign with another typ
        payload = json.loads(base64.urlsafe_b64decode(bad.split(".")[0] + "=="))
        import hashlib
        import hmac

        b = (
            base64.urlsafe_b64encode(
                json.dumps(
                    payload | {"typ": "pass"}, sort_keys=True, separators=(",", ":")
                ).encode()
            )
            .rstrip(b"=")
            .decode()
        )
        s = (
            base64.urlsafe_b64encode(
                hmac.new(KEY["key"].encode(), b.encode(), hashlib.sha256).digest()
            )
            .rstrip(b"=")
            .decode()
        )
        live_token.verify(f"{b}.{s}", KEY, now=now)


def test_authorizer_allows_a_valid_token_only(monkeypatch):
    monkeypatch.setenv("LIVE_KEY_JSON", json.dumps(KEY))
    ws.live_key.cache_clear()
    arn = "arn:aws:execute-api:ap-south-1:1:api/live/$connect"
    ok = ws.authorizer(
        {"methodArn": arn, "queryStringParameters": {"token": live_token.issue(EV, "org-1", KEY)}},
        None,
    )
    assert ok["policyDocument"]["Statement"][0]["Effect"] == "Allow"
    assert ok["context"] == {"event_id": EV, "sub": "org-1"}
    for params in ({"token": "garbage"}, {}, None):
        deny = ws.authorizer({"methodArn": arn, "queryStringParameters": params}, None)
        assert deny["policyDocument"]["Statement"][0]["Effect"] == "Deny"
    ws.live_key.cache_clear()


# Same string as services/booking-api/tests/test_live_token.py (the issuer's copy).
VECTOR = (
    "eyJldiI6IjlhYmY3NGFlLWMxNGYtNDZlMS05ZThmLThlZTk4NzJiNzk5NSIsImV4cCI6MTgwMDAwMDA2MCwiaWF0Ijox"
    "ODAwMDAwMDAwLCJraWQiOiJsMSIsInN1YiI6Im9yZy0xIiwidHlwIjoibGl2ZSJ9.tPWE8_XJnJiU6Y-dMsTed6qPmgaVbimnh0rSp15aD30"
)


def test_shared_vector_with_the_booking_api():
    assert live_token.issue(EV, "org-1", KEY, now=1_800_000_000) == VECTOR
    assert live_token.verify(VECTOR, KEY, now=1_800_000_000)["ev"] == EV
