# Week 1 · Day 4 · Task 03 — Concurrency test: 200 parallel requests for the same 10 seats; exactly 10 holds succeed

- **Date:** 2026-11-21 (evening of Day 3, ahead of schedule)
- **Phase / milestone:** Phase 2 (Booking core) → M2
- **Status:** Done (passes in CI on Postgres 18 **and** on the real dev RDS instance)
- **Commit / PR:** [#23](https://github.com/sheshagiri-62/surgegate/pull/23)

## 1. What the task was

Plan text: *"Concurrency test: 200 parallel requests for the same 10 seats; assert exactly 10 holds
succeed."* This is the M2 proof of "zero double bookings", and the plan's cut list says it must
never be cut.

## 2. What I did, step by step

1. **A real server, not a mock** (`tests/test_concurrency.py`):
   - the real app runs in uvicorn in a background thread, on a free port;
   - a 60-connection database pool;
   - real JWT checks, signed with a local test key.
2. **Real parallelism:**
   - 200 client threads share one HTTP client with 200 connections;
   - they all wait at a `threading.Barrier` and fire together.
3. **Check the database, not just HTTP codes:** seat statuses, how many different holds own the
   seats, and how many hold rows exist.
4. **Three scenarios:**

   | Scenario | Assertion |
   | --- | --- |
   | 200 different buyers; buyer *i* wants seat *i* mod 10 (20 per seat) | exactly `{201: 10, 409: 190}`; every seat won exactly once; all 10 seats `held` by 10 different holds; only 10 hold rows (losers rolled back); every loser got "someone just took that seat" |
   | 200 buyers, each wanting 2 **overlapping** seats in random order | only 201/409 (no 500s, so **no deadlocks**); no seat in two successful holds; each successful hold owns both seats (all or nothing) |
   | 1 buyer, 20 parallel single-seat requests, limit 4 | exactly `{201: 4, 409: 16}` |

5. **Ran it on the real dev RDS instance** too, from a temporary pod in the cluster, against a
   separate database `surgegate_ci` (dropped afterwards). The app's data was never touched.

### Commands I ran

```bash
git checkout -b test/concurrency feat/holds
python -m pytest -q tests/test_concurrency.py --durations=5     # 80 s (error 2) → 28 s after the fix
gh pr create … ; gh pr merge 23 --squash                         # approved; CI green
# real RDS run
kubectl create namespace verify && kubectl -n verify create configmap rds-ca --from-file=…
python … | kubectl apply -f -          # temporary Secret ci-db (ADMIN_URL, DATABASE_URL; never printed)
kubectl apply -f rds-tests.yaml         # python:3.12-slim, non-root
tar -cf - app alembic alembic.ini tests … | kubectl -n verify exec -i rds-tests -- tar -xf - -C /tmp/ba
kubectl -n verify exec rds-tests -- pip install --user -r requirements-dev.txt
kubectl -n verify exec rds-tests -- python -c "… create database surgegate_ci"
kubectl -n verify exec rds-tests -- python -m pytest -q tests/test_migrations.py tests/test_holds.py tests/test_concurrency.py tests/test_cross_tenant.py tests/test_organiser.py
kubectl -n verify exec rds-tests -- python -c "… drop database surgegate_ci with (force)"
kubectl delete namespace verify
```

### Files created or changed

| File | What it does |
| --- | --- |
| `services/booking-api/tests/test_concurrency.py` | Real-server concurrency tests (3 scenarios) |

## 3. How it works

A test that calls the hold function 200 times in a loop proves nothing about concurrency, because
the calls never overlap. Here, 200 threads send **HTTP requests at the same instant** to a real
server. The server runs each request in its own worker thread with its own database connection, so
PostgreSQL really has many transactions fighting over the same rows at once. That's exactly the
flash-sale situation. The test then reads the database to prove the final state is consistent:
10 seats, 10 holds, 1 hold per seat.

The overlapping-pairs scenario is the hard case for deadlocks: requests lock two seats in opposite
orders. It passes because the hold `UPDATE` always locks seats in `id` order (Task 2).

## 4. Errors I hit and how I fixed them

| # | Error (exact message) | Cause | Fix |
| --- | --- | --- | --- |
| 1 | ruff `S311 Standard pseudo-random generators are not suitable for cryptographic purposes` | False positive: `random.Random(42)` only shuffles test data | `# noqa: S311` with the reason |
| 2 | The tests passed but took **80 s** (about 35 s per 200-request batch) | Each of the 200 threads built its own `httpx.Client`, each creating an SSL context, while the clients and the server share one Python process (GIL) | One shared, thread-safe client with a 200-connection pool: 28 s locally, 14 s for the whole suite in CI |
| 3 | `ls: cannot access 'C:/Users/shesh/AppData/Local/Temp/ba/tests'` | Git Bash rewrote the `/tmp/ba` argument of `kubectl exec … ls` into a Windows path | Ran the command inside `sh -c '…'`, which Git Bash doesn't rewrite |
| 4 | `fatal: Not possible to fast-forward, aborting.` | The main checkout was still on an old docs branch when I pulled | Checked out `main` and pulled; confirmed `a7ab14c` (#24) before copying the code |

## 5. How I verified it works

| Where | Result |
| --- | --- |
| Local (Postgres 18 container) | 3 passed |
| CI (`postgres:18` service) | whole suite **80 passed in 13.98 s** |
| **Real dev RDS** (db.t4g.micro, PostgreSQL 18.3, TLS verify-full), from a pod | **38 passed in 11.01 s**: `test_200_parallel_requests_for_the_same_10_seats_exactly_10_succeed` 3.74 s; overlapping-holds test 3.04 s; plus holds, cross-tenant, organiser and migration tests |
| Clean-up | `surgegate_ci` dropped (remaining: `postgres, rdsadmin, surgegate`); namespace `verify` and its Secret deleted |

## 6. Cost impact

None. The temporary pod ran on the existing nodes, and the test database lived on the existing
instance.

## 7. Interview notes

- **Q:** How did you prove there are no double bookings?
  **A:** With a real HTTP server and 200 threads released by a barrier, so the requests really
  overlap in PostgreSQL. For 10 seats with 20 contenders each, exactly 10 requests succeed and the
  database shows 10 seats held by 10 different holds. It runs in CI on every PR and was also run
  against the real RDS instance.
- **Q:** What about deadlocks?
  **A:** A second scenario has 200 requests for overlapping seat pairs in random order. Seats are
  locked in `id` order, so there are no deadlocks: only 201/409, never 500. If one ever happened,
  it would map to a 409 retry, and nothing would be held.
- **Q:** Does a test on a laptop prove anything about production?
  **A:** The logic lives in PostgreSQL's row locking, which behaves the same everywhere. I still ran
  the same tests against the dev RDS instance from inside the cluster. Day 11's k6 load test then
  measures it at sale scale.

## 8. Next task

Day 4 Task 4 — Cross-tenant test: organiser A can never read or change organiser B's events.
