# Week 1 · Day 3 · Task 04 — Organiser endpoints: create event, upload seat map (CSV), list events (tenant-scoped)

- **Date:** 2026-11-21
- **Phase / milestone:** Phase 2 (Booking core) → M2
- **Status:** Done
- **Commit / PR:** [#20](https://github.com/sheshagiri-62/surgegate/pull/20)

## 1. What the task was

Plan text: *"Organiser endpoints: create event, upload seat map (CSV), list events — tenant-scoped."*
Blueprint: `POST /org/events` and `PUT /org/events/{id}/seats`. Each organiser is a tenant and
sees only their own events. This is how a sale is set up before buyers arrive.

## 2. What I did, step by step

1. **`app/routes/organiser.py`** (organiser role, and the token must carry a tenant):
   - `POST /org/events` creates a draft event. The tenant row is created on first use.
   - `GET /org/events` lists this tenant's events, with seat counts and a per-zone summary.
   - `GET /org/events/{id}` returns one event.
   - `PUT /org/events/{id}/seats` replaces the seat map from a `text/csv` body.
2. **Tenant scoping:**
   - Every query filters `events.tenant_id = <tenant from the token>`.
   - An event of another tenant answers **404**, the same as an event that doesn't exist.
   - The request body may not contain unknown fields (`extra="forbid"`), so a `tenant_id` in the
     body is refused (422), never silently used.
3. **`app/seatmap_csv.py`**, the seat-map rules:
   - Header `section,row,number,zone,price_inr`.
   - At most 3 price zones, one price per zone; zone names are case-insensitive.
   - Each seat appears once (label `A-1-2`); price in whole paise (≤ 2 decimals); no negative
     prices or zero seat numbers.
   - At most 20,000 seats and 2 MB, UTF-8 (an Excel BOM is accepted).
   - Every error names the line, e.g. `line 3: seat A-1-1 appears twice`.
4. **Safe replace:**
   - The event row is locked (`SELECT … FOR UPDATE`) while the map is replaced.
   - The replace is **refused with 409 once any seat is held or sold**, so a sale in progress can't
     lose seats.
5. **`app/schemas.py`:** pydantic bodies. Timezone-aware datetimes are required; the sale must
   start before the event; `per_buyer_limit` is 1–10.
6. **Tests:** 28 new, 53 in total (CSV unit tests, integration tests through the real app with
   JWT checks, on Postgres).

### Commands I ran

```bash
git checkout -b feat/organiser-endpoints origin/main
ruff format . && ruff check --fix .
DATABASE_URL=postgresql+psycopg://surgegate:local-only@127.0.0.1:15432/surgegate_test python -m pytest -q   # 53 passed
gh pr create … ; gh pr merge 20 --squash          # approved; CI green
gh run watch <build-deploy>                        # image ea8a22b7acc5
bash pf.sh                                         # kubectl port-forward svc/booking-api 18080:80, wait for /healthz
python devcheck steps                              # real Cognito tokens for organiser A, organiser B, buyer
```

### Files created or changed

| File | What it does |
| --- | --- |
| `services/booking-api/app/routes/organiser.py` | The four organiser endpoints |
| `services/booking-api/app/seatmap_csv.py` | CSV parsing and validation |
| `services/booking-api/app/schemas.py` | Request/response models |
| `services/booking-api/app/main.py` | Registers the router |
| `services/booking-api/tests/helpers.py`, `conftest.py` | Signed test tokens; `api` fixture (real app + test DB) |
| `services/booking-api/tests/test_seatmap_csv.py`, `test_organiser.py` | 28 new tests |

## 3. How it works

**Multi-tenancy in one database.** All organisers share the same tables. What keeps them apart is
one rule applied everywhere: *the tenant comes only from the signed token, and every query filters
on it*. Organiser B asking for A's event ID gets the same answer as for an ID that doesn't exist,
404. B therefore can't even tell whether A's event exists, which is safer than 403, because 403
would confirm the ID is real.

**Uploading a seat map.** The CSV is checked fully *before* the database is touched, and the
organiser gets a clear message with a line number. Then, in one transaction:
1. lock the event row;
2. check that no seat is held or sold;
3. delete the old seats and insert the new ones;
4. commit.

If anything fails, nothing changes.

**How it fits SurgeGate.** The seats inserted here are what the hold `UPDATE` (Day 4) reserves, and
what the seat-map endpoint and cache serve to buyers. Day 4 Task 4 adds a test that checks *every*
organiser route automatically.

## 4. Errors I hit and how I fixed them

| # | Error (exact message) | Cause | Fix |
| --- | --- | --- | --- |
| 1 | `/usr/bin/bash: -c: line 214: unexpected EOF while looking for matching ''` | One long shell command wrote several files through heredocs, and the quoting inside the test code (`contains '-'`) confused the shell wrapper | Wrote the files with the editor tool instead. Only `seatmap_csv.py` and `schemas.py` existed at that point |
| 2 | `ConnectionRefusedError: [WinError 10061] No connection could be made because the target machine actively refused it` | The `kubectl port-forward` wasn't ready after a fixed 4-second sleep | `pf.sh` waits until `/healthz` answers before the checks run |

## 5. How I verified it works

| Check | Result |
| --- | --- |
| Tests (Postgres 18) | 53 passed (28 new) |
| CI (#20) | ruff + pytest green |
| Deployed (`ea8a22b7acc5`, RDS, real Cognito tokens) | Organiser A: create → `201`, `draft`; upload 96-seat CSV → `200`, 96 seats: gold 24 × ₹1500, silver 36 × ₹900, bronze 36 × ₹500; list → 1 event |
| Cross-tenant on the deployed API | Organiser B list → `[]`; B `GET` A's event → `404 event not found`; B `PUT` seats on A's event → `404`; A still has 96 seats |
| Roles | Buyer → `/org/events` → `403 organiser role required` |

## 6. Cost impact

None (code only).

## 7. Interview notes

- **Q:** Why 404 and not 403 when organiser B asks for A's event?
  **A:** A 403 confirms the event exists, which leaks information. A 404 treats "not yours" exactly
  like "doesn't exist". The tenant is never read from the URL or the body, only from the signed
  token.
- **Q:** What if an organiser re-uploads the seat map during a sale?
  **A:** The replace locks the event row and is refused (409) if any seat is held or sold. The CSV
  is validated in full first, and the delete-and-insert happens in one transaction, so a failure
  leaves the old map intact.
- **Q:** How would you scale this to many tenants?
  **A:** Every query has `tenant_id` first in its index, so tenants don't slow each other down.
  Next steps would be PostgreSQL row-level security as a second guard, and per-tenant rate limits.

## 8. Next task

Day 4 Task 1 — Seat map endpoint with Redis cache and invalidation on change.
