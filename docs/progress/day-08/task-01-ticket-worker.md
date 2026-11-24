# Week 2 · Day 8 · Task 01 — Ticket worker: PDF + QR to S3, email through SES

- **Date:** 2026-11-24
- **Phase / milestone:** Phase 4 → M4 ("a buyer goes from queue to paid ticket email in one run")
- **Status:** Done, verified live through CloudFront. **Awaiting your confirmation:**
  - how many ticket emails are in your inbox (expected **4**: 3 redriven orders + 1 fresh order);
  - whether the phone scan of a QR showed the `eyJ…` token.
- **Commit / PR:**
  - [#50](https://github.com/sheshagiri-62/surgegate/pull/50) (squash `4800951`), deployed by
    `e8857f3 ci: deploy booking-api 4800951a4c85`;
  - fix [#51](https://github.com/sheshagiri-62/surgegate/pull/51) (squash `473f6ea`).

## 1. What the task was

Plan, Day 8 Task 1: *"Ticket worker: PDF + QR code to S3, email through SES (verify your test
addresses in the SES sandbox)."*

When an order is paid, the buyer gets a PDF with **one QR code per seat**. Each QR carries a
**signed ticket token**, so the gate can verify it and mark it used once. The PDF is stored in
the private tickets bucket and can be downloaded again from "My tickets". A replayed `order_paid`
must **never** send a second email.

## 2. What I did, step by step

1. **Design (approved):**
   - an SQS job fed by an EventBridge rule on `order_paid`, plus a 5-minute sweep;
   - segno + a small PDF writer;
   - a **2-minute** email-claim window;
   - a claimed-but-unsent message is **not acked**.
2. **Worker** (`services/workers`, Lambda):
   - lock the order;
   - create the tickets idempotently;
   - claim the email;
   - write the PDF to S3;
   - send through SES;
   - record `sent_at` and the message ID;
   - publish `ticket_issued`.
3. **Ticket token** (HMAC, `kid`, `typ=ticket`) with `verify()` for the gate. A shared test
   vector keeps the worker's copy and the booking API's copy identical.
4. **PDF writer** (about 90 lines, no dependencies) + vendored **segno** (pure Python). I stayed
   well inside the 1-hour timebox, so no reportlab fallback was needed.
5. **Booking API:**
   - migration 0003: `tickets`, plus ticket-email columns on `orders`;
   - `GET /me/tickets` with 5-minute presigned links;
   - a buyer "My tickets" page.
6. **Terraform** (plans shown, merged first so migration 0003 was in place, then applied):
   - bootstrap: 1 change;
   - dev: 24 added, 2 changed.
7. **SES sandbox:** an identity for your address; you clicked the link and it shows `SUCCESS`.
8. **Live:**
   - the sweep bug found and fixed (#51);
   - the DLQ redriven: **39 copies → exactly 3 emails**;
   - a fresh order emailed in **3.3 s**;
   - an archive replay → no second email;
   - presigned link expiry checked.

### Commands I ran

```bash
# code + tests (local PostgreSQL in Docker, 127.0.0.1)
pip download segno==1.6.6 --no-deps; pip install --no-deps --target src/sg_workers/_vendor segno-*.whl
cd services/booking-api && alembic upgrade head      # 0003 on a fresh workers_test database
cd services/workers && python -m pytest -q           # 20 passed (later 21 with the sweep fix)
cd services/booking-api && python -m pytest -q       # 138 passed
cd web/buyer && npm run lint && npm run typecheck && npm test && npm run build

# infrastructure
terraform fmt -recursive infra; terraform validate (dev, bootstrap); tflint (async, dev)
terraform -chdir=infra/bootstrap plan -out=tickets.tfplan   # 0 add, 1 change
terraform -chdir=infra/envs/dev plan ... -out=tickets.tfplan # 24 add, 3 change
gh pr create (#50); gh pr merge 50 --squash                  # migration 0003 via Argo CD
terraform -chdir=infra/bootstrap apply tickets.tfplan        # after your "yes"
terraform -chdir=infra/envs/dev apply tickets.tfplan         # 24 added, 2 changed

# the sweep bug
aws logs filter-log-events --log-group-name /aws/lambda/surgegate-dev-ticket-worker ...  # (needs MSYS_NO_PATHCONV=1)
terraform -chdir=infra/envs/dev plan ... -out=sweepfix.tfplan; terraform apply sweepfix.tfplan  # 0 add, 2 change
gh pr create (#51); gh pr merge 51 --squash

# after you verified the address
aws sesv2 list-email-identities                               # SUCCESS, SendingEnabled true
aws sqs start-message-move-task --source-arn ...tickets-dlq --destination-arn ...tickets   # 36, later 3 more
aws logs filter-log-events ... ; aws sesv2 get-account ; aws cloudwatch describe-alarms

# live checks (one dev test buyer; token and pass never printed)
python tests/load/k6/load_users.py create 1
kubectl -n booking exec -i <pod> -- python - <sub> <event> < mint_pass.py
python tickets_live.py order        # paid -> emailed in 3.3 s
aws events start-replay --event-source-arn ...archive/surgegate-dev-sale-events \
  --event-start-time 2026-11-24T15:59:41Z --event-end-time 2026-11-24T16:00:41Z \
  --destination Arn=...event-bus/surgegate-dev-sale-events,FilterArns=<order-paid rule>
python tickets_live.py mytickets    # 200, PDF via presigned link
python tickets_live.py expired      # 319 s later: 403 Request has expired
python tests/load/k6/load_users.py delete 1
```

### Files created or changed

| File | What it does |
| --- | --- |
| `services/workers/src/sg_workers/ticket_worker.py` | Handler (SQS batch + sweep), idempotent `issue()`, rendering, MIME, SES, S3 |
| `services/workers/src/sg_workers/ticket_token.py` | Sign / verify signed ticket tokens |
| `services/workers/src/sg_workers/pdf.py` | Dependency-free PDF writer (text + vector QR, one page per seat) |
| `services/workers/src/sg_workers/__init__.py`, `_vendor/segno` | Vendored pure-Python QR library on `sys.path` |
| `services/workers/tests/test_ticket_token_pdf.py`, `test_ticket_worker.py` | 15 new tests (incl. QR matrix vs segno, one email per order, sweep) |
| `services/booking-api/alembic/versions/0003_tickets.py`, `app/models.py` | `tickets` table; ticket-email columns |
| `services/booking-api/app/ticket_token.py`, `app/routes/tickets.py` | Same token code (gate); `GET /me/tickets` with presigned links |
| `services/booking-api/tests/test_tickets.py` | Shared vector; My tickets owner-only; 300 s link |
| `web/buyer/src/app/tickets/page.tsx`, `src/lib/api.ts` | "My tickets" page |
| `infra/modules/async/tickets.tf` (+ variables, outputs, versions) | Queue, DLQ, alarm, rule, Lambda, sweep, ticket key, SES identity + config set, SSM email setting |
| `infra/envs/dev/main.tf`, `variables.tf`, `booking_api.tf` | Wiring; booking-api may read `tickets/*` |
| `infra/bootstrap/iam.tf` | CI plan role may read the ticket key |
| `deploy/helm/booking-api/*` | `TICKETS_BUCKET` |
| `infra/envs/dev/alerts.auto.tfvars` | **Not committed:** sender / sandbox recipient address |

## 3. How it works

**Simply:** when a payment is confirmed, a "make tickets" job goes into a queue. A worker takes
the job and does the following:
1. it draws one QR code per seat into a PDF;
2. it saves the PDF in a private S3 bucket;
3. it emails the PDF to the buyer;
4. it writes down "email sent" in the database.

If the same job ever comes again (a retry, a duplicate, or someone replaying old events), the
worker sees "email sent" and stops.

```
order worker COMMIT → order_paid → Kinesis → Pipe → EventBridge bus
        rule detail.type = "order_paid" ──► SQS surgegate-dev-tickets (visibility 360 s, 5 tries → DLQ → alarm → email)
Scheduler every 5 min ──{"sweep": true}──┐                │
                                         ▼                ▼
                              ticket-worker Lambda (VPC; batch 5; ReportBatchItemFailures)
   lock order ─ not paid → ack │ sent → ack │ claimed < 2 min ago → NOT acked (retry)
   tickets INSERT … ON CONFLICT (order_item_id) DO NOTHING   (ticket id = uuid5(order item))
   claim email → COMMIT → PDF (1 page + 1 signed QR per seat) → S3 tickets/<event>/<order>.pdf (SSE-KMS)
   → SES (raw MIME, PDF attached, configuration set) → sent_at + message id → ticket_issued
buyer ── GET /me/tickets (Cognito) ──► presigned S3 GET, 5 minutes
```

- **The QR carries a signed token, not an ID.**
  - Format: `base64url(payload).base64url(HMAC-SHA256)`, with payload ticket, order, event,
    seat, `iat` = paid time, and `kid`.
  - Anyone can read an ID and print a copy; only we can produce a valid signature.
  - The ticket ID is derived from the order item (uuid5), so the token is the same every time.
    Re-issuing never makes an old printout invalid.
  - The gate (Day 8 Task 4) runs `verify()` and then
    `UPDATE tickets SET used_at = now() WHERE id = :tid AND used_at IS NULL`, so one use only.
- **Why SQS fed by an EventBridge rule, not a stream consumer:**
  - a ticket is a job, done once per order;
  - SQS retries one message (a stream consumer retries the whole shard batch);
  - SQS scales with the backlog;
  - the bus archive lets us **replay** `order_paid`, which is the live test.
- **Why a sweep:** `order_paid` is published best-effort after the payment commit (see the Day 7
  Task 4 outbox trade-off). The sweep is the safety net. Every 5 minutes it queues paid orders
  that are more than 2 minutes old and that **no run has ever claimed**.

**SES limit: no idempotency key.**
- SES `SendEmail` has no idempotency token. If the Lambda crashes *after* SES accepted the email
  but *before* `ticket_email_sent_at` commits, the claim expires after 2 minutes and the retry
  sends a second copy.
- We narrow that window. The send and the database update are adjacent, and the claim stops
  concurrent sends. Every replay or duplicate that arrives after `sent_at` is acked without
  sending (proven live below).
- Fully exactly-once email is impossible with an outside service that has no idempotency key.
  The honest guarantee is "at most one email per order except after a crash in that window".
  At scale, keep the SES `MessageId` and check delivery events before re-sending, or use a
  provider with idempotency keys.

## 4. Errors I hit and how I fixed them

| # | Error (exact message) | Cause | Fix |
| --- | --- | --- | --- |
| 1 | ruff `E501 Line too long` ×7 | Long SQL strings and f-strings | Wrapped |
| 2 | tflint `Missing version constraint for provider "random" in required_providers` | The `async` module now uses `random_password` | Added `hashicorp/random ~> 3.7` |
| 3 | (caught before running) `import segno` before anything put `_vendor` on `sys.path` | Only `db.py` added the vendor path, and isort puts third-party imports first | The package `__init__.py` adds `_vendor` to `sys.path` |
| 4 | (caught before running) `:ns_ids ->> i.id::text` on a text parameter | The JSON lookup needs `jsonb` | `CAST(CAST(:ids AS jsonb) ->> i.id::text AS uuid)` |
| 5 | `MessageRejected('… SendEmail operation: Email address is not verified. The following identities failed the check in region AP-SOUTH-1: <your address>')` | The SES identity was still `PENDING`: the worker ran (via the sweep) before you clicked the link | You verified it (`SUCCESS`), then I redrove the DLQ |
| 6 | **Design bug:** the queue grew (`9` in flight, then the DLQ `24`, then `36`) with log lines `"result": "claimed elsewhere: retry"` | The sweep re-queued paid orders whose job was **still retrying** (claimed, not sent), every 5 minutes, so copies piled up. Idempotency held: one claim, zero duplicate emails. | #51: the sweep only takes orders with `ticket_email_claimed_at IS NULL`; new test; applied (0 add / 2 change) |
| 7 | `InvalidParameterException … Value at 'logGroupName' failed to satisfy constraint: Member must satisfy regular expression pattern: [\.\-_/#A-Za-z0-9]+` (and a 10-minute watcher that found nothing) | **Git Bash path conversion** turned `/aws/lambda/…` into a Windows path before the AWS CLI saw it | `MSYS_NO_PATHCONV=1` for every AWS CLI call with a `/…` argument |
| 8 | `arithmetic syntax error: invalid arithmetic operator (error token is "None")`, then `ParamValidation: argument --event-start-time: expected one argument` | `--output text` printed the timestamp plus a pagination `None` line, which broke the date maths | `head -1` on the value |
| 9 | Replay `COMPLETED` but `EventLastReplayedTime: null`, and the worker saw nothing | **Archive ingestion lag:** I started the replay 31 s after the event, before EventBridge had written it to the archive (`EventCount` still 30) | Re-ran the same window 12 minutes later: replayed, then `skipped: email already sent` |
| 10 | `sed: -e expression #1, char 6: unterminated 's' command` | My log-parsing one-liner (quoting) | Read the lines with a simpler filter |

## 5. How I verified it works

- **Tests:**

  | Suite | Result |
  |---|---|
  | workers | 21 passed |
  | booking API | 138 passed (migration 0003 = models; shared vector) |
  | buyer | 24 passed |

  CI green on #50 and #51. The CI plans matched the saved ones, and the PR plan comment
  contains **no email address** (checked: 0 matches).
- **QR test you asked for:** `test_pdf_has_one_page_and_one_correct_qr_per_seat` rebuilds each
  QR from the PDF's drawn squares, **regenerates the token independently**, and compares the
  drawing with **segno's matrix** for that token. The first seat's token equals the shared
  vector.
- **SES identity:** `EMAIL_ADDRESS SUCCESS SendingEnabled=True` (sandbox: 200/day, 1/s).
- **Redrive: 39 copies → exactly 3 emails.**
  - Before: 3 paid orders, 2 tickets each, no email.
  - 36 messages moved back at 15:49:43 UTC, plus 3 later copies that reached the DLQ at
    receive 5 while the real send was in progress.
  - Worker logs: **`sent` ×3** (`437bd3ba` SES `…3fb1cc…`, `16d20e4b` `…3fb2c9…`,
    `3612227f` `…3fb1d1…`), `email already sent` acks for the rest, **0 errors**.
  - DLQ 0, queue 0. Alarm `ALARM → OK` at 15:59 UTC.
  - SES `SentLast24Hours` = 4: the 3 tickets + the 13:56–14:56 UTC hour, which holds only
    rejected ticket attempts, so it is almost certainly the verification email.
- **Fresh order through CloudFront:** order `7e96313d…` (A-1-7, A-1-8), paid on the mock
  checkout page at 16:00:10 UTC → **ticket email sent 3.3 s later** (SLO: under 5 minutes).
- **Replay:** EventBridge archive replay of 15:59:41–16:00:41, target the order-paid rule only →
  worker at 16:13:11: **`skipped: email already sent`**. SES sends 5 → 5: **no second email**.
- **My tickets:**
  - `GET /me/tickets` → 200, seats A-1-7/A-1-8, `emailed: true`;
  - presigned link → 200 `application/pdf`, 188,836 bytes, `%PDF-1.4`, `X-Amz-Expires=300`;
  - **the same link 319 s later → 403 `AccessDenied: Request has expired`**.
- **Your checks (awaiting confirmation):** inbox count of ticket emails (expected 4) plus the
  ALARM/OK emails; phone scan of one QR (expected: a long `eyJ…` text with one dot).

## 6. Cost impact

- **New billable resources:** nothing hourly.
  - Ticket key secret: $0.40/month.
  - DLQ alarm: $0.10/month.
  - SES: 4 ticket emails ≈ $0.0004.
  - SQS / Lambda / Scheduler: free tier.
  - S3: a few PDFs of about 190 KB; KMS requests are minimal with bucket keys.
  - SSM standard parameter: free.
- **Teardown:** revert #50/#51 and apply. Nothing is tied to `make down` except that the sweep
  turns off with the database (`sweep_enabled = enable_data`).

## 7. Interview notes

- **Q:** How do you avoid sending a ticket email twice?
  **A:** One job per order, and the order row records `email claimed` then `email sent`. A
  replay or duplicate that sees "sent" is acked without sending. One that sees a fresh claim is
  left on the queue to retry, never acked. Live: 39 queued copies produced exactly 3 emails, and
  an EventBridge archive replay produced none. SES has no idempotency key, so the remaining risk
  is a crash between SES accepting the email and our database write.
- **Q:** Why put a signed token in the QR instead of the ticket ID?
  **A:** An ID can be guessed or copied into a fake ticket. A token signed with our secret key
  proves we issued it, for this event and seat. The gate verifies the signature, then marks the
  ticket used in one conditional UPDATE, so a second scan of a screenshot is refused.
- **Q:** What did the sweep bug teach you?
  **A:** A safety net must not fight the main retry path. The sweep is for jobs that were never
  started (a lost event). A job that started and failed is already being retried by SQS and will
  reach the DLQ. Re-queuing it only made copies. Idempotency made the bug harmless; the alarm
  made it visible.

## 8. Next task

Day 8 Task 3: **consumers** (live dashboard over WebSocket, analytics to S3 + Athena, audit). I'll
propose the plan next session, before writing any code. Day 8 Task 2 (`events` module) was
already done on Day 7 (ADR 002).
