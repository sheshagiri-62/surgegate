# Week 1 · Day 6 · Task 01 — `valve` Lambda on EventBridge Scheduler raising "serving N" by the admission rate; pause and resume

- **Date:** 2026-11-22 (early hours; same session as Day 3)
- **Phase / milestone:** Phase 3 (Waiting room) → M3 ("they are admitted at the set rate")
- **Status:** Done
- **Commit / PR:** [#32](https://github.com/sheshagiri-62/surgegate/pull/32)

## 1. What the task was

Plan text: *"`valve` Lambda on EventBridge Scheduler raising 'serving N' by the admission rate;
pause and resume."* Blueprint step 6: every minute a scheduled Lambda raises N by the admission
rate set by the organiser, and pausing sets the rate to zero. This is what turns a crowd of any
size into a fixed, safe load on the booking API.

## 2. What I did, step by step

1. **`sg_queue/valve.py`**, run every minute by a second EventBridge Scheduler schedule:
   - for each open queue in the `active-queues` index:
     `serving_up_to = min(serving_up_to + admission_rate, next_position)`, so "now serving"
     never runs ahead of the people in line;
   - **exactly once per minute**: the update is conditional on `last_tick < this minute`
     **and** on the old `serving_up_to`, so a retry or a second invocation admits nobody extra;
   - paused, pre-queue and closed queues are left alone, and a pause that lands between the
     valve's read and its write wins.
2. **Organiser controls in the booking API** (`app/queue_control.py`, `app/routes/organiser.py`),
   tenant-scoped like every `/org` route (404 for another tenant's event):
   - `PUT /org/events/{id}/queue {admission_rate}` opens the waiting room. It's `pre-queue` before
     the event's `sale_starts_at` (from PostgreSQL), so the starter shuffles and opens it, or
     `open` if the sale has started. A second open → 409.
   - `PATCH /org/events/{id}/queue {action: pause|resume, admission_rate?}`: only open → paused
     and paused → open (otherwise 409); the rate can change at any time.
   - `GET /org/events/{id}/queue`: status, rate, in line, admitted, waiting.
   - This replaces the `tools/open_queue.py` dev tool for real use.
3. **IAM:**
   - valve role: `Query` on the index plus `UpdateItem`;
   - the Scheduler role may invoke the starter and valve only;
   - **booking-api pod role:** `GetItem/PutItem/UpdateItem` on the queue table only, through the
     existing DynamoDB VPC endpoint;
   - chart `QUEUE_TABLE`.
4. **Refactor:** the schedules are a map (`starter`, `valve`). A `moved` block kept the live
   starter schedule.
5. **Cross-tenant guard:** it failed on the three new routes until they had attack recipes, which
   is the design working. Recipes can now `prepare` (the owner opens the queue first), and the
   before/after snapshot also compares the **DynamoDB queue state**.

### Commands I ran

```bash
git checkout -b feat/valve origin/main
pytest -q (queue)          # 43 passed (7 valve)
pip install "moto[dynamodb]==5.2.5" (booking-api)
pytest -q (booking-api)    # cross-tenant failed for the 3 new routes (expected), then error 2, then 91 passed
terraform -chdir=infra/envs/dev plan … -out=valve.tfplan   # 5 add, 12 change, 0 destroy, schedule "has moved"
terraform -chdir=infra/envs/dev apply valve.tfplan          # approved: 5 added, 7 changed
aws scheduler list-schedules                                # starter, valve ENABLED
curl …/queue/<event>/serving (watch)                        # 0 → 65; 100 → 200 → 300
gh pr merge 32 --squash                                     # approved; pipeline → 17f59300963e
bash pf.sh && python …                                      # open, 20 joins, pause, tick, resume, tick; B attempts
```

### Files created or changed

| File | What it does |
| --- | --- |
| `services/queue/src/sg_queue/valve.py`, `tests/test_valve.py` | The valve and 7 tests |
| `services/booking-api/app/queue_control.py` | Open / pause / resume / rate on the queue's META item |
| `services/booking-api/app/routes/organiser.py`, `app/schemas.py` | `PUT/PATCH/GET /org/events/{id}/queue` |
| `services/booking-api/tests/test_queue_control.py`, `conftest.py`, `test_cross_tenant.py` | 6 tests; moto queue table; recipes with `prepare`, DynamoDB in the snapshot |
| `services/booking-api/requirements-dev.txt` | `moto[dynamodb]` |
| `infra/modules/queue/main.tf` | valve Lambda + role; schedules map + `moved` |
| `infra/envs/dev/booking_api.tf` | Pod role: queue table |
| `deploy/helm/booking-api/…` | `QUEUE_TABLE` |

## 3. How it works

Think of the waiting room as a door with a counter above it: "now serving up to N". Every minute
the valve adds the admission rate to N (say 125), so the next 125 people in line may enter. The
crowd outside can be 1,000 or 1,000,000; the door still lets in only 125 a minute, which is the
load the booking API and the database were tested for.

Pausing simply stops the valve from moving N: people can keep joining, and nobody new gets in.
The valve's update is a conditional write ("only if this minute isn't done yet, and N is still
what I read"), so duplicate or retried runs can't let extra people through.

## 4. Errors I hit and how I fixed them

| # | Error (exact message) | Cause | Fix |
| --- | --- | --- | --- |
| 1 | `AssertionError: add a cross-tenant recipe for: [('GET', '/org/events/{event_id}/queue'), ('PATCH', …), ('PUT', …)]` | **Expected:** the guard from Day 4 Task 4 found the new routes | Added recipes, a `prepare` step, and DynamoDB state in the snapshot |
| 2 | `AssertionError: recipe for PATCH /org/events/{event_id}/queue is wrong: {"detail":"can only pause a queue that is open"}` | The test event's sale is tomorrow, so its queue is `pre-queue`, and pausing is correctly refused | Recipe changed to a rate change (valid in any state). The isolation part had already passed |
| 3 | The scripted edit of `test_cross_tenant.py` failed: `AssertionError: ('tests/test_cross_tenant.py', '# How to call each organiser route…\nX,1,1,gold,1\n…')` | The `\n` escapes in the CSV bytes literal were changed on their way through the shell | Used the editor tool |

## 5. How I verified it works

| Check | Result |
| --- | --- |
| Tests | queue 43 passed (7 valve): +rate each minute (125/250/375); capped at people in line; same-minute retry admits nobody; stale read can't double-admit; paused and pre-queue don't move; pause between read and write wins; all open queues advance. Booking API 91 passed: open pre-queue/open, open twice 409, pause/resume/rate, can't pause a pre-queue, validation and roles, **cross-tenant for PUT/PATCH/GET queue** |
| Schedules | `surgegate-dev-queue-starter` and `surgegate-dev-queue-valve` ENABLED |
| Valve, live | 65-person queue: one tick **0 → 65** (capped). 300-person queue at 100/min: **100 (19:17:56), 200 (19:18:48), 300 (19:19:47)**, then stopped |
| Organiser controls, deployed (`17f59300963e`, real tokens) | A opens → `201 open rate 5`; 20 joins → `in_line 20, admitted 0`; A pauses → `paused`; **tick while paused → admitted 0**; A resumes → `open`; **next tick → admitted 5, waiting 15** |
| Cross-tenant, deployed | B `PUT` A's queue → `404 event not found`; B `PATCH resume` → `404` |

## 6. Cost impact

No hourly cost. The second schedule adds 43,200 invocations a month, within the free tiers.

## 7. Interview notes

- **Q:** What sets the load on your database during a sale?
  **A:** The admission rate, not the crowd. A valve raises "now serving" by a fixed number each
  minute, so the booking API sees, say, 125 new buyers a minute however many are waiting. That
  rate can be load-tested and guaranteed.
- **Q:** How do you stop the valve admitting twice if it runs twice?
  **A:** It's a conditional DynamoDB update: only if this minute hasn't been applied and N is still
  the value read. A duplicate gets `ConditionalCheckFailed` and does nothing. Unit tests cover the
  retry, the stale read, and a pause arriving mid-update.
- **Q:** How does an organiser pause a sale, and who else could?
  **A:** `PATCH /org/events/{id}/queue {"action": "pause"}` on the booking API. It's tenant-scoped
  like every organiser route, and a cross-tenant test discovers these routes automatically and
  proves another tenant gets 404 and changes nothing, including the DynamoDB state.

## 8. Next task

Day 6 Task 2 — `admit` endpoint issuing a 15-minute booking pass. The booking API verifies the
pass itself; the CloudFront Function check on `/book/*` is **pending CloudFront verification**.
