# Week 2 · Day 8 · Task 03a — Consumers (1 of 3): live-dashboard over WebSocket

- **Date:** 2026-11-24
- **Phase / milestone:** Phase 4 → M4 ("the organiser watches it all update live")
- **Status:** Done, verified live. **Target changed (your decision): updates within 5 s
  (p95).** Measured 2.5–3.6 s from the click; the main cause is Lambda's Kinesis polling
  (about once per second; iterator age 1.3 s on average). Enhanced fan-out stays off;
  re-measure in the demo environment.
- **Commit / PR:** [#53](https://github.com/sheshagiri-62/surgegate/pull/53) (squash `e7f5b73`)

## 1. What the task was

Plan, Day 8 Task 3 (first consumer): *"Consumers: live-dashboard (WebSocket push), …"*.
Organisers see waiting, admitted, sold, revenue and admission rate change live during the sale
(blueprint feature 15).

## 2. What I did

1. **`services/event-consumers` / `live_dashboard.py`:** a Lambda consumer of the Kinesis stream.
   - Each record is **one DynamoDB transaction**: a dedupe marker `DEDUP#<message id>`
     (`attribute_not_exists`, 24 h TTL) plus `ADD` on the sale's counters.
   - On an error it reports the failing record's sequence number, so Lambda checkpoints before
     it and retries from there.
   - After each batch it pushes the numbers to subscribed connections.
2. **`ws.py`:**
   - a `$connect` REQUEST authorizer (verifies the 60-second live token, stdlib HMAC only);
   - `$connect` / `$disconnect` keep `SUBS#<event>` and `CONN#<id>` items (TTL 2 h);
   - a `snapshot` route sends the current numbers on demand.
3. **Booking API:** `POST /org/events/{id}/live-token`.
   - Own events only; another tenant's event is a 404, and the cross-tenant guard test covers it.
   - It returns `{token, ws_url, expires_in: 60}`.
   - A shared test vector keeps the issuer and the authorizer identical.
4. **Infra (`events` module):**
   - WebSocket API `surgegate-dev-live`, stage `live`;
   - 3 Lambdas;
   - a Kinesis mapping (LATEST, in order, bisect, 3 retries / 1 h, failed batches to SQS
     `consumers-failed` + alarm);
   - DynamoDB `sale-stats`;
   - the live-key secret.

   Plans shown, then applied: bootstrap 0/1/0, dev 28 add / 1 change.
5. **Day 9/10 note** added to the checklist: Kinesis write throughput at 50k users.

**Layout note:** the plan's layout put the WebSocket API in the `queue` module. I kept it with
its only user, the live-dashboard consumer, in the `events` module, so the push endpoint, the
connections table and the consumer change together.

## 3. How it works

**Simply:** every sale event (someone joined, was admitted, held seats, paid…) is a message on
the stream. The dashboard worker reads each one, adds it to the sale's running totals, and
immediately sends the new totals to every organiser who has that sale open. Each message has a
unique ID, and the worker records the IDs it has already counted, so seeing a message twice
never counts it twice.

```
producers ─► Kinesis sale-events ─(poll ~1 s)─► events-live-dashboard (in order per shard)
                                                  │ per record: TransactWrite [DEDUP#id (new only) + ADD counters]
                                                  ▼
                                         DynamoDB sale-stats  SALE#<event>/STATS
                                                  │ after the batch: Query SUBS#<event>
                                                  ▼
organiser ── POST /org/events/{id}/live-token (Cognito, own tenant) ─► 60 s token
organiser ── wss://…/live?token=… ─► authorizer (HMAC) ─► $connect: SUBS#<event>/<conn>
          ◄─────────────── PostToConnection {waiting, admitted, held, sold, revenue, rate, …}
```

- **Why a token in the URL:** browsers can't send an `Authorization` header when opening a
  WebSocket. The token lasts 60 seconds, is signed, and opens one event only. The tenant check
  happens when the booking API issues it.
- **Why "waiting" is joined minus admitted:** the stream carries joins and admissions, not
  leavers. Good enough for a live view; exact queue length stays the waiting room's job.

## 4. Errors I hit and how I fixed them

| # | Error (exact message) | Cause | Fix |
| --- | --- | --- | --- |
| 1 | `sed: -e expression #1, char 139: unknown option to 's'` (the first commit went out without the WebSocket URL and the checklist note) | The `#` in the replacement text clashed with sed's `#` delimiter | Second commit done with Python |
| 2 | `X Pull request …#52 is not mergeable: the base branch policy prohibits the merge.` | The required checks were re-running after I resolved #52's README conflict | `gh pr merge 52 --squash --auto` (merged after green; no admin override) |
| 3 | `ModuleNotFoundError: No module named 'websockets'` | No WebSocket client on the laptop | Installed `websockets==15.0.1` into the local dev virtualenv (not the repo) |
| 4 | (finding, not an error) **join → dashboard 26.2 s** | The waiting room's **sequencer** picked the join up 22 s later, on a cold start after the SQS queue had been idle (join Lambda 18:09:33, sequencer 18:09:55, `joined` published 18:09:56). The dashboard part was ~1 s | Not a dashboard issue. Noted for the load test: pre-warm or provision the sequencer before a sale |

## 5. How I verified it works

- **Tests:**
  - event-consumers: **9 passed**, covering:
    - a whole sale adds up (including a late payment and a refund);
    - duplicates and replays count once;
    - a failure reports the failing record and the retry counts correctly;
    - gone connections are removed, and only that sale's subscribers get pushes;
    - disconnect and snapshot work;
    - the token's expiry and forgery checks, and the authorizer's allow/deny;
    - the shared vector.
  - booking API: **141** (cross-tenant guard includes the new route).
  - CI: 12 checks green.
- **Live, through CloudFront** (event `24052880…`, organiser `organiser_a`, one test buyer, the
  real waiting room):

  | Step | Result | Click → dashboard |
  | --- | --- | --- |
  | live token | 200, `expires_in` 60; WebSocket connected; snapshot all zeros, status `open`, rate 250 | — |
  | join | 202 → `waiting` 1 | 26.2 s (sequencer cold start; see Errors #4) |
  | admit (real queue) | 200 + booking pass → `admitted` 1, `waiting` 0 | 3.6 s |
  | hold 2 seats | 201 → `held_seats` 2 | 2.5 s |
  | pay (mock) | 303 → `sold_seats` 2, revenue ₹3,000, `held_seats` 0 | 2.5 s |
  | ticket issued | → `tickets` 2 | 3.6 s after paying |

- **Where the time goes:**
  - `IteratorAge` (time a record waits in the stream before the consumer gets it): **average
    1.3 s, max 2.0 s**. That's Lambda's standard Kinesis polling, about once per second.
  - Warm consumer run: **~80 ms**.
  - The rest is the HTTP request itself through CloudFront plus the push.
  - Getting under 2 s reliably would need **enhanced fan-out** (push from Kinesis, about 70 ms;
    $0.015/h per consumer-shard), which you decided against. I recommend re-measuring in the
    demo environment and deciding there.
- **Duplicates:** all 5 of the sale's records were put on the stream **again** (same message
  IDs; what a producer retry or a replay delivers). **Counters unchanged: True.** The same
  duplicates also reached the bus through the Pipe; the ticket worker logged
  `skipped: email already sent` for the duplicate `order_paid`, so no second email.
- **Correction to the plan:** an EventBridge **archive** replay goes to the bus (it feeds the
  ticket rule), **not** to the Kinesis consumers. For the dashboard, the matching test is
  re-putting the records on the stream, which is what I did.

## 6. Cost impact

Nothing hourly.

| Item | Cost |
|---|---|
| Live-key secret | $0.40/month |
| Failure alarm | $0.10/month |
| DynamoDB on-demand, Lambda, WebSocket messages and connection minutes | Cents |

The Kinesis mapping follows `make up`/`make down`. Shard readers are now 2 (Pipe +
live-dashboard), within the 5 reads/s limit.

## 7. Interview notes

- **Q:** How do you avoid double counting when Kinesis delivers a record twice?
  **A:** Each envelope has a unique message ID. The counter update and a "seen this ID" marker
  are written in one DynamoDB transaction, and the marker is conditional. A second delivery
  fails the condition, so the whole transaction is cancelled and nothing is added. Verified live
  by re-putting a sale's records: the counters didn't move.
- **Q:** How does a browser authenticate a WebSocket?
  **A:** It can't send headers, so the organiser first gets a 60-second signed token from the
  booking API, where the usual Cognito and tenant checks run. The token goes in the connect URL.
  A Lambda authorizer verifies it and tells API Gateway which sale this connection may watch.
- **Q:** Why is the dashboard 2–3 s behind, and how would you make it faster?
  **A:** Lambda polls a Kinesis shard about once a second (iterator age 1.3 s on average here).
  Enhanced fan-out pushes records to the consumer in about 70 ms at a per-hour cost. For a live
  dashboard, 2–3 s is usually fine; I'd turn it on only if the organisers need it.

## 8. Next

Task 3b, **analytics** (lean): batches to S3 as gzip JSON lines with deterministic keys, a Glue
table with partition projection, an Athena workgroup with a scan limit, and 2 saved queries.
Then 3c, audit.
