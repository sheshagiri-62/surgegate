# Week 2 · Day 9 Task 3 — Observability: logs, dashboard, Container Insights, X-Ray

- **Date:** 2026-11-25
- **Phase / milestone:** Phase 5 → M5
- **Status:** Done. Container Insights metrics and pod logs run in **demo only** (your cost
  decision); dev keeps traces, JSON logs and the dashboard.
- **Commit / PR:** [#64](https://github.com/sheshagiri-62/surgegate/pull/64) (logs, tracing,
  add-on, dashboard), [#66](https://github.com/sheshagiri-62/surgegate/pull/66) (Transaction
  Search, dev trim)

## 1. What the task was

Plan, Day 9 Task 3: *"Observability: structured logs, CloudWatch dashboards ('sale room'),
Container Insights, X-Ray through OpenTelemetry."* During a sale, the operator must see the
whole system on one screen and be able to follow one slow request from the edge to the database.

## 2. What I did, step by step

1. **Structured logs.** The Lambdas already logged JSON. The booking API and the order worker
   (EKS) now write one JSON object per line, uvicorn's access log included: `time`, `level`,
   `logger`, `message`, `service`, and the **X-Ray `trace_id`** when the request is traced
   (`app/telemetry.py`).
2. **OpenTelemetry → X-Ray.** The booking API and the order worker run the OTel SDK with spans for
   FastAPI, boto3 (DynamoDB, Kinesis, SQS, Step Functions, Secrets) and Redis. They use X-Ray trace
   IDs, honour the ALB's `X-Amzn-Trace-Id`, and **sample 10%**, which stays inside X-Ray's free
   allowance even at 50k users. Traces go over OTLP/HTTP to the CloudWatch agent. The Helm values
   set `OTEL_*` per container.
3. **Container Insights:** the `amazon-cloudwatch-observability` EKS add-on (v8.0.1, Pod Identity
   with `CloudWatchAgentServerPolicy` + `AWSXrayWriteOnlyAccess`).
   - Application Signals, span metrics and profiles are **off**, because they bill extra.
   - Its log groups were pre-created with 7-day retention (otherwise "never expire").
   - Measured: **~2,260 metrics, about 2.9 M observations a day, about $0.60/day.** Your decision:
     **off in dev** (`container_insights_metrics = false`, which keeps the agent only as the trace
     receiver), **on in demo** for the load test.
4. **"Sale room" dashboard** `surgegate-dev-sale-room` (free; first 3 dashboards). Its sections,
   in the order a buyer moves through the system:
   - edge: CloudFront requests and errors, WAF blocks and challenges per rule;
   - waiting room: queue API requests/4xx/5xx, Lambda p95 and errors, join backlog and its age,
     DynamoDB, Lambda concurrency;
   - booking API: p95/p99 against the 0.5 s SLO line, requests and 5xx, healthy targets;
   - payments and tickets: queues, DLQs, the ticket worker;
   - data: RDS, Redis, Kinesis (incoming, throttled, consumer lag);
   - pods: CPU, nodes, and the latest ERROR log lines.
5. **X-Ray Transaction Search** (account-wide, `infra/envs/shared`). The add-on sends OTLP to
   X-Ray's OTLP endpoint, which only accepts spans when the segment destination is CloudWatch Logs.
   - Destination set to CloudWatch Logs, with a log resource policy for `xray.amazonaws.com`.
   - Indexing at the free 1%.
   - `aws/spans` imported and set to 7 days.

### Commands I ran

