# Week 1 · Day 6 · Task 03 — Buyer waiting-room page: countdown, position, estimated wait, automatic redirect when admitted

- **Date:** 2026-11-22 (early hours; same session)
- **Phase / milestone:** Phase 3 (Waiting room) → M3
- **Status:** Done. Every request the page makes was replayed against dev. The manual browser
  click-through is yours (no browser tool in my session).
- **Commit / PR:** [#34](https://github.com/sheshagiri-62/surgegate/pull/34)

## 1. What the task was

Plan text: *"Buyer waiting-room page: countdown, position, estimated wait, automatic redirect when
admitted."* This is what 50,000 fans actually look at during a sale, so it must be light: join
once, then only poll the shared, cacheable counter.

## 2. What I did, step by step

1. **`/queue/?id=<event>`** (`web/buyer/src/app/queue/page.tsx`, static):
   - sign in (same component as the seat page);
   - **join once**: the `request_id` is kept per event in `sessionStorage`, so a refresh doesn't
     join again (the server also allows only one place per account);
   - ask for the position every 3 s **only until a number arrives** (`joining` / `pre-queue`);
   - after that, poll **only the public `/serving` counter** every 5 s (cacheable at CloudFront
     later) and **compute position, people ahead and the wait in the browser**;
   - **before the sale:** a big countdown and "everyone who arrives before the start gets a
     random place, so there's no need to refresh";
   - **in line:** "You are number 1,234", people ahead, about N minutes (people ÷ rate), a progress
     bar; a paused queue shows "paused" and no estimate;
   - **your turn:** automatically calls `admit`, stores the booking pass and **redirects to the
     seats**. A buyer who already holds a valid pass goes straight to the seats.
2. **`lib/queue.ts`:** API calls plus the pure `view()` logic (phase, ahead, ETA). The counter
   never goes backwards if the cached `/serving` is older than the position answer.
3. **Seat page:** sends `X-Booking-Pass` on every `/book` call. With no pass, or one that's expired
   or refused (403 with `detail.queue`), it goes back to the waiting room.
4. **Home page:** "Open" now leads to the waiting room.
5. **Booking API CORS:** `X-Booking-Pass` added to the allowed headers, and the test now checks it.
6. **Config:** `NEXT_PUBLIC_QUEUE_API` (API Gateway URL) in `.env.example`.

### Commands I ran

```bash
git checkout -b feat/waiting-room-page origin/main
npx jest && npx tsc --noEmit && npx eslint . && npx next build     # 16 tests; / /event /queue static
pytest -q tests/test_cors.py                                        # 2 passed (with x-booking-pass)
gh pr create … ; gh pr merge 34 --squash                            # approved; pipeline → 417baabd44f0
npx next dev --port 3000      # EADDRINUSE (error 2): the earlier dev server was still serving
bash pf.sh && python …        # M3 flow replay (below)
```

### Files created or changed

| File | What it does |
| --- | --- |
| `web/buyer/src/app/queue/page.tsx` | The waiting-room page |
| `web/buyer/src/lib/queue.ts`, `queue.test.ts` | Queue API client, per-tab storage, `view()` / `waitText()`; 7 tests |
| `web/buyer/src/lib/api.ts`, `src/app/event/page.tsx` | Pass on every `/book` call; back to the queue when refused |
| `web/buyer/src/app/page.tsx`, `.env.example` | Home → waiting room; `NEXT_PUBLIC_QUEUE_API` |
| `services/booking-api/app/main.py`, `tests/test_cors.py` | CORS allows `X-Booking-Pass` |

## 3. How it works

The page asks the server for *your* number only once. After that, it only asks the question
everyone shares: "who's being served?". That one answer is identical for 50,000 people, so it can
be cached at the edge, and every browser works out "number 1,234, 400 ahead, about 4 minutes" for
itself. When the shared counter reaches your number, the page swaps your signed queue token for a
booking pass and takes you to the seats; you never press anything. If you come back later without
a valid pass, the seat page sends you back to the queue.

## 4. Errors I hit and how I fixed them

| # | Error (exact message) | Cause | Fix |
| --- | --- | --- | --- |
| 1 | (caught before testing) the browser would have blocked every `/book` call at preflight | `X-Booking-Pass` is a custom header and wasn't in the API's CORS `allow_headers` | Added it; the CORS test now requests it |
| 2 | `Error: listen EADDRINUSE: address already in use :::3000` | The dev server from earlier tonight (PID 38396) was still running: stopping its `npx` wrapper didn't stop the Node process | Used the running one, which serves the current code (`/queue/` → 200). Stopped at session end |

## 5. How I verified it works

| Check | Result |
| --- | --- |
| Jest / lint / typecheck / build | 16 passed (7 new); clean; `/`, `/event`, `/queue` static |
| **M3 flow on dev, replaying the page's requests** with `Origin: http://localhost:3000` | 1) organiser A: *M3 Waiting Room Demo*, 96 seats, `PUT …/queue` → `201 pre-queue`, rate 5/min, sale at 19:56:18. Preflight join → `204`, ACAO localhost:3000. 2) buyer-1 joins → `202`. 3) before the sale: position `pre-queue`, serving `pre-queue` → **countdown**. 4) **numbered at 19:56:47** → position 1. 5) **valve admitted** (serving 1 ≥ 1) → admit. 6) **admit → 200**, pass until 20:11:48. 7) **booking API preflight allows `X-Booking-Pass`**. 8) **seats with the pass → 200, 96 seats** |
| Page served | `http://localhost:3000/queue/?id=…` → 200 |

## 6. Cost impact

None: the page runs locally, and polling costs only per request.

## 7. Interview notes

- **Q:** How does the page stay cheap with 50,000 people waiting?
  **A:** It gets your signed position once, then only polls `/serving`, which is the same for
  everyone and cacheable for 5 s at CloudFront. People ahead and the ETA are computed in the
  browser. The crowd's size only shows up as cached GETs.
- **Q:** What happens if a buyer refreshes or opens a second tab?
  **A:** The same account keeps the same place. The server allows one place per account, and the
  page reuses its stored join. A valid pass skips the waiting room; an expired one sends the buyer
  back.
- **Q:** Why does the admit happen automatically?
  **A:** So nobody loses their slot by not noticing. The moment the shared counter reaches your
  number, the page swaps the token for a pass and opens the seats. The 15-minute window starts at
  that first admission.

## 8. Next task

Day 6 Task 4 — k6 script: 1,000 virtual users join, wait and get admitted (expected cost shown
before running).
