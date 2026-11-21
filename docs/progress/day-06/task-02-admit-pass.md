# Week 1 · Day 6 · Task 02 — `admit` endpoint issuing a 15-minute booking pass (CloudFront Function check pending)

- **Date:** 2026-11-22 (early hours; same session)
- **Phase / milestone:** Phase 3 (Waiting room) → M3 ("a request to `/book/*` without a valid pass is refused at the edge")
- **Status:** Done in the booking API. **The edge (CloudFront Function) check is pending CloudFront
  verification**: written and plan-checked, behind `enable_cloudfront`.
- **Commit / PR:** [#33](https://github.com/sheshagiri-62/surgegate/pull/33)

## 1. What the task was

Plan text: *"`admit` endpoint issuing a 15-minute booking pass; CloudFront Function checking it on
`/book/*`."* Your change for tonight: the booking API must verify the pass itself now, and the
CloudFront Function stays pending until CloudFront is verified.

## 2. What I did, step by step

1. **`POST /queue/{event}/admit {queue_token}`** (`sg_queue/admit.py`, JWT):
   1. The queue token must be genuine, unexpired, and for **this signed-in user and this event**.
      A copied token is useless.
   2. The stored place must match the token's position, and it must be reached
      (`position ≤ serving_up_to`). Otherwise `409 not your turn yet`.
   3. It issues a **booking pass** `{typ: "pass", ev, sub, iat, exp}`, signed with a **separate key**
      `surgegate/dev/queue/pass-key` (write-only, never in state).
   - **The 15 minutes count from the first admission** (`admitted_at` via `if_not_exists`), so
     asking again gives the same expiry, and once it's over the answer is `410`.
2. **The booking API checks the pass** (`app/booking_pass.py`) on every `/book/{event}/…` route
   (seat map, holds), from the `X-Booking-Pass` header:
   - signature (constant-time compare), key ID, type, expiry, the **event in the URL**, and the
     **same user as the verified Cognito token**;
   - a refusal is `403 {"detail": {"reason": …, "queue": "/queue/<event>/join"}}`, so the browser
     knows where to send the buyer;
   - the key comes from Secrets Manager with the pod's role (cached 5 min);
   - `BOOKING_PASS_REQUIRED` is true in the dev chart.
3. **Tests that grow with the API** (`tests/test_booking_pass.py`):
   - every `/book/{event_id}` route is discovered from OpenAPI;
   - each is attacked with **missing, garbage, forged, expired, other-event, other-user and
     wrong-type** passes (all must be 403), and then a genuine pass must work;
   - the **200-request concurrency race now runs with real booking passes**, the production path.
4. **Pending CloudFront verification** (`infra/modules/edge`, created only when
   `enable_cloudfront`):
   - CloudFront Function `booking-pass` (`functions/booking_pass.js`, cloudfront-js-2.0). It checks
     HMAC, type, expiry and the event in the URL at the edge; the API re-checks everything,
     including the user.
   - a **KeyValueStore** holding the pass key, and an ordered behaviour `/book/*` with the function
     on viewer-request.
   - **Pending one-time step after verification:** copy `pass-key` from Secrets Manager into the
     KeyValueStore (`aws cloudfront-keyvaluestore put-key`). Terraform never holds the value.

### Commands I ran

```bash
git checkout -b feat/booking-pass origin/main
pytest -q (queue)          # 50 passed (7 admit)
pytest -q (booking-api)    # 3 failed (error 1) → 95 passed
terraform … plan -var=enable_cloudfront=true      # PLAN ONLY: booking_pass function + KVS + /book/* behaviour
terraform … plan -out=admit.tfplan                 # 9 add, 14 change, 0 destroy
terraform … apply admit.tfplan                     # approved: 9 added, 7 changed
python …  # position → admit → verify pass with the key; admit again; garbage token
aws dynamodb update-item … SET active = "1"         # put the M2 demo queue on the valve
gh pr merge 33 --squash                             # approved; pipeline → 1f916f5bbded
bash pf.sh && python …                              # /book with no/tampered/other-event/other-user/valid pass; hold
```

### Files created or changed

| File | What it does |
| --- | --- |
| `services/queue/src/sg_queue/admit.py`, `tests/test_admit.py` | The endpoint; 7 tests |
| `services/booking-api/app/booking_pass.py` | Pass verification dependency |
| `services/booking-api/app/routes/buyer.py` | Pass required on seat map and holds |
| `services/booking-api/tests/test_booking_pass.py`, `helpers.py`, `conftest.py`, `test_holds.py`, `test_concurrency.py` | Route-discovering pass tests; pass helpers; race with passes |
| `infra/modules/queue/main.tf`, `variables.tf`, `outputs.tf` | admit Lambda + route; pass-key secret (write-only) |
| `infra/envs/dev/booking_api.tf` | Pod may read the pass key |
| `deploy/helm/booking-api/…` | `BOOKING_PASS_REQUIRED`, `BOOKING_PASS_SECRET_ID` |
| `infra/modules/edge/main.tf`, `functions/booking_pass.js` | **Pending:** CloudFront Function, KeyValueStore, `/book/*` behaviour |

## 3. How it works

The waiting room hands out **two different signed notes**:
- the **queue token** says "you are number 57";
- the **booking pass** says "you may book for event X until 19:58".

Only the admit step turns one into the other, and only when your number has been reached. The
booking API refuses every seat request that doesn't carry a valid pass for that same user and
event. That's how the valve's admission rate becomes the real limit on how many people are
booking.

Different keys keep the two apart: a queue token can never be used as a pass, even though both use
the same format. Fixing the expiry at the first admission stops "admit again" from becoming
"book forever".

Once CloudFront is verified, the same check runs at the edge too, so a request without a pass is
refused before it reaches the load balancer. The API keeps its own check as defence in depth.

## 4. Errors I hit and how I fixed them

| # | Error (exact message) | Cause | Fix |
| --- | --- | --- | --- |
| 1 | 3 tests failed: `KeyError: 'seats'` (in `tests/test_holds.py:30`) | The `open_event` helper read the seat map as a plain buyer, and the new check (rightly) answered 403 | The helper reads as an `admitted_buyer` (token + pass) |
| 2 | ruff `S105 Possible hardcoded password assigned to: "BOOKING_PASS_REQUIRED"` | False positive: a feature flag | `# noqa: S105` with the reason |
| 3 | Scripted edit stopped: `AssertionError: ('tests/test_concurrency.py', '        seat_ids = [s["id"] for s in c.get(…', 0)` | ruff had wrapped that line differently from what I assumed; the earlier edits in the same script had applied | Finished with the editor tool |

## 5. How I verified it works

| Check | Result |
| --- | --- |
| Tests | queue 50 (7 admit: 15-min pass bound to the user; not yet → 409; someone else's token → 403; forged or mismatched position → 403; expiry from the first admission (5 min left, not 15); window over → 410; bad body → 422). Booking API 95 (every `/book` route × 7 bad passes → 403, genuine → OK; reason given; concurrency race with passes) |
| Admit on AWS (buyer-1, #57, serving 65) | `200`; pass verifies with the pass key (`kid p1`, **15.0 min**); admit again → **same expiry**; garbage token → `403 invalid queue token: malformed token` |
| Booking API on dev (`1f916f5bbded`, M2 Demo event, real tokens) | admitted (pos 1, serving 1) → pass. `/book` seats: **no pass → 403** `booking pass required` (+ queue link); **tampered → 403 forged pass**; **pass for another event → 403**; **buyer-1's pass with organiser A's token → 403 pass belongs to someone else**; **valid pass → 200, 96 seats**; **hold with pass → 201 A-1-1** |
| Edge check | Plan-only: `aws_cloudfront_function.booking_pass`, `aws_cloudfront_key_value_store.edge`, `/book/*` behaviour. **Live "refused at the edge": pending CloudFront verification** |

## 6. Cost impact

One more secret ($0.40/month); everything else is per request. The CloudFront Function and
KeyValueStore (later) cost per invocation.

## 7. Interview notes

- **Q:** How does the booking API know a buyer came through the waiting room?
  **A:** The admit step issues a 15-minute HMAC-signed pass bound to the user and event, and only
  when their queue number has been reached. Every `/book` request must carry it; the API checks the
  signature, expiry, event and that it belongs to the same user as the Cognito token.
- **Q:** Why a different key for passes than for queue tokens?
  **A:** So one can never be passed off as the other, and so the edge (CloudFront) only needs the
  pass key. Each key is rotatable via its `kid`, and neither is ever in Terraform state.
- **Q:** Why check at the edge and in the API?
  **A:** The edge check (CloudFront Function) stops unadmitted traffic before it costs anything in
  the VPC. The API check is defence in depth, and it also verifies the user binding, which needs
  the Cognito signature the edge function can't verify.

## 8. Next task

Day 6 Task 3 — Buyer waiting-room page: countdown, position, estimated wait, automatic redirect
when admitted.