```bash
pip index / PyPI JSON: opentelemetry-sdk 1.45.2, instrumentation 0.66b2 (29 Oct), sdk-extension-aws 2.1.0, propagator-aws-xray 1.0.2
pytest -q                                   # booking-api unit tests: 50 passed (CI full suite with Postgres: green)
helm template t deploy/helm/booking-api     # OTEL_* env on both containers
terraform -chdir=infra/envs/dev plan <up vars> -out=obs.tfplan    # 10 add, 0 change, 0 destroy
terraform -chdir=infra/envs/dev apply obs.tfplan
kubectl -n amazon-cloudwatch get pods; kubectl -n amazon-cloudwatch get svc cloudwatch-agent   # 4317 4318
gh pr merge 63 && gh pr merge 64                                  # image aea688fcc1d9 rolled out
terraform -chdir=infra/envs/shared plan -out=tracing.tfplan && terraform -chdir=infra/envs/shared apply tracing.tfplan
terraform -chdir=infra/envs/dev plan <up vars> -out=trim.tfplan   # add-on config only: 0/1/0
seq 1 1500 | xargs -P 12 -I{} curl -s -o /dev/null "$CF/org/events"
# X-Ray: GetTraceSummaries service("booking-api"); Logs: aws/spans
```

### Files created or changed

| File | What it does |
| --- | --- |
| `services/booking-api/app/telemetry.py`, `main.py`, `order_worker.py`, `requirements.txt` | JSON logs + OTel setup |
| `services/booking-api/tests/test_telemetry.py` | JSON line, X-Ray trace id, one-line exceptions, tracing off without an endpoint |
| `deploy/helm/booking-api/templates/*`, `values.yaml` | `OTEL_*` env, `tracing` values |
| `infra/modules/eks/observability.tf`, `variables.tf` | Add-on, Pod Identity, log groups, `container_insights_metrics` |
| `infra/modules/observability/*` | The sale-room dashboard |
| `infra/modules/{queue,edge}/outputs.tf` | `api_id`, ALB / target-group ARN suffixes |
| `infra/envs/shared/tracing.tf` | Transaction Search |

## 3. How it works

The three "pillars", for a beginner:
- **Metrics** are numbers over time (requests per minute, p95 latency). Dashboards and alarms are
  built on them.
- **Logs** are what happened, line by line. Writing them as JSON means CloudWatch Logs Insights
  can filter on any field (`level = "ERROR"`, a trace ID).
- **Traces** follow one request through every component: each step is a *span* with a start and a
  duration, and all spans share one *trace ID*.

In SurgeGate:
1. The ALB starts an X-Ray trace header.
2. The booking API continues it: a FastAPI span, with child spans for each DynamoDB, Kinesis,
   Redis or Secrets call.
3. The spans go to the CloudWatch agent on the node, then to X-Ray (Transaction Search stores them
   in `aws/spans`; 1% are indexed for the trace map).
4. The same trace ID is in that request's log lines, so you can jump from a slow trace to its logs.

**Sampling** (10%) keeps cost flat: a sale's traffic grows, but you only need a sample to see
where time goes.

## 4. Errors I hit and how I fixed them

