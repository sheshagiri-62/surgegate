# Week 2 · Day 7 · Task 04 — Webhook → SQS → order worker (exactly once) + the late-payment rule

- **Date:** 2026-11-24
- **Phase / milestone:** Phase 4 → M4 ("a duplicate webhook changes nothing, an unpaid hold is
  released after 10 minutes")
- **Status:** Done, verified live through CloudFront. This also covers the plan's Day 7 Task 4,
  the late-payment rule.
- **Commit / PR:** [#47](https://github.com/sheshagiri-62/surgegate/pull/47) (squash `a307574`),
  deployed by `1a9155b ci: deploy booking-api a307574caa48` and
  `32867b3 ci: deploy mock-pay a307574caa48`

## 1. What the task was

The plan's Day 7 Tasks 3 and 4:
- *"Webhook endpoint: verify signature, put on SQS; order worker confirms exactly once by
  payment ID."*
- *"Late-payment rule: re-hold if seats are free, otherwise refund (test mode) and notify."*

A payment provider may send the same webhook several times, late, or at the moment the hold
timer fires. The seat must still be sold exactly once, the buyer charged exactly once, and a
buyer whose seats are gone gets their money back.

Decisions you made:
- the worker is a pod in the cluster;
- the Step Functions timer is not cancelled;
- the release Lambda locks the hold first;
- a late re-hold over the per-buyer limit is refunded;
- an unknown order goes to the DLQ (not deleted);
- the alarm email address stays out of Git;
- one poison-message demo;
- the report must cover the outbox trade-off.

## 2. What I did, step by step

1. **Release Lambda lock order:** `SELECT … FOR UPDATE` on the hold first, then the seats. This
   is the same order as the new worker, so they can't deadlock. Added a test proving the release
   waits on a locked hold.
2. **Webhook endpoint** `POST /webhooks/razorpay` (booking API): raw-body HMAC with a
   constant-time compare, 400/413 refusals, then SQS and a 200 (503 if SQS is down).
3. **Order worker** `app/order_worker.py`: one transaction per message, deleted from SQS only
   after the commit, running as its own Deployment (same image, its own service account and
   role).
4. **Provider `refund()`**, plus a Razorpay-shaped, idempotent `POST /v1/payments/{id}/refund`
   in mock-pay.
5. **Buyer app:** after a failed payment, the next try uses a new idempotency key, so it creates
   a new order for the same hold.
6. **Terraform** (`async` module + dev), plan shown, then applied:
   - payments queue and DLQ;
   - DLQ alarm → SNS `surgegate-dev-alerts` → email;
   - order-worker role;
   - booking-api `SendMessage`.
7. **Tests:**

   | Suite | Passed | New |
   |---|---|---|
   | booking API | 135 | 14 payment-flow tests |
   | mock-pay | 15 | |
   | workers | 6 | |
   | buyer | 24 | |

   PR #47: 11 green checks; CI plans showed No changes.
8. **Live:** merge, deploy, then 5 scenarios through CloudFront and the poison-message demo.

### Commands I ran

```bash
# code + tests (local PostgreSQL in Docker, 127.0.0.1)
cd services/workers && python -m pytest -q          # 6 passed (incl. lock order)
cd services/booking-api && python -m pytest -q      # 135 passed
python -m pytest -q tests/test_payment_flow.py -s   # race outcomes: {'paid': 15, 'paid_late': 15} (x3 runs)
cd services/mock-pay && python -m pytest -q         # 15 passed
cd web/buyer && npm run lint && npm run typecheck && npm test && npm run build
helm lint deploy/helm/booking-api && helm template ... # worker pods don't match the Service selector

# infrastructure
terraform fmt -recursive infra; terraform -chdir=infra/envs/dev validate; tflint
terraform -chdir=infra/envs/dev plan ... -out=webhook.tfplan        # failed: ExpiredToken
aws login --profile surgegate                                       # you
aws s3api get-object ... envs/dev/terraform.tfstate.tflock          # stale lock 997c3deb… (my plan)
terraform -chdir=infra/envs/dev force-unlock -force 997c3deb-a8f0-b5f7-be14-c405eb085a2f   # after your OK
terraform -chdir=infra/envs/dev plan ... -out=webhook.tfplan        # 9 add, 3 change, 0 destroy
terraform -chdir=infra/envs/dev apply webhook.tfplan                # after your "yes": 9 added, 2 changed
aws sqs get-queue-attributes / sns get-subscription-attributes / cloudwatch describe-alarms

git push -u origin feat/payments-webhook; gh pr create ... (#47); gh pr merge 47 --squash
gh run watch <build-deploy> <build-deploy-mock-pay>   # both success
kubectl -n booking rollout status deploy/booking-api deploy/booking-api-order-worker

# live (scratchpad scripts; tokens, passes and secrets never printed)
python tests/load/k6/load_users.py create 4
kubectl -n booking exec -i <pod> -- python - <sub> <event> < mint_pass.py         # x4
kubectl -n booking exec -i <pod> -- python - order_TJCJ… pay_82wS… 300000 < sign_webhook.py
python payments_live.py old | normal | late | resold
kubectl -n booking logs deploy/booking-api-order-worker
kubectl -n mock-pay port-forward svc/mock-pay 18081:80; curl .../mockpay/test/orders/<order>
aws logs filter-log-events --log-group-name /aws/events/surgegate-dev-sale-events ...
# poison demo: signed webhook for order_POISONDEMO0001 -> watch queue/DLQ/alarm -> purge DLQ
python tests/load/k6/load_users.py delete 4
```

### Files created or changed

| File | What it does |
| --- | --- |
| `services/booking-api/app/routes/webhooks.py` | The endpoint: size limit, signature, queue, fast 200 |
| `services/booking-api/app/payment_queue.py` | SQS client and `send()` |
| `services/booking-api/app/order_worker.py` | `process()` (one transaction), `handle_message()`, the long-poll loop |
| `services/booking-api/app/payments.py` | `refund()` on the interface and the mock client |
| `services/booking-api/tests/test_payment_flow.py` | 14 tests incl. duplicate, bad signature, late free/resold/limit, race |
| `services/booking-api/tests/conftest.py`, `alembic/versions/0002_…` | Empty-schema test start; downgrade limits documented |
| `services/workers/src/sg_workers/release_hold.py` (+ test) | Lock the hold row first |
| `services/mock-pay/app/main.py` (+ tests) | Idempotent refund endpoint; refunds in the test view |
| `deploy/helm/booking-api/templates/order-worker.yaml`, `values.yaml`, `_helpers.tpl` | Worker Deployment + service account; `PAYMENTS_QUEUE_URL` |
| `infra/modules/async/*` | Queue, DLQ, redrive-allow policy, alarm, SNS topic + email subscription |
| `infra/envs/dev/order_worker.tf`, `booking_api.tf`, `main.tf`, `variables.tf` | Worker role + Pod Identity; `SendMessage`; alert wiring |
| `infra/envs/dev/alerts.auto.tfvars` | **Not committed** (git-ignored): the alert email address |
| `web/buyer/src/lib/checkout.ts` (+ test), `app/event/page.tsx` | New key after a failed payment |

## 3. How it works

**Exactly once, simply.** Think of a cashier with a stamp book of receipt numbers. If the same
receipt comes in twice, it's already stamped, so the second one changes nothing. Here the
"stamp" is a row in `payments` with the provider's **payment ID** as a unique key. The worker
inserts it with `ON CONFLICT DO NOTHING`. If nothing was inserted, it's a duplicate, and the
worker stops.

**Why one transaction?** The payment row, the seats becoming `sold`, the hold becoming
`converted` and the order becoming `paid` all commit together or not at all. If the stamp were
committed first and the worker crashed before confirming, the retry would see "already stamped",
and a paid order would never be confirmed.

```
provider ──POST /webhooks/razorpay (raw body + X-Razorpay-Signature)──► CloudFront ─► ALB ─► booking API
   400 bad/missing signature (nothing queued) · 413 too big · 200 {"status":"queued"} · 503 SQS down
                                                              │ SendMessage (raw body)
                                                              ▼
                     SQS surgegate-dev-payments (visibility 60 s, long poll 20 s) ──5 failures──► DLQ ─► alarm ─► SNS ─► email
                                                              │
                                                 order-worker pod (one transaction per message)
     lock ORDER (by provider order id) → INSERT payment ON CONFLICT DO NOTHING → lock HOLD → seats
       hold active   : seats held by this hold → sold; items sold; hold converted; order paid
       hold released : all seats free AND within the per-buyer limit → re-held, paid; else refund
       payment.failed: order failed; hold untouched
     COMMIT → delete message → publish order_paid / payment_refunded → Kinesis → Pipe → EventBridge
```

**The race with the hold timer.** The worker and the release Lambda both lock the **hold row
first**. Whoever gets the lock goes first, and the other then sees the new state:
- **Worker first:** the seats are `sold`. The release's `WHERE status='held'` matches nothing,
  so it releases and publishes nothing.
- **Release first:** the hold is `released` and the seats are free. The worker takes the
  late-payment path and re-holds them, so the buyer still gets the seats.

Either way exactly one path does the work, and there is never a paid order with a free seat.
That is why the timer is **not cancelled**: `StopExecution` would add an API call, IAM and a
failure mode, and the conditional updates already make a late release harmless.

**Trade-off: refund inside the transaction vs an outbox (you asked for this).**
- **What we do now:** when the seats are gone, the worker calls `provider.refund()` *inside* the
  database transaction, with a 5 s timeout. Then it commits.
  - **Why it's safe:** the refund is **idempotent per payment** (the mock returns the same
    `rfnd_…` for the same payment; Razorpay refunds are keyed by payment too). If the call fails,
    the transaction (including the payment row) rolls back, and SQS retries. If the worker
    crashes *after* refunding but *before* committing, the retry gets the same refund back,
    never a second one. Verified by `test_refund_is_idempotent_on_retry`.
  - **Cost:** for up to 5 s the transaction holds row locks on the order and hold while waiting
    on the network. Refunds are rare (late payment *and* the seat resold), so at our scale that
    is fine.
- **At scale, the outbox pattern:** the transaction only *records* "refund needed" in an
  `outbox` table, in the same commit as the payment row. A separate relay reads the outbox,
  calls the provider and marks the row done. It retries forever and is idempotent by payment ID.
  - **What it gains:** no network call while holding database locks; refunds survive a long
    provider outage without the message going to the DLQ; and `order_paid` /
    `payment_refunded` events become **guaranteed**. Today they are best-effort after the
    commit: if Kinesis is down for that second, the event is lost, though the order is correct.
  - **What it costs:** one more table, a relay process, and "refunded" becoming a
    pending → refunded state the buyer sees for a few seconds. I'd switch when refunds or event
    consumers (live dashboard, audit) become critical, which is likely Day 8 for the audit
    consumer.

## 4. Errors I hit and how I fixed them

| # | Error (exact message) | Cause | Fix |
| --- | --- | --- | --- |
| 1 | `psycopg.errors.UniqueViolation: could not create unique index "uq_orders_idempotency_key"` / `DETAIL: Key (idempotency_key)=(001cced4-…) is duplicated.` | The test fixture began with `alembic downgrade base`. Migration 0002's downgrade re-adds the old global key rule, which data valid under the new per-buyer rule (two buyers, one key) breaks. | The fixture starts from an empty schema (`DROP SCHEMA public CASCADE`), and the migration documents that its downgrade refuses such data, on purpose |
| 2 | `AssertionError: assert ['seat_held', 'order_paid'] == ['order_paid']` | The hold also publishes `seat_held`; my assertion was too strict | Count only `order_paid` (exactly 1) |
| 3 | `AssertionError: both orders should have happened` (`race outcomes: {'paid': 30}`) | The release opens a new pg8000 connection (slower), so the worker always won and the race didn't test both orders | Jitter on alternating rounds (worker 50–250 ms, release 0–30 ms): 15/15 both ways, 3 runs |
| 4 | ruff `S311 Standard pseudo-random generators are not suitable for cryptographic purposes`; `E501 Line too long` ×3 | Test jitter uses `random`; long lines | `# noqa: S311 - test timing jitter`; shorter lines |
| 5 | `AssertionError: ('infra/envs/dev/main.tf', '  sale_events_stream = module.events.stream_name…')` | My edit script's anchor text appears in two module blocks | Anchored on the unique `kms_key_arn` line plus the following lines |
| 6 | `ExpiredToken: The security token included in the request is expired` (plan) and `Error releasing the state lock … unable to retrieve file from S3 bucket` | The `aws login` session ended mid-plan; Terraform then couldn't delete its lock file | You logged in again. The lock (`997c3deb…`, `OperationTypePlan`, this machine, created 04:18:34 UTC, 2 s after my plan started; no Terraform running; state unchanged since 21:09) was force-unlocked with your OK |
| 7 | eslint `Do not use window.location.assign() to navigate to internal Next.js pages` | The "already paid" redirect went to an internal page | `router.push(...)` |
| 8 | `ModuleNotFoundError: No module named 'yaml'` | The system Python lacks PyYAML (for my Helm selector check) | Used the queue virtualenv |
| 9 | `botocore.exceptions.EndpointConnectionError: Could not connect to the endpoint URL` / `dial tcp: lookup …eks.amazonaws.com: no such host` | Home network/DNS outage (nothing had been created) | Waited for DNS, re-ran |
| 10 | `403 {"detail":{"reason":"booking pass refused: pass belongs to someone else"…}}` | On Windows, Python's output lines end in `\r`, so my script minted passes for `"<sub>\r"`. The API's ownership check worked exactly as designed. | `tr -d '\r'` and re-minted |
| 11 | `NameError: name '__file__' is not defined` | My one-off debug `exec` of the live script | Called the API directly instead |

Also caught before deploy (no error message): the first worker pod template reused
`booking-api.labels`, so the pod would have matched the booking-api **Service selector** and been
registered in the ALB target group. The worker now has its own name label; `helm template`
confirms only the API pods match.

## 5. How I verified it works

- **Infrastructure:**
  - queue `surgegate-dev-payments`: VisibilityTimeout 60, long poll 20 s, `maxReceiveCount 5` →
    `surgegate-dev-payments-dlq`, SSE on;
  - alarm `OK`, actions → `surgegate-dev-alerts`;
  - email subscription `PendingConfirmation: false` (you confirmed it);
  - CI plan without the email file: **No changes** (the subscription is stable);
  - the address appears nowhere in Git or the plan output (`(sensitive value)`).
- **Deployed:** booking-api, `booking-api-order-worker` (`order worker started`) and mock-pay,
  all on `a307574caa48`.
- **Live through CloudFront** (4 dev test buyers, deleted afterwards):

  | # | Scenario | Result |
  | --- | --- | --- |
  | 1 | Today's pending order `437bd3ba` (hold already released by the timer at 21:32, seats A-1-1/A-1-2 free): signed webhook | 200 queued → worker **`paid_late`** → order `paid`, hold `converted`, both seats `sold` |
  | 2 | The same webhook again | 200 queued → worker **`duplicate`**; still **one** payment row `pay_82wS…` |
  | 3 | Bad signature / no signature | **400** `invalid signature` / **400** `missing signature` |
  | 4 | Normal: hold A-1-3/A-1-4, order, pay on the checkout page | `303` back to the buyer app → worker **`paid`** → order `paid` within seconds |
  | 5 | Late, seats free: hold A-1-5/A-1-6, order, release Lambda (`['A-1-5','A-1-6']`), pay | worker **`paid_late`** → order `paid` |
  | 6 | Late, seat resold: hold A-1-7/A-1-8, order, release, another buyer holds A-1-8 (201), pay | worker **`refunded`** "seats no longer free"; mock: refund `rfnd_xncK…` processed, 300000, payment `refunded`; the other buyer keeps A-1-8 |

- **Events on the EventBridge bus** (log group `/aws/events/surgegate-dev-sale-events`):
  `order_paid` ×3 (`late: true` for #1 and #5, `false` for #4) and `payment_refunded` ×1 (reason
  and refund ID).
- **Poison-message demo (once, then purged):** a correctly signed webhook for a non-existent
  order `order_POISONDEMO0001`, sent through CloudFront at 04:40:22 UTC.

  | Time (UTC) | What happened |
  | --- | --- |
  | 04:40:23 → 04:44:23 | worker `failed (receive 1…5): UnknownOrder('order_POISONDEMO0001')`, one receive every 60 s (the visibility timeout); the message was **not** deleted, as you asked |
  | by 04:45:49 | SQS moved it to `surgegate-dev-payments-dlq` (redrive after `maxReceiveCount` 5) |
  | 04:49:26 | alarm `OK → ALARM`; history: *"Successfully executed action arn:aws:sns:…:surgegate-dev-alerts"*, so the email was sent (about 3½ min after the DLQ: SQS metrics arrive late) |
  | after | peeked the DLQ (the message, `ApproximateReceiveCount` 6 incl. the peek), then **purged** it; the alarm returns to OK (OK action, second email) |

## 6. Cost impact

- **New billable resources:** nothing hourly.
  - SQS queue and DLQ: requests are within the free tier. The worker's long poll is about 3
    requests/minute while the cluster is up (about 130k/month if it ran all month).
  - CloudWatch alarm: $0.10/month.
  - SNS topic and email: free tier.
  - IAM: free.
  - The worker pod (25m CPU / 96 MiB) runs on the existing nodes.
  - 4 Cognito test users signed in once.
- **Teardown:** revert #47 and apply, which removes the queues, alarm, topic and roles. The
  worker pod goes with `make down` (the cluster).

## 7. Interview notes

- **Q:** How do you make payment webhooks idempotent?
  **A:** Verify the signature over the raw bytes, queue the event, and in the worker insert the
  payment with the provider's payment ID as a unique key (`ON CONFLICT DO NOTHING`), in the
  **same** transaction as the confirmation. A duplicate inserts nothing and changes nothing.
  Verified live: the same webhook twice gave one payment row and one confirm.
- **Q:** The buyer pays at 9:59 and the 10-minute timer fires at 10:00. What happens?
  **A:** Both sides lock the hold row first, so they run one after the other. If the payment
  wins, the seats are sold and the release finds no `held` seats. If the release wins, the
  payment becomes a "late payment": re-hold if every seat is still free and the buyer is within
  the limit, otherwise refund. A test runs the real release code against the worker 30 times in
  parallel and checks the end state every time.
- **Q:** Why a queue between the webhook and the database?
  **A:** The provider needs a fast 2xx, or it retries and eventually gives up. Bursts at sale
  time shouldn't hit PostgreSQL directly, and a failing message must not be lost. SQS gives
  retries with a visibility timeout, a DLQ after 5 failures, and an alarm. The demo showed a bad
  message ending in the DLQ and an email instead of disappearing.

## 8. Next task

The plan's Day 8 (Thu 26 Nov):
- **Task 1:** the ticket worker (PDF + QR to S3, email through SES; verify your test addresses
  in the SES sandbox). It can consume `order_paid`.
- **Task 2:** the `events` module, already done on Day 7 (ADR 002).
- **Next after that:** the consumers (live dashboard, analytics, audit) and the organiser
  dashboard.
