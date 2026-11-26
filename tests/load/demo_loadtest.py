# ruff: noqa: E501, S603, S607, S310 -- operator tool: long SQL strings, runs kubectl, calls our own URLs
"""Demo load-test runner (Day 10 Task 4): 10k / 50k fans for a 2,000-seat flash sale.

Run with the booking-api venv (boto3, PyJWT[crypto], cryptography), AWS_PROFILE=surgegate and
kubectl pointed at the demo cluster. Order (docs/runbooks/demo-loadtest.md):

    terraform -chdir=infra/envs/demo output -json > tests/load/.demo-out.json
    python tests/load/demo_loadtest.py keygen                 # issuer key -> Secrets Manager
    python tests/load/demo_loadtest.py headroom --fans 50000  # limits vs the planned peak
    python tests/load/demo_loadtest.py setup --fans 10000     # organiser, event, 2,000 seats, queue
    python tests/load/demo_loadtest.py start                  # k6 Job (shards on the Spot pool)
    python tests/load/demo_loadtest.py watch                  # sold count; pauses queue when sold out
    python tests/load/demo_loadtest.py collect                # k6 shard summaries -> results JSON
    python tests/load/demo_loadtest.py check                  # SQL oversold check
    python tests/load/demo_loadtest.py cleanup                # Job, organiser user

State of the current run: tests/load/.demo-run.json (gitignored). Results:
docs/progress/day-10/loadtest-<run>.json. Every result states the REAL VU count (sum of each
shard's vus_max) and whether it was the fallback profile.
"""

from __future__ import annotations

import argparse
import base64
import csv
import io
import json
import math
import secrets
import subprocess
import sys
import time
import urllib.request
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import boto3

REGION = "ap-south-1"
ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
OUT_FILE = HERE / ".demo-out.json"
RUN_FILE = HERE / ".demo-run.json"
NAME = "surgegate-demo"
NS = "loadtest"
K6_IMAGE = "grafana/k6:2.3.0"
SEATS = 2000
SEATS_PER_BUYER = 2


# --- helpers -------------------------------------------------------------------------------
def tf() -> dict:
    if not OUT_FILE.exists():
        sys.exit(f"missing {OUT_FILE}: terraform -chdir=infra/envs/demo output -json > {OUT_FILE}")
    return {k: v["value"] for k, v in json.loads(OUT_FILE.read_text()).items()}


def run_state() -> dict:
    return json.loads(RUN_FILE.read_text()) if RUN_FILE.exists() else {}


def save_run(state: dict) -> None:
    RUN_FILE.write_text(json.dumps(state, indent=2))


def kubectl(*args: str, stdin: str | None = None, check: bool = True) -> str:
    r = subprocess.run(["kubectl", *args], input=stdin, capture_output=True, text=True)
    if check and r.returncode != 0:
        sys.exit(f"kubectl {' '.join(args[:3])}: {r.stderr.strip()}")
    return r.stdout


def api(method: str, url: str, token: str, body=None, content_type="application/json") -> dict:
    data = None
    if body is not None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", content_type)
    req.add_header("User-Agent", "surgegate-demo-loadtest")
    with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 (our own CloudFront URL)
        raw = r.read()
    return json.loads(raw) if raw else {}


def b64url(n: int) -> str:
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


