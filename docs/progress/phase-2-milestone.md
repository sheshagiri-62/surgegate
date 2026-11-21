# Phase 2 — Booking core → Milestone M2

- **Checked on:** 2026-11-21 (Day 3, evening; Day 4's tasks were done ahead of schedule)
- **"Done when"** (plan): *an organiser creates an event with a seat map, a buyer holds seats from
  the browser, and the concurrency test proves zero double bookings.*
- **Result:** **Met at the API level on deployed dev.** The browser click-through below is the demo
  step for you to perform and screenshot (no browser tool was available in my session).

## Evidence

| Condition | How it was checked | Result |
| --- | --- | --- |
| Organiser creates an event with a seat map | Deployed API (RDS), real Cognito token for organiser A | `POST /org/events` → 201 *M2 Demo Night*; `PUT …/seats` → 200, 96 seats (gold 24 × ₹1500, silver 36 × ₹900, bronze 36 × ₹500) |
| Buyer holds seats from the browser | The page's exact requests replayed: buyer-web client sign-in (Cognito `USER_AUTH`), CORS preflight from `http://localhost:3000`, seat map, hold | Hold A-1-5 and A-1-6 → 201, ₹3,000, 10-minute expiry; a second viewer 0.40 s later sees both `held` |
| Concurrency test proves zero double bookings | `tests/test_concurrency.py`, 200 parallel HTTP requests released by a barrier | CI (Postgres 18): pass. **Real dev RDS** (from a pod): pass, `{201: 10, 409: 190}`, 10 seats held by 10 different holds; overlapping pairs, no deadlock; same-buyer race exactly 4/20 |
| Tenant isolation (blueprint requirement) | `tests/test_cross_tenant.py` (every organiser route; mutation-checked), plus the deployed API with real tokens | B → A's event: 404 and nothing changed |

## How to demo it (about 5 minutes)

Prerequisites: `make up` done, and the Argo CD apps Synced/Healthy.

```bash
# terminal 1: tunnel to the API (stays open)
kubectl -n booking port-forward svc/booking-api 18080:80
# terminal 2: the buyer app
cd web/buyer && cp .env.example .env.local && npm ci && npm run dev    # http://localhost:3000
```

1. **Organiser creates the event.** For now this goes through the API: the organiser UI is on
   Day 7–8. Use the test users from Secrets Manager `surgegate/dev/test-users`: sign in organiser A
   with the `test` client, then `POST /org/events` (sale start in the past) and `PUT
   /org/events/{id}/seats` with a CSV.
2. Open `http://localhost:3000/event/?id=<event id>`, choose **Use a password instead**, and sign
   in as `buyer-1@surgegate.test` (password from the same secret).
3. Pick 2 seats (they turn indigo), then **Hold seats**. The green banner shows the seats, the total
   and the 10-minute timer.
4. Open the same URL in a **private window**, signed in as another user. Within about 2 seconds
   those two seats show grey ("Taken").
5. Try to pick a taken seat: it can't be selected. Clicking past the limit does nothing.
6. Show CI: PR #23's `booking-api` job, `test_200_parallel_requests_for_the_same_10_seats_exactly_10_succeed`.

## Screenshots to take

1. The event page with the seat map and legend (zones + "Taken" + "Your pick").
2. Two seats selected, with the "2 selected · ₹3,000" bar.
3. The green hold banner with the countdown.
4. The private window showing the same seats grey.
5. GitHub Actions: the `ci` run for #23 with the concurrency test passing (and "80 passed").
6. The terminal: the RDS pod run, `38 passed`, with `test_200_parallel…` in `--durations`.
7. Argo CD: `booking-api` Synced/Healthy, with the `booking-api-migrate` Job completed.

## What's not in M2 (by design)

- No waiting room or booking pass yet (Phase 3); `/book/*` currently needs any signed-in user.
- Holds expire in the data but aren't yet *released* (Step Functions timer, Day 7).
- No payment (Phase 4).
- CloudFront is still blocked by account verification, so the public URL waits for that (ADR 003).
