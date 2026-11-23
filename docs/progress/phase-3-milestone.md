# Phase 3 — Waiting room → Milestone M3

- **Checked on:** 2026-11-22 (early hours, same session as Day 3; Days 5–6 brought forward)
- **"Done when"** (plan): *1,000 simulated buyers join, the pre-queue is shuffled, they are admitted
  at the set rate, and a request to `/book/*` without a valid pass is refused at the edge.*
- **Result: partly met.**
  - Shuffle: **met**.
  - Admission at the set rate: **met**.
  - 1,000 join: **977 / 1,000**, the rest throttled by the account's Lambda concurrency limit (10;
    increase requested).
  - `/book/*` refused without a pass: **met in the booking API, and at the edge since 23 Nov**
    (CloudFront approved).
- **Update 2026-11-23:** CloudFront edge checks done (below). The k6 re-run with 1,000 users is next
  (Lambda limit is now 1,000), and this file will be updated with its result.

## Evidence

| Condition | How it was checked | Result |
| --- | --- | --- |
| 1,000 simulated buyers join | k6 `tests/load/k6/queue.js`, 1,000 virtual users with real Cognito tokens, arriving over 60 s | **977 joined (97.7%)**. 23 failed after retries: Lambda `ConcurrentExecutions` peaked at the **account limit of 10**. **Re-run pending the quota increase** (`CASE_OPENED`) |
| The pre-queue is shuffled | `check_queue.py` on DynamoDB after the run; unit tests; a manual 62-person test | All 977 joined before the start; **the 10 earliest arrivals got positions 267, 307, 214, 41, 304, 425, 385, 218, 511, 334**; positions 1–977 unique without gaps |
| Admitted at the set rate | Rate 250/min. Valve logs; earlier live test at 100/min | serving went up by 250 per minute up to 977; **all 977 admitted**. 100/min test: 100 → 200 → 300 at 19:17/18/19. Pause: a tick while paused admitted 0 |
| `/book/*` without a valid pass is refused **in the booking API** | Deployed API, real tokens | no pass → `403 booking pass required`; tampered → forged; other event → refused; another user's pass → refused; valid → 200 |
| `/book/*` without a valid pass is refused **at the edge** (23 Nov) | `https://d1t9vww2xtyvsz.cloudfront.net/book/<event>/seats`, buyer-1 token | **no pass / garbage / forged / expired → `403`, `X-Cache: FunctionGeneratedResponse from cloudfront`**: answered by the CloudFront Function, never reaching the ALB. Valid pass with the **wrong user** → passes the edge, refused by the API (`403 pass belongs to someone else`, `X-Cache: Error from cloudfront`), which is defence in depth. **Valid pass, right user → `200`, 96 seats** |
| The shared counter is cached 5 s at the edge (23 Nov) | 8 requests to `/queue/<event>/serving`, about 2 s apart | `Miss`, `Hit (Age 1)`, `Hit (Age 3)`, `Miss`, `Hit (Age 2)`, `Hit (Age 4)`, `Miss`, `Hit (Age 1)`; `Cache-Control: public, max-age=5` |
| Everything through one origin (23 Nov) | Organiser API, join, position, admit, `/book` all via the CloudFront domain | default → ALB, `/queue/*` → API Gateway, `/book/*` → booking-pass function → ALB |

## How to demo it

Prerequisites: `make up`; Argo CD Synced/Healthy; `kubectl -n booking port-forward
svc/booking-api 18080:80`; `cd web/buyer && npm run dev`.

1. **Organiser opens a waiting room**, with the sale 2 minutes away, using organiser A's token:
   `POST /org/events` (sale in 2 min) → `PUT /org/events/{id}/seats` (CSV) →
   `PUT /org/events/{id}/queue {"admission_rate": 5}` → `pre-queue`.
2. **Buyer** opens `http://localhost:3000/queue/?id=<event>`, signs in (buyer-1, password from
   `surgegate/dev/test-users`) and sees the **countdown**.
3. At the start, the page shows **"You are number N"**, people ahead and the wait.
4. When the valve reaches N, the page **admits automatically and jumps to the seats**, with the
   pass sent on every `/book` call.
5. In another window, the same `/book/<event>/seats` call without a pass → **403** (show it with
   `curl`).
6. Organiser `PATCH /org/events/{id}/queue {"action": "pause"}`: the counter stops moving.
   Resume: it moves again.
7. Show the k6 summary (`k6 run … queue.js`) and `python tests/load/k6/check_queue.py <event>`
   (shuffle + admitted per minute).

## Screenshots to take

1. The waiting-room page counting down (pre-queue).
2. "You are number …" with people ahead and the estimated wait.
3. The seat page right after the automatic redirect.
4. `curl` of `/book/<event>/seats` without `X-Booking-Pass` → 403 with the queue link.
5. The k6 end-of-test summary (977 admitted, thresholds), plus the CloudWatch Lambda
   `ConcurrentExecutions` = 10 graph (the reason for the shortfall).
6. `check_queue.py` output: the shuffle positions of the 10 earliest arrivals and admitted per
   minute.
7. EventBridge Scheduler: `surgegate-dev-queue-starter` and `-valve` ENABLED.

## Still to do for a full M3

1. **Lambda limit is now 1,000** (since 23 Nov) → re-run k6 → expect 1,000/1,000 joins.
2. ~~CloudFront verification → edge refusal, 5 s cache~~ **Done 23 Nov.** The first deploy of the
   function failed at the edge with `SyntaxError: await in arguments not supported in 37`
   (`X-Cache: FunctionExecutionError`). Fixed, re-tested with `TestFunction` and live.
3. ~~Before the sale, poll the shared status instead of `/position`~~ **Done** (#37).