# --- keygen --------------------------------------------------------------------------------
def keygen(_: argparse.Namespace) -> None:
    """New RSA key: private half -> Secrets Manager (k6 pods only), public JWK -> SSM."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    o = tf()
    if not o.get("loadtest_key_secret_id"):
        sys.exit("enable_loadtest is off: apply demo with -var=enable_loadtest=true first")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    kid = "lt-" + datetime.now(UTC).strftime("%Y%m%d%H%M")
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    pub = key.public_key().public_numbers()
    jwk = {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS256",
        "kid": kid,
        "n": b64url(pub.n),
        "e": b64url(pub.e),
    }
    boto3.client("secretsmanager", region_name=REGION).put_secret_value(
        SecretId=o["loadtest_key_secret_id"],
        SecretString=json.dumps({"kid": kid, "private_key_pem": pem}),
    )
    boto3.client("ssm", region_name=REGION).put_parameter(
        Name=o["loadtest_jwks_param"],
        Value=json.dumps({"keys": [jwk]}),
        Type="String",
        Overwrite=True,
    )
    del pem, key  # only in this process's memory, never on disk
    # The issuer caches the JWKS for 5 minutes; check what it serves now.
    with urllib.request.urlopen(f"{o['loadtest_issuer']}/.well-known/jwks.json", timeout=10) as r:  # noqa: S310
        print(
            f"issuer {o['loadtest_issuer']} serves kid(s): {[k['kid'] for k in json.load(r)['keys']]}"
        )
    print(
        f"new key {kid}: private -> {o['loadtest_key_secret_id']}, public -> {o['loadtest_jwks_param']}"
    )


# --- headroom ------------------------------------------------------------------------------
def headroom(args: argparse.Namespace) -> None:
    """Limits vs the planned peak, BEFORE a run (all numbers read live from the account)."""
    fans, arrival = args.fans, 60
    lam = boto3.client("lambda", region_name=REGION).get_account_settings()["AccountLimit"]
    sq = boto3.client("service-quotas", region_name=REGION)

    def quota(service: str, code: str) -> float | None:
        try:
            return sq.get_service_quota(ServiceCode=service, QuotaCode=code)["Quota"]["Value"]
        except Exception:  # noqa: BLE001
            return None

    apigw = boto3.client("apigatewayv2", region_name=REGION)
    api_id = next(a["ApiId"] for a in apigw.get_apis()["Items"] if a["Name"] == f"{NAME}-queue")
    stage = apigw.get_stage(ApiId=api_id, StageName="$default")["DefaultRouteSettings"]
    ddb = boto3.client("dynamodb", region_name=REGION).describe_table(TableName=f"{NAME}-queue")[
        "Table"
    ]
    kin = boto3.client("kinesis", region_name=REGION).describe_stream_summary(
        StreamName=f"{NAME}-sale-events"
    )
    mock_pay = kubectl(
        "-n", "mock-pay", "get", "deploy", "-o", "jsonpath={.items[*].spec.replicas}", check=False
    )
    spot = quota("ec2", "L-34B43A08")
    od = quota("ec2", "L-1216C47A")

    join_rps = fans / arrival
    position_rps = fans / 15  # first position call spread over the 15 s poll interval
    serving_rps = fans / 10  # CloudFront-cached 5 s: ~0 reach API Gateway
    lambda_peak = math.ceil(position_rps * 0.05)  # ~50 ms per position call
    rows = [
        (
            "Lambda concurrency (account)",
            f"{lam['ConcurrentExecutions']}",
            f"~{lambda_peak} at the position peak (50 ms x {position_rps:.0f}/s)",
        ),
        (
            "API Gateway stage rate / burst",
            f"{stage.get('ThrottlingRateLimit')} / {stage.get('ThrottlingBurstLimit')} rps",
            f"join {join_rps:.0f}/s, position <= {position_rps:.0f}/s",
        ),
        (
            "API Gateway account (quota L-8A5B8E43)",
            f"{quota('apigateway', 'L-8A5B8E43')} rps",
            "all APIs in the region together",
        ),
        (
            "CloudFront (serving, cached 5 s)",
            "no practical limit",
            f"{serving_rps:.0f}/s at the edge, ~1 per 5 s per edge to origin",
        ),
        (
            "DynamoDB queue table",
            ddb.get("BillingModeSummary", {}).get("BillingMode", "?")
            + f", max {ddb.get('OnDemandThroughput', {})}",
            f"~{join_rps:.0f} writes/s (join) + {position_rps:.0f} reads/s",
        ),
        (
            "Kinesis sale-events",
            kin["StreamDescriptionSummary"]["StreamModeDetails"]["StreamMode"],
            f"~{join_rps:.0f} records/s at join (on-demand: 4,000/s from the start)",
        ),
        (
            "mock-pay",
            f"{mock_pay or '?'} pod (in-memory orders: must stay 1)",
            f"<= admission rate x 1 order/min ~ {args.rate / 60:.0f} orders/s",
        ),
        (
            "Spot vCPU quota (load generators)",
            f"{spot}",
            f"{math.ceil(fans / 5000)} shards ~ {math.ceil(fans / 5000) * 2} vCPU requested",
        ),
        ("On-demand vCPU quota", f"{od}", "demo 4 baseline + <= 12 Karpenter; dev down"),
    ]
    w = max(len(r[0]) for r in rows)
    print(f"Planned peak for {fans:,} fans (arrival {arrival} s):\n")
    for name, limit, need in rows:
        print(f"  {name:<{w}}  limit: {limit:<34}  need: {need}")


# --- setup ---------------------------------------------------------------------------------
def seat_csv() -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["section", "row", "number", "zone", "price_inr"])
    for section, zone, price in (
        ("A", "gold", 2500),
        ("B", "gold", 2500),
        ("C", "silver", 1500),
        ("D", "silver", 1500),
    ):
        for row in range(1, 21):
            for number in range(1, 26):
                w.writerow([section, row, number, zone, price])
    return buf.getvalue().encode()  # 4 x 20 x 25 = 2,000 seats


def organiser_token(o: dict, state: dict) -> str:
    """A throwaway organiser in the demo pool (deleted by cleanup); 1 MAU."""
    idp = boto3.client("cognito-idp", region_name=REGION)
    pool, client = o["cognito_user_pool_id"], o["cognito_client_ids"]["test"]
    email = state.setdefault("organiser", f"loadtest-organiser-{state['run']}@surgegate.test")
    password = secrets.token_urlsafe(18) + "aA1"
    try:
        idp.admin_create_user(
            UserPoolId=pool,
            Username=email,
            MessageAction="SUPPRESS",
            UserAttributes=[
                {"Name": "email", "Value": email},
                {"Name": "email_verified", "Value": "true"},
                {
                    "Name": "custom:tenant_id",
                    "Value": state.setdefault("tenant", str(uuid.uuid4())),
                },
            ],
        )
        idp.admin_add_user_to_group(UserPoolId=pool, Username=email, GroupName="organiser")
    except idp.exceptions.UsernameExistsException:
        pass
    idp.admin_set_user_password(UserPoolId=pool, Username=email, Password=password, Permanent=True)
    auth = idp.initiate_auth(
        ClientId=client,
        AuthFlow="USER_PASSWORD_AUTH",
        AuthParameters={"USERNAME": email, "PASSWORD": password},
    )
    return auth["AuthenticationResult"]["AccessToken"]


def setup(args: argparse.Namespace) -> None:
    o = tf()
    base = o["api_url"].rstrip("/")
    run = datetime.now(UTC).strftime("%m%d%H%M")
    state = {
        "run": run,
        "fans": args.fans,
        "shards": math.ceil(args.fans / args.vus_per_shard),
        "vus_per_shard": args.vus_per_shard,
        "fallback": args.fallback,
        "base": base,
        "rate": args.rate,
    }
    token = organiser_token(o, state)
    # Fans arrive over 60 s starting START_AT (time for Karpenter nodes + token minting); the
    # sale opens 15 s after the last arrival, so everyone is in the pre-queue and gets shuffled.
    start_at = datetime.now(UTC) + timedelta(minutes=args.lead_minutes)
    sale = start_at + timedelta(seconds=75)
    event = api(
        "POST",
        f"{base}/org/events",
        token,
        {
            "name": f"Load test {run} ({args.fans:,} fans)",
            "venue": "SurgeGate demo arena",
            "starts_at": (sale + timedelta(days=30)).isoformat(),
            "sale_starts_at": sale.isoformat(),
            "per_buyer_limit": 4,
        },
    )
    seats = api("PUT", f"{base}/org/events/{event['id']}/seats", token, seat_csv(), "text/csv")
    queue = api(
        "PUT", f"{base}/org/events/{event['id']}/queue", token, {"admission_rate": args.rate}
    )
    state |= {
        "event_id": event["id"],
        "start_at": int(start_at.timestamp()),
        "sale_starts_at": sale.isoformat(),
    }
    save_run(state)
    print(
        json.dumps(
            {
                "event": event["id"],
                "seats": seats,
                "queue": queue,
                "start_at": start_at.isoformat(),
                "sale_starts_at": sale.isoformat(),
                "shards": state["shards"],
            },
            indent=2,
            default=str,
        )
    )


# --- start: the k6 Job -----------------------------------------------------------------------
def manifests(o: dict, st: dict, image: str) -> str:
    vus = st["vus_per_shard"]
    mem_gi = math.ceil(vus * st.get("mb_per_vu", 1.0) / 1024) + 1
    scripts = {
        n: (HERE / "k6" / n).read_text(encoding="utf-8") for n in ("fans.js", "mint_tokens.py")
    }
    cm = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {"name": f"k6-{st['run']}", "namespace": NS},
        "data": scripts,
    }
    env = [
        {"name": "BASE", "value": st["base"]},
        {"name": "EVENT_ID", "value": st["event_id"]},
        {"name": "VUS", "value": str(vus)},
        {"name": "START_AT", "value": str(st["start_at"])},
        {"name": "SEATS_PER_BUYER", "value": str(SEATS_PER_BUYER)},
        {"name": "TOKENS", "value": "/work/tokens.json"},
        {
            "name": "SHARD",
            "valueFrom": {
                "fieldRef": {
                    "fieldPath": "metadata.annotations['batch.kubernetes.io/job-completion-index']"
                }
            },
        },
    ]
    job = {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": f"k6-fans-{st['run']}",
            "namespace": NS,
            "labels": {"app": "k6-fans", "run": st["run"]},
        },
        "spec": {
            "completionMode": "Indexed",
            "completions": st["shards"],
            "parallelism": st["shards"],
            "backoffLimit": 0,
            "ttlSecondsAfterFinished": 7200,
            "template": {
                "metadata": {"labels": {"app": "k6-fans", "run": st["run"]}},
                "spec": {
                    "serviceAccountName": "k6",
                    "restartPolicy": "Never",
                    "nodeSelector": {"surgegate.io/pool": "loadgen"},
                    "tolerations": [
                        {
                            "key": "surgegate.io/loadgen",
                            "operator": "Equal",
                            "value": "true",
                            "effect": "NoSchedule",
                        }
                    ],
                    "volumes": [
                        {"name": "work", "emptyDir": {}},
                        {"name": "scripts", "configMap": {"name": f"k6-{st['run']}"}},
                    ],
                    "initContainers": [
                        {
                            "name": "mint",
                            "image": image,
                            "command": ["python", "/scripts/mint_tokens.py"],
                            "env": [
                                {"name": "KEY_SECRET_ID", "value": o["loadtest_key_secret_id"]},
                                {"name": "ISSUER", "value": o["loadtest_issuer"]},
                                {"name": "AUDIENCE", "value": o["loadtest_audience"]},
                                {"name": "RUN_ID", "value": st["run"]},
                                {"name": "VUS", "value": str(vus)},
                            ],
                            "volumeMounts": [
                                {"name": "work", "mountPath": "/work"},
                                {"name": "scripts", "mountPath": "/scripts"},
                            ],
                            "resources": {
                                "requests": {"cpu": "500m", "memory": "256Mi"},
                                "limits": {"memory": "512Mi"},
                            },
                        }
                    ],
                    "containers": [
                        {
                            "name": "k6",
                            "image": K6_IMAGE,
                            "args": ["run", "--quiet", "/scripts/fans.js"],
                            "env": env,
                            "volumeMounts": [
                                {"name": "work", "mountPath": "/work"},
                                {"name": "scripts", "mountPath": "/scripts"},
                            ],
                            "resources": {
                                "requests": {"cpu": "1500m", "memory": f"{mem_gi}Gi"},
                                "limits": {"memory": f"{mem_gi + 2}Gi"},
                            },
                        }
                    ],
                },
            },
        },
    }
    head = [
        {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": NS}},
        {"apiVersion": "v1", "kind": "ServiceAccount", "metadata": {"name": "k6", "namespace": NS}},
    ]
    return "\n---\n".join(json.dumps(d) for d in [*head, cm, job])


def start(args: argparse.Namespace) -> None:
    o, st = tf(), run_state()
    if not st.get("event_id"):
        sys.exit("run setup first")
    st["mb_per_vu"] = args.mb_per_vu
    tag = kubectl(
        "-n",
        "booking",
        "get",
        "rollout",
        "booking-api",
        "-o",
        "jsonpath={.spec.template.spec.containers[0].image}",
        check=False,
    ).strip()
    image = (
        tag
        or json.loads(kubectl("-n", "booking", "get", "deploy", "booking-api", "-o", "json"))[
            "spec"
        ]["template"]["spec"]["containers"][0]["image"]
    )
    lead = st["start_at"] - time.time()
    if lead < 120:
        print(f"WARNING: only {lead:.0f} s until START_AT; arrivals will be compressed")
    print(kubectl("apply", "-f", "-", stdin=manifests(o, st, image)))
    save_run(st)
    print(
        f"{st['shards']} shards x {st['vus_per_shard']} VUs; fans arrive from "
        f"{datetime.fromtimestamp(st['start_at'], UTC).isoformat()} for 60 s"
    )


# --- watch / check (SQL in a booking-api pod: the RDS secret never leaves the cluster) -------
SQL = r"""
import json, os
from sqlalchemy import text
from app.db import get_engine
e = os.environ.get("EVT") or "{event}"
q = {
 "seats": "SELECT status, count(*) FROM seats WHERE event_id = :e GROUP BY status",
 "paid_orders": "SELECT count(*), coalesce(sum(n),0) FROM (SELECT o.id, count(i.id) n FROM orders o JOIN order_items i ON i.order_id = o.id WHERE o.event_id = :e AND o.status = 'paid' GROUP BY o.id) x",
 "seat_on_two_paid_orders": "SELECT count(*) FROM (SELECT i.seat_id FROM order_items i JOIN orders o ON o.id = i.order_id WHERE o.event_id = :e AND o.status = 'paid' GROUP BY i.seat_id HAVING count(*) > 1) x",
 "sold_flag_twice": "SELECT count(*) FROM (SELECT seat_id FROM order_items i JOIN orders o ON o.id = i.order_id WHERE o.event_id = :e AND i.sold GROUP BY seat_id HAVING count(*) > 1) x",
 "sold_seat_without_paid_order": "SELECT count(*) FROM seats s WHERE s.event_id = :e AND s.status = 'sold' AND NOT EXISTS (SELECT 1 FROM order_items i JOIN orders o ON o.id = i.order_id WHERE i.seat_id = s.id AND o.status = 'paid')",
 "paid_item_on_unsold_seat": "SELECT count(*) FROM order_items i JOIN orders o ON o.id = i.order_id JOIN seats s ON s.id = i.seat_id WHERE o.event_id = :e AND o.status = 'paid' AND s.status <> 'sold'",
 "buyer_over_limit": "SELECT count(*) FROM (SELECT o.buyer_id FROM orders o JOIN order_items i ON i.order_id = o.id JOIN events ev ON ev.id = o.event_id WHERE o.event_id = :e AND o.status = 'paid' GROUP BY o.buyer_id, ev.per_buyer_limit HAVING count(*) > ev.per_buyer_limit) x",
 "tickets": "SELECT count(*), count(DISTINCT seat_id) FROM tickets WHERE event_id = :e",
 "emails_sent": "SELECT count(*) FILTER (WHERE ticket_email_sent_at IS NOT NULL), count(*) FROM orders WHERE event_id = :e AND status = 'paid'",
 "active_holds": "SELECT count(*) FROM holds WHERE event_id = :e AND status = 'active'",
 "orders_by_status": "SELECT status, count(*) FROM orders WHERE event_id = :e GROUP BY status",
}
out = {}
with get_engine().connect() as c:
    for k, s in q.items():
        rows = c.execute(text(s), {"e": e}).all()
        out[k] = [list(map(str, r)) for r in rows]
