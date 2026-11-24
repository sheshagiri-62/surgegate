# Day 7 summary — planned for Wed 25 Nov, done Mon 23 → Tue 24 Nov 2026

One long session: it started on the afternoon of Mon 23 Nov (IST) and ran through Tue 24 Nov.
Dev was brought up once (`make up` from snapshot `surgegate-dev-pg-final-873e7969`, finished
about 17:29 UTC on 23 Nov) and is **still up** at the time of writing, as you asked, for Day 8.

## Finished

| Task | PRs | Report |
| --- | --- | --- |
| 0. Carry-overs: make on Windows fixed; snapshot restore + marker row; position polling only after the sale opens; CloudFront enabled (**M1 met**); VPC origin + internal ALB; k6 1,000/1,000 (**M3 met**) | [#36](https://github.com/sheshagiri-62/surgegate/pull/36) [#37](https://github.com/sheshagiri-62/surgegate/pull/37) [#38](https://github.com/sheshagiri-62/surgegate/pull/38) [#39](https://github.com/sheshagiri-62/surgegate/pull/39) [#40](https://github.com/sheshagiri-62/surgegate/pull/40) | [task-00-carry-overs](task-00-carry-overs.md) |
| 1. Sale events: Kinesis + EventBridge (Pipe, archive, log rule; ADR 002); producers joined / admitted / seat_held | [#41](https://github.com/sheshagiri-62/surgegate/pull/41) | [task-01-sale-events](task-01-sale-events.md) |
| 2. Step Functions hold timer + release Lambda (plan: Day 7 Task 1) | [#42](https://github.com/sheshagiri-62/surgegate/pull/42) [#43](https://github.com/sheshagiri-62/surgegate/pull/43) | [task-02-hold-timer](task-02-hold-timer.md) |
| 3. Orders with idempotency keys + checkout, with a Razorpay-shaped mock provider ([ADR 004](../../adr/004-mock-payment-provider.md)) (plan: Task 2) | [#44](https://github.com/sheshagiri-62/surgegate/pull/44) [#45](https://github.com/sheshagiri-62/surgegate/pull/45) [#46](https://github.com/sheshagiri-62/surgegate/pull/46) | [task-03-orders-checkout](task-03-orders-checkout.md) |
| 4. Webhook → SQS → order worker, exactly once; late-payment rule; DLQ alarm (plan: Tasks 3 + 4) | [#47](https://github.com/sheshagiri-62/surgegate/pull/47) [#48](https://github.com/sheshagiri-62/surgegate/pull/48) | [task-04-payments-webhook](task-04-payments-webhook.md) |

**Day 7 of the plan is complete.** Milestones: M1 and M3 met (Task 0). M4 needs Day 8: the
ticket email and the organiser's live view. Its other two checks already pass live: a duplicate
webhook changes nothing, and an unpaid hold is released by the timer.

Also done on the way:
- the 9 seats left `held` by holds made before the timer existed were released (9 → 0);
- the Day 9 WAF note is in the checklist: exclude `/webhooks/*`.

## Not finished / open items

- **M4** still needs the ticket email with PDF/QR (Day 8 Task 1) and the organiser's live view
  (Day 8 consumers + dashboard).
- **Sale events are best-effort** after the commit (Task 4 report: outbox at scale). The Day 8
  ticket plan includes a safety-net sweep, so a lost `order_paid` still gets a ticket.
- **Buyer site still runs on `localhost:3000`:** add the buyer CloudFront origin to the
  booking-API and mock-pay allow-lists when it's deployed there.
- **HTTPS on the CloudFront → ALB hop** waits for a domain (ADR 003); today it's a VPC origin
  (private) plus the origin header.
- **Real Razorpay:** blocked by business KYC (ADR 004). Switching is configuration plus one
  provider class.

## All errors of the day

Full details (exact messages and fixes) are in each task report. One line each:

| # | Task | Error (exact message, shortened) | Cause | Fix |
| --- | --- | --- | --- | --- |
| 1 | 0 | `RuntimeError: Could not determine home directory.` (inside make) | MSYS2 make from Git Bash lost 90 of 97 env vars | Guard + fail-fast (#36); run via `cmd //c "make …"` |
| 2 | 0 | Command blocked by the safety check (quoting) | Couldn't be parsed | Editor / script files |
| 3 | 0 | `SyntaxError: await in arguments not supported in 37` (CloudFront Function) | cloudfront-js-2.0 rule | Await into a variable |
| 4 | 0 | `Error acquiring the state lock … PreconditionFailed` (#39 CI) | My apply held the lock | Re-ran the CI job |
| 5 | 0 | `failed to upload state … no such host`; `Error releasing the state lock` | Network outage mid-apply | With your OK: force-unlock, state push (serial 94 > 92), untaint, final apply |
| 6 | 0 | `Post "https://api.github.com/graphql": net/http: TLS handshake timeout` | Flaky network | Retried |
| 7 | 0 | `File has not been read yet. Read it first` | Editor rule | Read, then edit |
| 8 | 1 | `psycopg.errors.ConnectionTimeout` (57 tests) | Docker Desktop not running | Started it, `docker start sg-pg sg-redis` |
| 9 | 1 | Pre-commit `Terraform fmt … Failed` | Formatting after staging | fmt, then commit |
| 10 | 1 | Pipe `ExecutionFailed` / `BadRequest`, `Target invocation failed partially.` | Empty dynamic detail-type, then (real cause, found with TRACE logs) a bare `<$.data>` template producing non-JSON | Fixed detail-type + JSON object input template; logs back to ERROR |
| 11 | 1 | (process) concluded too early | Diagnosed from one test | Read the rejected payload |
| 12 | 2 | ruff `E501 Line too long` | Long assert | Split |
| 13 | 2 | CI plan `2 to change`, `source_code_hash` drift | `*.pem` ignore rule hid the public RDS CA bundle from CI | Allow-listed and committed it |
| 14 | 2 | CI plan still drifting (`UMRH…`) | pip wrote CRLF RECORD files on Windows | Re-checkout as LF; zip-sync apply (approved) |
| 15 | 2 | `wsarecv: An established connection was aborted` | Network | Re-ran |
| 16 | 2 | `Blocked: sleep 30 followed by …` | Tool rule | `gh run watch` |
| 17 | 2 | `ImportError: cannot import name 'SessionLocal'` | Guessed a name | `_session_factory()` |
| 18 | 3 | `AssertionError: … ('POST', '/book/{event_id}/orders')` (pass guard test) | New `/book` route without a pass recipe (the guard worked) | Recipe for orders |
| 19 | 3 | `No module named pytest` | MSYS2 Python on PATH | Project venv |
| 20 | 3 | Test run hung in `psycopg … wait_conn` | `localhost` tries IPv6 `::1` first; Docker binds 127.0.0.1 | `127.0.0.1` in URLs |
| 21 | 3 | `UniqueViolation … "uq_orders_provider_order_id"` (7 tests) | Fake provider reused IDs across tests | Random IDs |
| 22 | 3 | ruff `S310` ×2, `E501` ×5 | `urlopen` schemes; long CSS | http(s)-only check + noqa; CSS constant |
| 23 | 3 | `unexpected EOF while looking for matching '''` | Nested heredocs | Python script via the editor |
| 24 | 3 | `Error: Module not installed` | Checkout not initialised | `terraform init` |
| 25 | 3 | `'eslint' is not recognized` | No node_modules | `npm ci` |
| 26 | 3 | `MissingDependencyException … "botocore[crt]"` | That venv lacked awscrt | Queue venv |
| 27 | 4 | `could not create unique index "uq_orders_idempotency_key"` (downgrade) | 0002 downgrade can't restore old global rules on new-rule data | Fixture starts from an empty schema; documented |
| 28 | 4 | `assert ['seat_held', 'order_paid'] == ['order_paid']` | Too-strict assertion | Count `order_paid` |
| 29 | 4 | `AssertionError: both orders should have happened` (`{'paid': 30}`) | Release always lost the race | Alternating jitter → 15/15 |
| 30 | 4 | ruff `S311` ×2, `E501` ×3 | Test jitter; long lines | noqa with reason; shorter lines |
| 31 | 4 | Edit script `AssertionError` (anchor in two module blocks) | Non-unique anchor | Unique anchor |
| 32 | 4 | `ExpiredToken` during plan + `Error releasing the state lock` | `aws login` session ended | You re-logged in; lock `997c3deb…` force-unlocked with your OK |
| 33 | 4 | eslint `Do not use window.location.assign() …` | Internal redirect | `router.push` |
| 34 | 4 | `No module named 'yaml'` | System Python | Queue venv |
| 35 | 4 | `EndpointConnectionError` / `no such host` | Home DNS outage | Waited, retried |
| 36 | 4 | `403 … "pass belongs to someone else"` | Windows `\r` in minted pass subs (the API check worked) | `tr -d '\r'` |
| 37 | 4 | `NameError: name '__file__' is not defined` | Debug `exec` | Direct call |
| 38 | Summary | `aws: [ERROR]: Your session has expired. Please reauthenticate using 'aws login'.`; AWS MCP tool `Unknown tool: 'aws___run_script'` | Login session ended again; the MCP tool was unavailable | You logged in again; billing read with the AWS CLI (read-only) |
| 39 | Summary | Cost Explorer daily totals all `$0` | The default view nets out the credits | Queried with `RECORD_TYPE` not in Credit/Refund/Tax (gross usage) |

Caught before they caused harm (no error message):
- the worker pod labels would have put the order worker into the ALB target group;
- the old `order_items UNIQUE(seat_id)` would have stopped a seat being re-sold after a failed
  order.

## Cost

Read from Cost Explorer on 24 Nov at 13:44 UTC, as **gross usage** (credits, refunds and tax
excluded). Cost Explorer runs several hours behind, so 24 Nov is partial.

| Day (UTC) | Gross usage |
| --- | --- |
| 19 Nov | $0.06 |
| 20 Nov | $1.25 |
| 21 Nov | $2.50 |
| 22 Nov | $0.13 |
| **23 Nov** | **$2.45** |
| **24 Nov (partial)** | **$1.24** |
| **Month to date** | **$7.61** |

23–24 Nov by service (gross, partial):

| Service | $ |
| --- | --- |
| EKS control plane | 1.06 |
| EC2 compute (2 nodes) | 0.81 |
| EC2 other (NAT gateway hours + data, EBS) | 0.70 |
| Load balancing (ALB) | 0.26 |
| RDS | 0.24 |
| ElastiCache | 0.20 |
| Kinesis | 0.18 |
| Secrets Manager | 0.10 |
| VPC | 0.06 |
| KMS | 0.04 |
| DynamoDB | 0.03 |

- **Credits:** $7.61 of credits applied month to date, so **net spend is $0.00** and about $132
  of the ~$140 credit is left. Budget `surgegate-monthly` ($45, alerts at $15/$30/$45): actual
  (net) $0.00, forecast $0.07.
- **Dev uptime today:** `make up` finished at about 17:29 UTC on 23 Nov, and dev is still up at
  13:44 UTC on 24 Nov, so **about 20.3 h × ~$0.35/h ≈ $7.10** for the hourly layer. Cost
  Explorer hasn't caught up yet; expect the 23 + 24 Nov total to reach about $7–8 gross.
- **New persistent items today:**
  - secrets ($0.40/month each): the payment keys version (no extra), the existing pass and
    origin keys;
  - 1 DLQ alarm: $0.10/month;
  - SQS, SNS, Step Functions, Lambda: free tier;
  - ECR `mock-pay`: about $0.01/month.
- **Cognito:** about 1,015 MAU this month, within the 10,000-MAU free tier.

## Still running (bills by the hour)

Dev is **up**, as you asked, at about **$0.35/h**:

| Item | About |
| --- | --- |
| EKS control plane | $0.10/h |
| 2 × t4g nodes | ~$0.07/h |
| NAT gateway | $0.056/h + data |
| Internal ALB | ~$0.0225/h |
| RDS db.t4g.micro | ~$0.017/h |
| ElastiCache | ~$0.017/h |
| Kinesis shard | $0.0175/h |
| CloudFront VPC origin | no extra charge |

Not hourly:
- **Persistent:** Step Functions, Lambdas, SQS queues, SNS, the DLQ alarms, secrets (about
  $0.40/month each), ECR, the CloudFront distribution (pay per request).
- **Run `cmd //c "make down"`** when you stop (about 25 minutes, including the VPC-origin
  wait), then `make billing-check`.

## Next day starts with

Day 8 Task 1: the **ticket worker** (plan proposed for your approval: `order_paid` → SQS →
ticket Lambda → PDF with one signed QR per seat → S3 (KMS) → SES email; "My tickets" with
presigned URLs). Then the consumers (live dashboard, analytics, audit), the organiser SSR
dashboard and the gate check-in. That completes M4.
