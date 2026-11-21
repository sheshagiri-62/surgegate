# Day 6 summary — planned for Tue 24 Nov, done in the early hours of Sun 22 Nov 2026

Same session as Days 3–5 (it started on the evening of Sat 21 Nov). The CloudFront and Kinesis
pieces were left out, as you asked; **CloudFront-dependent checks are marked "pending CloudFront
verification"**. M3: see `../phase-3-milestone.md` (partly met).

## Finished

| Task | PR | Report |
| --- | --- | --- |
| 1. `valve` Lambda (EventBridge Scheduler, every minute) + organiser open / pause / resume / rate | [#32](https://github.com/sheshagiri-62/surgegate/pull/32) | [task-01-valve](task-01-valve.md) |
| 2. `admit` → 15-minute booking pass; **booking API verifies it**. CloudFront Function check: **pending CloudFront verification** | [#33](https://github.com/sheshagiri-62/surgegate/pull/33) | [task-02-admit-pass](task-02-admit-pass.md) |
| 3. Buyer waiting-room page (countdown, position, wait, automatic redirect) | [#34](https://github.com/sheshagiri-62/surgegate/pull/34) | [task-03-waiting-room-page](task-03-waiting-room-page.md) |
| 4. k6 script: 1,000 virtual users; run (977 joined, 977 admitted) | this PR | [task-04-k6](task-04-k6.md) |
| M3 check | — | [phase-3-milestone](../phase-3-milestone.md) |

## Not finished / open items

- **M3 is partly met:** 23 of 1,000 joins were throttled by the account's **Lambda concurrency
  limit of 10** (increase to 1,000: `CASE_OPENED`, case 179528198300645). Re-run k6 after approval.
- **Pending CloudFront verification:** the `/book/*` CloudFront Function + KeyValueStore (copy the
  pass key in once), the `/queue/*/serving` 5 s cache, the M1 checks.
- **Improvement found by k6:** stop polling `/position` before the sale starts (most of the load).
- **Day 3 Task 1 still pending:** the snapshot-restore check at the next `make up`.
- **Follow-up:** `hash_key` → `key_schema` on the queue table (provider deprecation).

## All errors of the day

| # | Task | Error (exact message) | Cause | Fix |
| --- | --- | --- | --- | --- |
| 1 | 1 | `AssertionError: add a cross-tenant recipe for: [('GET', '/org/events/{event_id}/queue'), …]` | Expected: the guard found the new routes | Recipes + `prepare` + DynamoDB in the snapshot |
| 2 | 1 | `recipe for PATCH … is wrong: {"detail":"can only pause a queue that is open"}` | The test queue was a pre-queue | Recipe changed to a rate change |
| 3 | 1 | Scripted edit `AssertionError` on the CSV bytes literal | `\n` escapes changed in transit | Editor tool |
| 4 | 2 | 3 tests: `KeyError: 'seats'` | The `open_event` helper read seats without a pass (rightly 403 now) | Reads as an admitted buyer |
| 5 | 2 | ruff `S105 Possible hardcoded password … "BOOKING_PASS_REQUIRED"` | False positive | `noqa` with the reason |
| 6 | 2 | Scripted edit stopped at `seat_ids = […]` (count 0) | Line wrapped differently by ruff | Editor tool |
| 7 | 3 | (caught before testing) the CORS preflight would have blocked `X-Booking-Pass` | Custom header not allowed | Added to `allow_headers` + test |
| 8 | 3 | `Error: listen EADDRINUSE: address already in use :::3000` | The earlier `next dev` Node process outlived its stopped wrapper | Used it (it serves current code); stopped at session end |
| 9 | 4 | `thresholds on metrics 'http_req_failed, queue_admitted, queue_join_ok' have been crossed` (47% failed, 977/1,000) | **Lambda account concurrency 10** (`ConcurrentExecutions` max 10; 23,105 throttles) | Quota increase requested; re-run after approval |

(Day 5 and the `make up` credentials fix: see `../day-05/SUMMARY.md`.)

## Cost (whole session, 21–22 Nov, estimate)

| Item | Estimate |
| --- | --- |
| Dev hourly layer (EKS, 2 nodes, NAT, ALB, RDS, Redis), about 13:25 → about 20:30 UTC ≈ 7 h × $0.33 | **≈ $2.30** |
| Waiting room (API Gateway, Lambda, SQS, DynamoDB, Scheduler, logs) incl. k6 | **≈ $0.10** |
| Cognito: about 1,010 MAU this month (1,000 deleted load users + test users) | $0 within the 10,000-MAU free tier (worst case about $15) |
| New persistent | 2 secrets (token key, pass key) $0.80/month |

Check Cost Explorer tomorrow for actuals (it lags about a day).

## Still running

Until `make down`: EKS + 2 nodes, NAT + EIP, ALB, RDS `surgegate-dev-pg`, Redis
`surgegate-dev-redis`. Pay-per-request only (no hourly cost, kept): API Gateway, the 6 queue
Lambdas, SQS, DynamoDB, 2 Scheduler schedules (every minute), Cognito. Local: the `next dev`
process, the port-forward, Docker `sg-pg` / `sg-redis`.

## Next session starts with

1. `make up` → **check the snapshot restore** (`ops_restore_check` row `day3-before-make-down`).
2. If the Lambda quota was approved: re-run k6 (1,000/1,000).
3. If CloudFront is verified: enable it, fill the KeyValueStore, run the pending CloudFront checks
   (M1; M3 edge refusal; serving cache).
4. Day 7 — Phase 4, checkout.