print(json.dumps(out))
"""


def sql(event_id: str) -> dict:
    pod = kubectl(
        "-n",
        "booking",
        "get",
        "pods",
        "-l",
        "app.kubernetes.io/name=booking-api",
        "--field-selector=status.phase=Running",
        "-o",
        "jsonpath={.items[0].metadata.name}",
    ).strip()
    out = kubectl(
        "-n",
        "booking",
        "exec",
        "-i",
        pod,
        "-c",
        "booking-api",
        "--",
        "python",
        "-",
        stdin=SQL.replace("{event}", event_id),
    )
    return json.loads(out.strip().splitlines()[-1])


def sold_count(r: dict) -> int:
    return sum(int(n) for status, n in r["seats"] if status == "sold")


def watch(args: argparse.Namespace) -> None:
    o, st = tf(), run_state()
    token = organiser_token(o, st)
    while True:
        r = sql(st["event_id"])
        sold, holds = sold_count(r), int(r["active_holds"][0][0])
        pods = kubectl(
            "-n",
            NS,
            "get",
            "pods",
            "-l",
            f"run={st['run']}",
            "-o",
            "jsonpath={range .items[*]}{.status.phase} {end}",
            check=False,
        ).split()
        print(
            f"{datetime.now(UTC):%H:%M:%S} sold {sold}/{SEATS} active holds {holds} "
            f"orders {r['orders_by_status']} k6 pods {dict((p, pods.count(p)) for p in set(pods))}",
            flush=True,
        )
        if sold >= SEATS and holds == 0 and not st.get("paused_at"):
            api(
                "PATCH",
                f"{st['base']}/org/events/{st['event_id']}/queue",
                token,
                {"action": "pause"},
            )
            st["paused_at"] = datetime.now(UTC).isoformat()
            st["sold_out_at"] = st["paused_at"]
            save_run(st)
            print("SOLD OUT -> queue paused: waiting fans end with 'sale over'", flush=True)
        if pods and all(p in ("Succeeded", "Failed") for p in pods):
            print("all k6 shards finished")
            return
        time.sleep(args.every)


def check_cmd(_: argparse.Namespace) -> None:
    st = run_state()
    r = sql(st["event_id"])
    sold = sold_count(r)
    checks = {
        "sold <= 2,000 seats": sold <= SEATS,
        "no seat on two paid orders": r["seat_on_two_paid_orders"][0][0] == "0",
        "no seat sold twice (order_items.sold)": r["sold_flag_twice"][0][0] == "0",
        "every sold seat has a paid order": r["sold_seat_without_paid_order"][0][0] == "0",
        "every paid seat is marked sold": r["paid_item_on_unsold_seat"][0][0] == "0",
        "nobody over the per-buyer limit": r["buyer_over_limit"][0][0] == "0",
        "paid seats == sold seats": int(r["paid_orders"][0][1]) == sold,
    }
    st["sql"] = r
    st["oversold_check"] = checks
    save_run(st)
    print(json.dumps(r, indent=2))
    for name, ok in checks.items():
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not all(checks.values()):
        sys.exit(1)


# --- collect: add up the shards --------------------------------------------------------------
def collect(_: argparse.Namespace) -> None:
    st = run_state()
    pods = kubectl(
        "-n",
        NS,
        "get",
        "pods",
        "-l",
        f"run={st['run']}",
        "-o",
        "jsonpath={.items[*].metadata.name}",
    ).split()
    shards = []
    for pod in pods:
        for line in kubectl("-n", NS, "logs", pod, "-c", "k6", check=False).splitlines():
            if line.startswith("K6_SUMMARY "):
                shards.append(json.loads(line[len("K6_SUMMARY ") :]))
    total = lambda m, f="count": sum(s["metrics"].get(m, {}).get(f, 0) for s in shards)  # noqa: E731
    result = {
        "run": st["run"],
        "event_id": st["event_id"],
        "profile": "FALLBACK (smaller 50k: fewer, bigger VUs)"
        if st.get("fallback")
        else "full: 1 VU = 1 fan",
        "planned_fans": st["fans"],
        "shards_reported": len(shards),
        "shards_planned": st["shards"],
        "real_vus": total("vus_max", "max"),
        "joins_ok_rate": (
            total("fan_join_ok", "passes")
            / max(1, total("fan_join_ok", "passes") + total("fan_join_ok", "fails"))
        ),
        "admitted": total("fan_admitted"),
        "paid_orders": total("fan_paid"),
        "seats_paid": total("seats_paid"),
        "sold_out_at_seat_map": total("fan_sold_out_at_seat_map"),
        "sale_over_while_waiting": total("fan_sale_over_while_waiting"),
        "timed_out": total("fan_timed_out"),
        "hold_409": total("hold_conflict_409"),
        "hold_gave_up": total("fan_hold_gave_up"),
        "http_requests": total("http_reqs"),
        "http_429_503": total("http_429_or_503"),
        "http_5xx": total("http_5xx"),
        # p95 per shard (k6 trends can't be merged exactly): the worst shard is reported
        "p95_ms_worst_shard": {
            stage: max(
                (
                    s["metrics"].get(f"http_req_duration{{stage:{stage}}}", {}).get("p(95)", 0)
                    for s in shards
                ),
                default=0,
            )
            for stage in ("join", "serving", "position", "admit", "seats", "hold", "order", "pay")
        },
        "sold_out_at": st.get("sold_out_at"),
        "sale_starts_at": st.get("sale_starts_at"),
    }
    st["result"] = result
    save_run(st)
    out = ROOT / "docs" / "progress" / "day-10" / f"loadtest-{st['run']}.json"
    out.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    print(f"-> {out.relative_to(ROOT)}")


# --- cleanup -------------------------------------------------------------------------------
def cleanup(_: argparse.Namespace) -> None:
    o, st = tf(), run_state()
    kubectl("-n", NS, "delete", "job", f"k6-fans-{st['run']}", "--ignore-not-found", check=False)
    kubectl("-n", NS, "delete", "configmap", f"k6-{st['run']}", "--ignore-not-found", check=False)
    if st.get("organiser"):
        try:
            boto3.client("cognito-idp", region_name=REGION).admin_delete_user(
                UserPoolId=o["cognito_user_pool_id"], Username=st["organiser"]
            )
        except Exception as exc:  # noqa: BLE001
            print(f"organiser not deleted: {exc}")
    print(f"cleaned run {st['run']} (results kept in {RUN_FILE.name})")


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("keygen").set_defaults(fn=keygen)
    h = sub.add_parser("headroom")
    h.add_argument("--fans", type=int, default=50000)
    h.add_argument("--rate", type=int, default=600)
    h.set_defaults(fn=headroom)
    s = sub.add_parser("setup")
    s.add_argument("--fans", type=int, required=True)
    s.add_argument("--vus-per-shard", type=int, default=5000)
    s.add_argument(
        "--rate", type=int, default=600, help="admission rate (fans per minute), the ceiling"
    )
    s.add_argument(
        "--lead-minutes", type=float, default=6, help="minutes until fans start arriving"
    )
    s.add_argument(
        "--fallback", action="store_true", help="label the run as the smaller-50k fallback"
    )
    s.set_defaults(fn=setup)
    st = sub.add_parser("start")
    # measured 26 Nov: 2,000 idle VUs = 420 MB (0.21 MB/VU); 1.0 leaves room for open connections
    st.add_argument(
        "--mb-per-vu", type=float, default=1.0, help="k6 memory per VU (re-measure in the 10k run)"
    )
    st.set_defaults(fn=start)
    w = sub.add_parser("watch")
    w.add_argument("--every", type=int, default=15)
    w.set_defaults(fn=watch)
    sub.add_parser("check").set_defaults(fn=check_cmd)
    sub.add_parser("collect").set_defaults(fn=collect)
    sub.add_parser("cleanup").set_defaults(fn=cleanup)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
