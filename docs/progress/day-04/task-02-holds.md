# Week 1 · Day 4 · Task 02 — Hold endpoint: single conditional `UPDATE`, per-buyer limit in the same transaction

- **Date:** 2026-11-21 (evening of Day 3, ahead of schedule)
- **Phase / milestone:** Phase 2 (Booking core) → M2
- **Status:** Done
- **Commit / PR:** [#22](https://github.com/sheshagiri-62/surgegate/pull/22)

## 1. What the task was

Plan text: *"Hold endpoint: single conditional `UPDATE`, per-buyer limit in the same transaction."*
This is the heart of "never sell a seat twice". The blueprint's rule: a hold is one atomic
statement that only changes seats that are still available. If fewer rows come back than were
asked for, the transaction rolls back.

## 2. What I did, step by step

1. **`POST /book/{event}/holds`** with `{"seat_ids": [...]}`, buyer role (`app/holds.py`,
   `app/routes/buyer.py`).
2. **One transaction, in this order:**
   1. `SET LOCAL lock_timeout = '2s'`: wait at most 2 s behind another transaction, instead of
      piling up requests.
   2. `pg_advisory_xact_lock(hash(event, buyer))`: the **same buyer's** parallel requests run one
      after another. Without it, two requests could both see "0 held" and both pass the limit.
   3. **Per-buyer limit:** `SUM(seat_count)` of this buyer's holds for this event that are still
      active (`expires_at > now()`) or paid, plus this request, must be ≤ `per_buyer_limit`.
   4. `INSERT` the hold (expires in 10 minutes).
   5. **The conditional `UPDATE`:**
      `UPDATE seats SET status='held', hold_id=…, held_until=… WHERE id IN (SELECT id … AND
      status='available' ORDER BY id FOR UPDATE) AND status='available' RETURNING id, label,
      price_paise`.
   6. **Fewer rows than requested → ROLLBACK** →
      `409 {"detail": "someone just took that seat", "unavailable": [...]}`. Nothing is half-held.
   7. `COMMIT`, then invalidate the seat-map cache.
3. **Checks before the transaction:**
   - the event exists (404);
   - the sale is open (`sale_starts_at ≤ now < starts_at`, otherwise 409);
   - 1 to `per_buyer_limit` seats, none repeated (422).
4. **Errors:** a lock timeout (55P03) or deadlock (40P01) becomes
   `409 seats are busy, please try again` (nothing was held). Any other database error still
   raises, so an outage isn't hidden as "busy".

### Commands I ran

```bash
git checkout -b feat/holds origin/main
DATABASE_URL=… REDIS_URL=… python -m pytest -q        # 1st run: 10 failed (error 1); then 71 passed
gh pr create … ; gh pr merge 22 --squash              # approved; CI green
gh run watch <build-deploy>                           # image a5f2823f1c61
bash pf.sh && python devcheck …                       # real Cognito tokens against RDS
```

### Files created or changed

| File | What it does |
| --- | --- |
| `services/booking-api/app/holds.py` | The hold transaction (the only code that decides who gets a seat) |
| `services/booking-api/app/routes/buyer.py` | `POST /book/{event}/holds` |
| `services/booking-api/app/schemas.py` | `HoldCreate` (1–10 unique seat IDs), `HoldOut` |
| `services/booking-api/tests/test_holds.py` | 11 tests |

## 3. How it works

**Why one `UPDATE` is enough.** When 20 buyers click the same seat at once, PostgreSQL lets the
first `UPDATE` lock that row. The other 19 wait. When the first commits, PostgreSQL re-checks
`status = 'available'` for each waiting statement (in READ COMMITTED mode). It is now false, so they
change nothing and return 0 rows. The app sees "asked for 1, got 0", rolls back and answers 409.
There's no read-then-write gap where two buyers could both think a seat is free.

**Why lock in `id` order.** If buyer X wants seats {1, 2} and buyer Y wants {2, 1}, X could lock 1
while Y locks 2, and then each waits for the other: a deadlock. The sub-select
`ORDER BY id FOR UPDATE` makes everyone lock seats in the same order, so that can't happen. The
concurrency test (Task 3) proves it with 200 overlapping requests.

**Why an advisory lock for the limit.** The seat `UPDATE` protects *seats*; it doesn't stop one
buyer from sending 20 requests for 20 *different* seats at once, each of which would see "you hold
0". The advisory lock is a lock on the idea "this buyer, this event". It is held until the
transaction ends, so those 20 requests are checked one at a time.

**Second safety net.** `order_items.seat_id` is UNIQUE (Task 2 of Day 3), so even a future bug in
checkout couldn't sell one seat in two orders.

## 4. Errors I hit and how I fixed them

| # | Error (exact message) | Cause | Fix |
| --- | --- | --- | --- |
| 1 | 10 tests failed: `assert 422 == 200` on `upload(...)` | My test CSV gave the `gold` zone ten different prices (1001–1010), which the seat-map rules correctly reject ("one price per zone") | One price for the zone in the test data. The validator was right |
| 2 | My first fix (a Python `str.replace` over the test file) changed nothing | ruff had already reformatted the line, so the pattern no longer matched | Used the editor tool with the exact current text |

## 5. How I verified it works

| Check | Result |
| --- | --- |
| Tests (Postgres 18 + Redis) | 11 new, 71 total: hold + amount + 10-minute expiry; seat map shows `held` at once; taken seat → 409 with the seat ID and the *other* seat still available (all or nothing); limit across holds; expired holds don't count; over-limit request 422; empty or duplicate 422; another event's seat 409; sale not started or event started 409; unknown event 404; organiser 403; anonymous 401 |
| CI (#22) | green |
| Deployed (`a5f2823f1c61`, RDS, real Cognito buyer) | Hold 2 → `201`, A-1-1 and A-1-2, `300000` paise, expires in 10 min; seat map `miss` → `['held','held','available']`; same seat again → `409 someone just took that seat` + ID; 2 held + 3 more → `409 per-buyer limit is 4; you already hold 2`; organiser → `403 buyer role required` |
| Real RDS, from a pod (Task 3 run) | All 11 hold tests passed on db.t4g.micro |

## 6. Cost impact

None (code only).

## 7. Interview notes

- **Q:** Walk me through what happens when 20 people click the same seat.
  **A:** All 20 send the same conditional `UPDATE`. PostgreSQL row-locks the seat for the first;
  the rest wait. The first commits, and each waiting statement re-checks
  `status='available'`, which is now false, so they update 0 rows, roll back and get 409. No
  application lock or Redis is involved in the decision.
- **Q:** Why not check availability with a `SELECT` first?
  **A:** Between the `SELECT` and the write, someone else can take the seat (a race). A single
  conditional `UPDATE` makes the check and the change one atomic step.
- **Q:** How do you enforce "max 4 tickets per buyer" under concurrency?
  **A:** Within the same transaction: a transaction-scoped advisory lock per (event, buyer)
  serialises that buyer's requests, then their active and paid seats are counted. Tested: 20
  parallel requests from one buyer with limit 4 → exactly 4 succeed.

## 8. Next task

Day 4 Task 3 — Concurrency test: 200 parallel requests for the same 10 seats; exactly 10 holds succeed.