| # | Error (exact message) | Cause | Fix |
| --- | --- | --- | --- |
| 1 | `SQLAlchemyInstrumentor only instruments "sqlalchemy >= 1.0.0, < 2.1.0", but currently installed version ("sqlalchemy 2.1.9") falls outside of that range, so nothing can be instrumented.` | The instrumentation doesn't support SQLAlchemy 2.1 yet | Tried `skip_dep_check=True`, with a test (next row) |
| 2 | `ImportError: The SQLAlchemy asyncio module requires that the Python 'greenlet' library is installed.` | On 2.1 the instrumentation wraps the async engine, which needs `greenlet`; **it would have crashed the pod at startup** | Dropped SQL instrumentation (no compiled dependency for an unsupported version). Database time = the request span minus its child spans; RDS metrics on the dashboard |
| 3 | `failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine` (101 test errors) | Docker was stopped (WSL shut down to free memory) | Unit tests locally (50 passed); the full Postgres suite ran green in CI |
| 4 | `Error: Inconsistent conditional result types` | `cond ? [ALB widgets] : [text widget]`: two different object shapes | Two filtered `for` expressions (`[for w in [...] : w if local.alb]`) |
| 5 | (caught before apply) the dashboard used `surgegate-dev-joins.fifo` | Guessed a FIFO queue; the real one is standard `surgegate-dev-joins` | Read the queue module; fixed the name |
| 6 | (caught in the plan) `~ "ORIGIN_VERIFY_REQUIRED" = "true" -> "false"` on 7 Lambdas | I planned on `main`, where #63 wasn't merged yet: applying would have **switched the queue protection off** | Deleted the plan; rebuilt the branch on #63 |
| 7 | X-Ray `GetTraceSummaries`: 0 traces; agent pipeline `otlphttp/cw_k8s_otlp_traces` → `https://xray.ap-south-1.amazonaws.com`; `GetTraceSegmentDestination`: `Destination: XRay` | X-Ray's OTLP endpoint only takes spans with **Transaction Search** on; the agent's own logging is `level: none`, so no error was shown | With your OK: destination CloudWatch Logs + log resource policy + 1% indexing (Terraform, shared) |
| 8 | `InvalidParameterException: Log groups starting with AWS/ are reserved for AWS.` | Terraform can't create `aws/spans` | Let X-Ray create it, then `import` it to set 7 days |
| 9 | (finding) Container Insights about $0.60/day, above my $0.40–0.50 estimate; the API server is only 11% of the metrics | 69% are per-pod metrics (several dimension sets per pod) | Your decision: dev metrics and logs off, demo on |
| 10 | (caught in the plan) the WAF ACL back to 1,800 s, and 4 log groups to be destroyed | Same stacking trap (#65 not merged); a `for_each` tied to the metrics switch | Built on #65's branch; log groups kept whenever the add-on runs (no data deleted) |
| 11 | `BatchGetTraces` returned nothing for a trace found in `aws/spans` | Only the indexed 1% are X-Ray traces | 1,500 requests → about 150 sampled → **2 indexed traces** (expected) |

## 5. How I verified it works

- **JSON logs:** `kubectl -n booking logs deploy/booking-api` →
  `{"time": "...", "level": "INFO", "logger": "uvicorn.access", "message": "... GET /org/events HTTP/1.1\" 401", "service": "booking-api", "trace_id": "1-6b06f962-0d5549fb29ca5d2fadc5f5bc"}`.
- **Spans:** `aws/spans` had 33 spans in 10 minutes from about 100 requests (10% sampled):
  `booking-api` 27 (`GET /org/events` + `http send`), `order-worker` 6 (`SQS.ReceiveMessage`).
- **X-Ray:** `GetTraceSummaries service("booking-api")` → 2 indexed traces, e.g.
  `1-6b06fa02-5229b0cf02ed8a43fc132d2c`: `GET /org/events` 401, 1.7 ms, 2 subsegments.
- **Add-on:** agent pods Running on the existing 2 nodes (no 3rd node); service ports 4317/4318;
  after the dev trim, Fluent Bit is gone and the agent stays.
- **Dashboard:** `surgegate-dev-sale-room` exists; the ALB section is filled (the ALB exists).

## 6. Cost impact

| Item | Cost |
| --- | --- |
| Dashboard | $0 (first 3 free) |
| Container Insights + pod logs, **demo only** | ~$0.60/day when on (measured in dev) |
| Transaction Search | span logs $0.67/GB (dev: cents; 50k test about $0.15); indexing 1% free |
| X-Ray traces | inside the free 100,000/month at 10% sampling |
| CloudWatch agent pods | run on the existing nodes |

## 7. Interview notes

- **Q:** Why sample traces instead of tracing every request?
  **A:** At 50,000 buyers, tracing everything costs money and adds overhead, and 10% already shows
  where the time goes. Sampling is decided at the edge of the request (parent-based), so a trace
  is complete or absent, never half there.
- **Q:** How do you go from an alarm to the cause?
  **A:** The alarm points to the sale-room dashboard, which shows which layer is red. Then X-Ray
  shows a slow request's spans and which call is slow. Then that trace ID in Logs Insights shows
  the exact log lines, including errors.
- **Q:** Container Insights was more expensive than you estimated. What did you do?
  **A:** I measured the real number of metrics instead of trusting the estimate, found the bulk
  was per-pod metrics (not the API server, which I was asked to trim), and gave the owner the
  numbers. We kept it for the load-test window in demo and turned it off in dev, keeping the
  agent only as the trace receiver.

## 8. Next task

Day 9 Task 4: SLO alarms, SNS email alerts, three runbooks.
