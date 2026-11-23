# Week 1 · Day 6 · Task 04 — k6 script: 1,000 virtual users join, wait and get admitted

- **Date:** 2026-11-22 (early hours; same session)
- **Phase / milestone:** Phase 3 (Waiting room) → M3
- **Status:** Script done and run (you approved: a 5-user smoke run, then 1,000). **Result:**
  977 of 1,000 joined; **all 977 were admitted** with a fair shuffle at the set rate. **23 joins
  failed** because the account's **Lambda concurrency limit is 10** (increase to 1,000 requested,
  `CASE_OPENED`). Re-run once the quota is raised.
- **Commit / PR:** see the Day 6 summary (`test/k6-queue`)

## 1. What the task was

Plan text: *"k6 script: 1,000 virtual users join, wait and get admitted."* You asked for the
expected cost before running. Estimate: **about $0.06**; worst case about $15 if Cognito's
10,000-MAU free tier doesn't apply to this account.

## 2. What I did, step by step

1. **`tests/load/k6/load_users.py`:** creates N Cognito buyer accounts (`load-NNNN@surgegate.test`,
   no email sent), signs them in through the dev test client, and writes the 60-minute tokens to
   `.load_tokens.json` (gitignored). Passwords are random per run and never written to disk.
   `delete` removes the accounts.
