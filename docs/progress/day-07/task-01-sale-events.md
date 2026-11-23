# Week 2 · Day 7 · Task 01 — Sale events: EventBridge + Kinesis (ADR 002), producers in the queue Lambdas and the booking API

- **Date:** 2026-11-24 (early hours)
- **Phase / milestone:** Phase 4 → M4 ("the organiser watches it all update live")
- **Status:** Done for the queue producers (verified end to end). The booking API's `seat_held`
  producer goes live when this PR deploys.
- **Commit / PR:** see the Day 7 summary (`feat/events`)

## 1. What the task was

You asked to start Day 7 by switching sale events to **EventBridge + Kinesis** (ADR 002; in the
plan this is Day 8's `events` module and producers). Every state change in a sale is published
once, **ordered per sale and replayable**, for the Day 8 consumers (live dashboard, analytics,
audit).

## 2. What I did, step by step

1. **New module `infra/modules/events`:**
   - **Kinesis stream `surgegate-dev-sale-events`**: 1 provisioned shard, 24 h retention,
     KMS-encrypted. **Hourly ($0.0175/h)**, so it exists only between `make up` and
     `make down` (`enable_kinesis`, which the Makefile sets).
   - **EventBridge custom bus `surgegate-dev-sale-events`** with a **7-day archive** (replay
     beyond Kinesis' 24 h) and a rule sending every event to the log group
     `/aws/events/surgegate-dev-sale-events`. Persistent, pay per event.
   - **EventBridge Pipe stream → bus**: one write per event by the producers. The Pipe follows
     the stream switch, and its errors are logged at ERROR.
2. **Envelope (one Kinesis record):**
   - `{id, type, sale_event_id, at, data}`, partition key = sale event ID, so each sale's events
     are ordered on one shard;
   - `id` is unique, so consumers can drop duplicates;
   - on the bus: detail-type `sale-event`, and `detail` = the envelope plus `kinesis_sequence`.
3. **Producers, all best-effort** (a missing stream never fails the request; failures are logged):
   - `joined`: the sequencer, once per new place (duplicates publish nothing); one `PutRecords`
     per batch;
   - `admitted`: the admit Lambda, on the **first** admission only;
   - `seat_held`: the booking API after the hold **commits** (hold ID, seats, amount, expiry).
4. **IAM:** `kinesis:PutRecord(s)` on the stream ARN for the sequencer, the admit Lambda and the
   booking-api pod role. The ARN is stable even while the stream is down, so policies don't churn.
5. **Tests:** queue 53 (3 new, moto Kinesis) and booking API 98 (3 new): one event per new place
   and first admission; a failed hold publishes nothing; the stream being down breaks nothing.

### Commands I ran

```bash
aws pricing get-products --service-code AmazonKinesis …    # provisioned $0.0175/shard-h; on-demand $0.0517/stream-h
pip install "moto[…,kinesis]==5.2.5"; pytest -q            # queue 53, booking-api 98 (after starting Docker)
terraform -chdir=infra/envs/dev plan … -var=enable_kinesis=true -out=events.tfplan   # 10 add, 11 change
terraform -chdir=infra/envs/dev apply events.tfplan                                    # approved
python …   # join + admit through CloudFront; read the stream (get-records), the bus log group
# Pipe failing → logging (approved) → fixes (approved loop), see errors 3–5
aws pipes describe-pipe --name surgegate-dev-sale-events-to-bus
aws logs filter-log-events --log-group-name /aws/events/surgegate-dev-sale-events …
```

### Files created or changed

| File | What it does |
| --- | --- |
| `infra/modules/events/main.tf`, `variables.tf`, `outputs.tf`, `versions.tf` | Kinesis, bus, archive, log rule, Pipe (+ role, error log group) |
| `infra/envs/dev/main.tf`, `variables.tf`, `outputs.tf`, `booking_api.tf` | `module "events"`, `enable_kinesis`, outputs, pod IAM |
| `infra/modules/queue/main.tf`, `variables.tf` | `SALE_EVENTS_STREAM`, IAM for the sequencer and admit Lambdas |
| `services/queue/src/sg_queue/sale_events.py`, `sequencer.py`, `admit.py` | Producer + `joined` / `admitted` |
| `services/booking-api/app/sale_events.py`, `app/routes/buyer.py` | Producer + `seat_held` |
| `services/*/tests/test_sale_events.py`, `requirements-dev.txt` | Tests; moto Kinesis |
| `deploy/helm/booking-api/…` | `SALE_EVENTS_STREAM` |
| `Makefile` | `make up` / `make down` set `enable_kinesis` |

## 3. How it works

**Why two services?** Kinesis is an **ordered log**: everything about one sale goes to one shard
in order, and several consumers can each read it at their own pace, or replay it from the start
(24 h). EventBridge is a **router**: rules send events to targets (logs, alarms, later
notifications), and its archive keeps a longer history. The producers write once, to Kinesis, and
an EventBridge **Pipe** copies each record onto the bus, so both stay consistent without the
producers doing double work.

**Best-effort publishing.** Selling tickets matters more than reporting about it: if the stream
is down, the join, admission or hold still succeeds, and the failure is logged.

## 4. Errors I hit and how I fixed them

| # | Error (exact message) | Cause | Fix |
| --- | --- | --- | --- |
| 1 | 57 booking-API tests: `psycopg.errors.ConnectionTimeout: connection timeout expired` | Docker Desktop wasn't running (`failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine`) | Started Docker Desktop and the test containers: 98 passed |
| 2 | Shell command blocked by the safety check; `Terraform fmt … Failed` pre-commit hook | Quoting of Makefile text; formatting after staging | Edits via a script file; formatted, then committed |
| 3 | Pipe: `ExecutionFailed` 8/8, then (with error logging) `exceptionType: BadRequest`, `Target invocation failed partially.` | (part 1) the dynamic detail-type `$.data.type` resolved empty: a hand `PutEvents` with an empty DetailType gives `Parameter DetailType is not valid. Reason: DetailType is a required argument.` | Fixed detail-type `sale-event`; rules route on `detail.type`. **Not enough: still BadRequest** |
| 4 | (TRACE log) `TargetTransformationSucceeded … [{id:trace-aaec98d9,type:joined,…}]` → `TargetInvocationPartiallyFailed` | (part 2, the real cause) a bare `"<$.data>"` template produced **unquoted, array-wrapped text, not a JSON object**, so EventBridge rejected the `Detail` | A JSON object template, `{"id": <$.data.id>, …, "kinesis_sequence": <$.sequenceNumber>}` → **delivered** |
| 5 | (process) I concluded too early that the detail-type was the whole cause | Diagnosed from one test, not from the rejected payload | Asked to switch on TRACE logging; found the real cause from the payload; logging back to ERROR |

## 5. How I verified it works

| Check | Result |
| --- | --- |
| Tests | queue 53, booking API 98 |
| Stream | Real join + admit through CloudFront → Kinesis records `joined`, `admitted`, partition key = sale ID |
| Bus | After the fix: test record on the bus with `detail-type sale-event` and the full envelope + `kinesis_sequence`. **Real flow: `joined` and `admitted` for sale 3f51c9cc on the bus, in sequence order**, with their data |
| Pipe | RUNNING; logging back to ERROR |
| `seat_held` | Unit and integration tests; **live after the PR merges** (booking API image) |

## 6. Cost impact

**New hourly: Kinesis, 1 shard, $0.0175/h** (about $0.21 per 12-hour session), only between
`make up` and `make down`. Pay per event: Pipe about $0.40 per million, EventBridge $1 per
million, archive and logs cents.

## 7. Interview notes

- **Q:** Why Kinesis and EventBridge instead of Kafka?
  **A:** MSK was blocked on the Free plan and bills per cluster-hour. Kinesis gives the ordered,
  replayable log per sale (partition key = sale ID) for a cent or two per session hour.
  EventBridge adds routing, an archive and AWS integrations. A Pipe copies the stream to the bus,
  so producers write once.
- **Q:** What happens if the stream is down?
  **A:** Publishing is best-effort: the sale goes on, and the failure is logged. Joins and holds
  never depend on the event stream.
- **Q:** Tell me about a bug you diagnosed in this task.
  **A:** The Pipe rejected every event with a vague BadRequest. My first fix (the empty dynamic
  detail-type) was real but incomplete. Turning on TRACE logging showed the transformed payload:
  my template produced non-JSON text. A JSON object template fixed it. Lesson: look at the
  rejected payload before concluding.

## 8. Next task

Day 7 Task 2 (plan: Day 7 Task 1) — Step Functions hold timer: wait 10 minutes, release only if
still held by the same hold.
