# Week 1 · Day 4 · Task 01 — Seat map endpoint with Redis cache and invalidation on change

- **Date:** 2026-11-21 (done on the evening of Day 3, ahead of schedule)
- **Phase / milestone:** Phase 2 (Booking core) → M2
- **Status:** Done
- **Commit / PR:** [#21](https://github.com/sheshagiri-62/surgegate/pull/21)

## 1. What the task was

Plan text: *"Seat map endpoint with Redis cache and invalidation on change."* Blueprint: `GET
/book/{event}/seats` is served from Redis. The map shown to buyers may lag up to 2 seconds,
because only the hold `UPDATE` decides who gets a seat. In a sale thousands of buyers refresh the
map, and those reads must not all hit PostgreSQL.

## 2. What I did, step by step

1. **`GET /book/{event}/seats`** (any signed-in user for now; the booking pass comes on Days 5–6)
   returns the event and every seat with its status. An `X-Cache` header shows `hit`, `miss`,
   `stale` or `db`.
2. **`app/cache.py`**, cache-aside with three keys:
   - `seatmap:{event}` is the fresh copy, **TTL 2 s**;
   - `seatmap:{event}:stale` (60 s) is served while one request rebuilds;
   - `seatmap:{event}:lock` (`SET NX`, 2 s): only the request that wins the lock reads
     PostgreSQL after a miss, which prevents a **cache stampede**.
3. **Invalidation on change:** a committed seat-map upload deletes the fresh key; holds do the same
   (Task 2). The 2 s TTL limits the lag for changes we don't invalidate, such as the Day 7 timer.
4. **Failure handling:** 0.5 s timeouts. Any Redis error means the read goes to PostgreSQL (`db`),
   so Redis is never a single point of failure.
5. **Cluster connection:** `rediss://` (TLS, certificate verified) to the ElastiCache primary, with
   the AUTH token read from `surgegate/dev/data/redis-auth` through the pod's IAM role. That's one
   new IAM statement, applied with a saved plan (free).
6. **CI:** a `redis:7.4` service container in `ci.yml` and `build-deploy`.

### Commands I ran

```bash
docker run -d --name sg-redis -p 127.0.0.1:16379:6379 redis:7.4
pip install redis==8.1.0
DATABASE_URL=… REDIS_URL=redis://127.0.0.1:16379/0 python -m pytest -q        # 60 passed
terraform -chdir=infra/envs/dev plan … -out=redis-iam.tfplan && terraform apply redis-iam.tfplan   # 1 changed
helm lint deploy/helm/booking-api
gh pr create … ; gh pr merge 21 --squash          # approved; CI green; dev plan "No changes"
git merge origin/main   # conflict in 3 files (error 1)
bash pf.sh && python devcheck …                    # miss → hit → hit → (2.5 s) miss → upload → miss
```

### Files created or changed

| File | What it does |
| --- | --- |
| `services/booking-api/app/cache.py` | Redis client (URL or ElastiCache + Secrets Manager), cache-aside with lock and stale copy, invalidation |
| `services/booking-api/app/routes/buyer.py` | `GET /book/{event}/seats` |
| `services/booking-api/app/routes/organiser.py` | Invalidate after a seat-map upload |
| `infra/envs/dev/booking_api.tf` | Pod role may read the Redis AUTH secret |
| `deploy/helm/booking-api/…` | `REDIS_HOST`, `REDIS_AUTH_SECRET_ID` |
| `.github/workflows/ci.yml`, `build-deploy.yml` | Redis service container, `REDIS_URL` |
| `services/booking-api/tests/test_seatmap_cache.py` | 7 tests |

## 3. How it works

**Cache-aside.** The app asks Redis first. On a miss it reads PostgreSQL, stores the answer in Redis
and returns it. The next buyer within 2 seconds gets the copy from memory without touching the
database. One rebuild per event every 2 seconds is all PostgreSQL sees, however many buyers are
watching.

**Invalidation.** When we change seats (upload now, holds next), we delete the cached copy right
after the commit, so the next read rebuilds it and buyers see the change at once. The TTL is the
backstop for changes made by other processes.

**Stampede protection.** When a popular event's copy expires, a thousand requests might all miss at
the same moment. Only the request that wins the Redis lock rebuilds; the others get the slightly
older "stale" copy. This is safe because the map is only a display. **The hold `UPDATE` in
PostgreSQL is what decides who gets a seat**, so a stale map can never cause a double booking.

## 4. Errors I hit and how I fixed them

| # | Error (exact message) | Cause | Fix |
| --- | --- | --- | --- |
| 1 | `CONFLICT (content): Merge conflict in services/booking-api/tests/conftest.py` (also `app/main.py`, `app/routes/organiser.py`) | This branch was stacked on #20, which was squash-merged; both sides changed the same lines | Compared main's version with the branch's for each file: the branch = main + this task's additions. Kept the branch versions, re-ran all 60 tests, pushed (no force push) |
| 2 | Dev check printed `X-Cache=None` | Starlette sends header names in lower case (`x-cache`); my check script looked up `X-Cache` | Case-insensitive header lookup in the script. Then `miss/hit/hit` |

## 5. How I verified it works

| Check | Result |
| --- | --- |
| Tests | 7 new, 60 total: miss → hit with `0 < TTL ≤ 2`; upload invalidates; an out-of-band change is visible after the TTL; stale copy served while another request holds the lock; Redis down → `db` with full data; unknown event 404; anonymous 401 |
| CI (#21) | green; dev plan `No changes` |
| Deployed (`4c5c2c4bf67b`, real ElastiCache, TLS + AUTH, RDS) | `GET` #1 `miss` (96 seats), #2 `hit`, #3 `hit`; after 2.5 s `miss`, then `hit`; after re-upload `miss` (invalidated). No Redis warnings in the pod logs |

## 6. Cost impact

None. Redis already existed (Task 1); IAM is free.

## 7. Interview notes

- **Q:** The seat map can be 2 seconds stale. Can that cause a double booking?
  **A:** No. The map is only a display. The hold is one conditional `UPDATE … WHERE
  status='available'` in PostgreSQL, so a buyer clicking a seat that is really taken gets "someone
  just took that seat". The cache only reduces load.
- **Q:** What is a cache stampede and how did you prevent it?
  **A:** When a hot key expires, every request misses together and hits the database. A short Redis
  lock (`SET NX EX 2`) lets one request rebuild, while the others are served a stale copy kept
  longer.
- **Q:** What happens if Redis goes down mid-sale?
  **A:** Every Redis call has a 0.5 s timeout and falls back to PostgreSQL. The site gets a little
  slower but keeps working, and admission control (Phase 3) caps the load either way.

## 8. Next task

Day 4 Task 2 — Hold endpoint: the single conditional `UPDATE`, per-buyer limit in the same transaction.