2. **`tests/load/k6/queue.js`:** each virtual user does what the buyer page does:
   1. arrive at a random moment within 60 s;
   2. **join**;
   3. **position** every 5 s until numbered;
   4. the **shared `/serving`** counter every 10 s;
   5. **admit**, getting a booking pass.
   - 429/503 responses back off and retry (up to 6 times) and are counted.
   - Thresholds: join success > 99.9% (the blueprint's SLO), admitted == 1,000, fewer than 1% of
     requests failed.
   - `/book` isn't called: without CloudFront the ALB can't be reached from k6 (**pending
     CloudFront verification**), and the booking path has its own concurrency test.
3. **`tests/load/k6/check_queue.py`:** reads the queue in DynamoDB afterwards: positions unique
   with no gaps, admitted count, where the earliest arrivals landed (the shuffle), and admissions
   per minute.
4. **Runs:**
   - **smoke:** 5 users, all thresholds passed;
   - **full:** 1,000 users. The event was opened as a **pre-queue** through the organiser API,
     with the sale about 90 s later and **250/min**.
5. Deleted the 1,000 accounts and the token file.

### Commands I ran

```bash
python load_users.py create 5
python mkqueue.py 60 250 "k6 smoke"           # organiser A: event + PUT /org/events/{id}/queue (pre-queue)
k6 run -e QUEUE_API=… -e EVENT_ID=… -e VUS=5 -e ARRIVAL_SECONDS=10 queue.js
python check_queue.py <smoke event>
python load_users.py create 1000              # 1 min 34 s
python mkqueue.py 90 250 "k6 1000 fans"
k6 run -e QUEUE_API=… -e EVENT_ID=… -e VUS=1000 -e ARRIVAL_SECONDS=60 -e MAX_WAIT_SECONDS=480 --summary-export=k6-summary.json queue.js
python check_queue.py <event>
aws cloudwatch get-metric-statistics --namespace AWS/Lambda --metric-name Throttles|Invocations|ConcurrentExecutions …
python load_users.py delete 1000 && rm .load_tokens.json
```

### Files created or changed

| File | What it does |
| --- | --- |
| `tests/load/k6/queue.js` | The k6 scenario |
| `tests/load/k6/load_users.py` | Create / sign in / delete load-test accounts |
| `tests/load/k6/check_queue.py` | Post-run checks in DynamoDB |
| `.gitignore` | `.load_tokens.json` |

## 3. How it works

k6 starts 1,000 "virtual users", each a small script acting like one fan's browser. They arrive
over a minute, before the sale starts, so they all land in the pre-queue. At the start the starter
shuffles them, and every minute the valve lets in 250. Each virtual user notices from the shared
counter that it's their turn and swaps their queue token for a booking pass. Afterwards we read
DynamoDB to check what really happened: unique positions, a random order, and the admission rate.

## 4. Errors I hit and how I fixed them

| # | Error (exact message) | Cause | Fix |
| --- | --- | --- | --- |
| 1 | `level=error msg="thresholds on metrics 'http_req_failed, queue_admitted, queue_join_ok' have been crossed"`: `http_req_failed rate=46.90%`, `queue_join_ok 97.70%`, `queue_admitted count=977`, `http_429 22659` | **The account's Lambda concurrency limit is 10.** CloudWatch: `ConcurrentExecutions` max **10.0**; throttles position 17,452, serving 4,305, join 898, admit 395, sequencer 55. API Gateway's stage limit wasn't involved (peak 137 rps against 1,000). 23 joins still failed after 6 retries | Not a code bug. The increase to 1,000 is requested (Service Quotas `c57e030e…`, case 179528198300645, `CASE_OPENED`). **Re-run after approval.** Also an improvement found (below) |
| 2 | (finding) the biggest load was **position polling during the pre-queue**: 12,722 invocations + 17,452 throttles | 1,000 users ask "do I have a number yet?" every 5 s, although nobody gets one until the start | Next change: before the start, the page (and k6) watches the shared `/serving` status, cacheable, and asks for its position only once the sale has started |

## 5. How I verified it works

**Smoke (5 users):** all thresholds passed; 5/5 admitted; 116 requests, 0 failed; arrival order →
positions [3, 2, 5, 1, 4]; numbered 1–5 without gaps.

**Full run (1,000 users, 6 min):**

| Measure | Result |
| --- | --- |
| Joins | **977 / 1,000 (97.7%)**; 23 failed after retries (Lambda throttling) |
| Admitted (pass issued) | **977 / 977 who joined**, every one, checked in DynamoDB (`admitted_at`) |
| Positions | 977 numbered, **1–977 unique without gaps** |
| Shuffle | all 977 joined before the start; **the 10 earliest arrivals got 267, 307, 214, 41, 304, 425, 385, 218, 511, 334** (random, not 1–10) |
| Admission rate | the valve raised serving by 250 per minute (final `serving = 977`). Passes issued per minute 210 / 290 / 250 / 227: buyers notice within their 10 s poll, so a tick's admissions can land in the next minute's bucket |
| Wait (arrival → pass) | avg 234 s, p95 310 s, max 330 s (sale started ~90 s in; 977 ÷ 250/min ≈ 4 ticks) |
| HTTP | 49,177 requests (137/s); latency avg 55 ms, p95 148 ms; **47% failed, nearly all 429 throttles** |
| Lambda | max concurrent executions **10** (the account limit) |
| Clean-up | 1,000 accounts deleted (`load users left: 0`), token file removed |

## 6. Cost impact

As estimated: about 49,000 API calls (about $0.06), Lambda within the free tier, DynamoDB about
$0.01, logs about $0.01. **Cognito: 1,005 MAU this month**, which is $0 within the 10,000-MAU
free tier (worst case $15 if it doesn't apply; check the November bill). Nothing hourly.

## 7. Interview notes

- **Q:** What did the load test show?
  **A:** The waiting room's logic held under 1,000 concurrent fans. Every joiner got a unique,
  gap-free, randomly shuffled position, and everyone was admitted at exactly the configured rate.
  What failed was capacity: the new account's Lambda concurrency limit of 10 caused 429s and 2.3%
  lost joins. That's an account quota, already requested to be raised to 1,000.
- **Q:** What would you change after this run?
  **A:** Stop polling `/position` before the sale starts, which was most of the load. Watch the
  shared, cacheable status instead and ask for a position once the shuffle has run. With CloudFront
  caching `/serving`, the remaining polling hardly reaches Lambda at all.
- **Q:** Why are the passes per minute not exactly 250?
  **A:** The valve raises "now serving" by exactly 250 a minute, but each browser only notices on
  its next 10-second poll, so some of a tick's admissions are counted in the following minute. The
  ceiling stays 250 a minute.

## 8. Next task

Day 7 (Phase 4, checkout). Before that, once the quota is raised: re-run this test (expect 1,000/1,000).
