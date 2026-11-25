# Phase 4 — Checkout and live events → Milestone M4

- **Checked on:** 2026-11-25, 06:08–06:22 UTC (11:38–11:52 IST), dev through CloudFront
  (`https://d1t9vww2xtyvsz.cloudfront.net`)
- **"Done when"** (plan): *a buyer goes from queue to paid ticket email in one run, a duplicate
  webhook changes nothing, an unpaid hold is released after 10 minutes, and the organiser watches
  it all update live.*
- **Result: MET.** All four conditions passed in one run with a fresh test buyer. One thing to
  redo: **your screen recording.** During the run your browser was on the "Valve test" event
  (the first one in the list), not "M4 demo", so the video doesn't show these numbers. The
  organiser's live feed itself was checked on the M4 event (below).

## The run

Fresh Cognito buyer `m4-buyer-1125112621@example.test` (verified email, group `buyer`; deleted
afterwards), new event **"M4 demo 1125112621"** (`5191b64c-43e5-4cdf-a1db-a986602df8b8`, 10 seats
at ₹1,500, waiting room open at 250/min). The organiser side is organiser_a's live WebSocket, the
same feed the dashboard page uses. Scripts: `m4_setup.py`, `m4_run.py`, `m4_pod.py` (scratchpad).

### Time for each step to appear on the dashboard

"Event" = when the system recorded the step (the `at` field in the analytics table). "Pushed" =
when the live-dashboard Lambda finished sending the new numbers to the socket (its log). All
times UTC on 25 Nov.

| # | Step | Buyer's action | Event | Pushed | Event → dashboard | Action → dashboard |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Join the queue (`202`) | ~06:08:05 | `joined` 06:08:20.05 | 06:08:23.74 | **3.7 s** (cold start) | **~18 s** |
| 2 | Admitted, booking pass issued (`200`) | 06:09:14 | `admitted` 06:09:14.73 | 06:09:16.47 | **1.7 s** | ~2 s |
| 3 | Hold 2 seats (`201`) | 06:10:17 | `seat_held` 06:10:17.02 | 06:10:17.51 | **0.5 s** | ~0.5 s |
| 4 | Pay on the mock checkout (`303`) → webhook → order worker | ~06:11:15.6 | `order_paid` 06:11:18.17 | 06:11:18.50 | **0.3 s** | ~2.9 s |
| 5 | Ticket worker: PDF + QR, SES email sent 06:11:19.42 | (automatic) | `ticket_issued` 06:11:19.42 | 06:11:21.49 | **2.1 s** | 3.3 s after payment |
| 6 | Same `payment.captured` webhook sent twice more (`200 queued` ×2) | 06:11:28 | none | none | **nothing changed** (correct) | — |
| 7 | Unpaid hold of 1 more seat (`201`) | 06:11:59 | `seat_held` 06:11:59.19 | 06:12:00.49 | **1.3 s** | ~1.3 s |
| 8 | 60 s timer releases it (timer started 06:13:03.50) | (automatic) | `hold_released` 06:14:06.73 | 06:14:09.76 | **3.0 s** (cold start) | 63.2 s after the timer started |

**Against the target "updates within 5 s (p95)":** event → dashboard was **0.3–3.7 s for all 7
updates** (two of them with a Lambda cold start), so the dashboard path meets it. From the buyer's
click, only the **join** is slow (~18 s). The join Lambda answered at 06:08:08, but the waiting
room's **sequencer** only picked the join up at 06:08:19, its first poll of an SQS FIFO queue that
had been idle. That is the same idle-queue delay as in Task 3a (22 s cold, 5.9 s warm). Under a
real sale the queue is busy and the poller is warm. **Re-measure in the Day 9/10 load test.** If
it's still over 5 s there, count joins in the join Lambda instead of the sequencer.

### The four conditions

| Condition | Evidence | Result |
| --- | --- | --- |
| **Queue → paid ticket email in one run** | Order `b13ffc3a`: `status paid`, paid 06:11:18.16, **email sent 06:11:19.42** (SES message ID stored), 2 tickets, seats A-1-1 A-1-2 `sold`, `buyer_email` stored on the order and it's the fresh buyer's (Task 4 fix). `/book` without the pass → `403` at the edge | **Met** |
| **Duplicate webhook changes nothing** | The real payment's `payment.captured`, signed in the pod, sent twice more → `200 {"status":"queued"}` both times. 25 s later: **order changes: none**, payments still 1, tickets still 2, **same SES message ID** (no second email), dashboard unchanged, no live-dashboard push at all between 06:11:21 and 06:12:00 | **Met** |
| **Unpaid hold released after 10 minutes** | Fast path (you allowed 60 s): a second timer run with a 60 s wait started 06:13:03.50 and released the seat at 06:14:06.95. Hold `released`, 0 seats still held, dashboard `held 0`. **Real path:** the hold's own 10-minute timer started 06:11:59.18 and ran at 06:21:59.44 (exactly 600 s) with `released_seats: []`, `hold_was_active: false`. It found the hold already released and changed nothing, so the release is idempotent. The 10-minute release of a still-held hold was shown live on Day 7 ([task-02-hold-timer](day-07/task-02-hold-timer.md)) | **Met** |
| **Organiser watches it update live** | organiser_a's live token for the M4 event → WebSocket; snapshot on connect, then 7 pushes (table above), each 0.3–3.7 s after the event. Final dashboard: waiting 0, admitted 1, held 0, sold 2, tickets 2, revenue ₹3,000. Sale stats: joined 1, admitted 1, orders_paid 1, released_seats 1 | **Met** (feed). Your recording: **re-take**, see below |

Earlier Day 8 checks behind M4: ticket worker (6 emails / 6 orders, no duplicates; all in Gmail
Spam because of DMARC), live dashboard (Task 3a: duplicates counted once), organiser dashboard and
gate (Task 4: pause/resume/rate, one-time check-in, CSV, relative redirects).

## How to demo it (and re-take the recording)

1. `make up` (if down). Argo CD Synced/Healthy.
2. Open `https://d1t9vww2xtyvsz.cloudfront.net/organiser/login` and sign in as organiser_a
   (password in `surgegate/dev/test-users`). Create an event, or open the **exact event URL**
   (`/organiser/events/<id>`), not the first item in the list.
3. As a buyer (buyer_1 or a fresh test user): join the queue → admitted → hold 2 seats → pay on
   the mock checkout. Watch waiting → admitted → held → sold, revenue and tickets change on the
   page. The ticket email arrives (Gmail: check Spam).
4. Re-send the same webhook (`m4_pod.py sig <order>`, then POST to `/webhooks/razorpay` twice).
   The page doesn't change.
5. Hold one more seat and don't pay. It's released by the timer (10 minutes, or 60 s with a second
   timer run). Held goes back to 0.

### Screenshots to take

1. The organiser event page with the live panel showing **sold 2, tickets 2, ₹3,000**.
2. The ticket email (PDF attached, QR visible), in Spam with Gmail's "why is this in spam" note.
3. The live panel **before and after** the duplicate webhooks: identical numbers.
4. The live panel with **held 1**, then **held 0** after the release.
5. The Step Functions console: the hold timer execution (`Wait` → `Release`) and its output
   `hold_was_active: false` for the 10-minute run.
6. The attendee CSV opened in a spreadsheet: buyer email filled in.
