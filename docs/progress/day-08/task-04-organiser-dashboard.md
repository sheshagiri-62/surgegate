# Week 2 · Day 8 Task 4 — Organiser SSR dashboard on EKS + gate check-in

- **Date:** 2026-11-25
- **Phase / milestone:** Phase 4 → M4 (closed by this task, see [phase-4-milestone](../phase-4-milestone.md))
- **Status:** Done
- **Commit / PR:** [#56](https://github.com/sheshagiri-62/surgegate/pull/56) (dashboard + gate),
  [#57](https://github.com/sheshagiri-62/surgegate/pull/57) (relative redirects),
  [#58](https://github.com/sheshagiri-62/surgegate/pull/58) (buyer email on the order, CSV escaping,
  CloudFront `/organiser*` behaviours)

## 1. What the task was

Plan, Day 8 Task 4: *"Organiser SSR dashboard on EKS: live numbers, pause/resume, admission rate,
attendee export; gate check-in endpoint."* The organiser needs one screen to run a sale: see the
numbers move, slow or stop the waiting room, download who bought, and scan tickets at the gate.

## 2. What I did, step by step

1. **Gate check-in endpoint** in the booking API: `POST /org/events/{id}/check-in` verifies the QR
   token's HMAC signature (same key and format the ticket worker signs with), checks the ticket
   belongs to this organiser's event and a paid order, then marks it used **once** with
   `UPDATE … SET used_at = now() WHERE used_at IS NULL RETURNING used_at`. Answers: 200 admitted,
   409 already used (with the first-use time), 400 forged / wrong event, 404 unknown, 409 not paid.
2. **Attendee export** `GET /org/events/{id}/attendees.csv`: one row per ticket of a paid order.
3. **Organiser app** `web/organiser` (Next.js, server-side rendered, `basePath /organiser`,
   standalone output): sign-in page (Cognito `USER_PASSWORD_AUTH` on the server; the access token
   lives only in an `HttpOnly; SameSite=Strict; Secure` cookie), events list, event page with the
   live panel (WebSocket), pause/resume, admission rate, check-in form and CSV download. All API
   calls happen **on the server** inside the cluster (`http://booking-api.booking.svc`).
4. **Deploy wiring:** Helm chart `deploy/helm/organiser` (non-root, read-only root filesystem, no
   service-account token, TargetGroupBinding), Argo CD app, ECR repo + CI push permission,
   `build-deploy-organiser.yml` (lint → typecheck → build → image → smoke test as the cluster runs
   it → Trivy → push → tag bump → Argo CD), ALB rule `/organiser*` (priority 6).
5. **Live check through CloudFront** found that redirects pointed at the pod's own address
   (`http://0.0.0.0:8000/...`), so **#57** made every redirect relative.
6. **Your three fixes (#58)**, none of which were in #56:
   - **Buyer email on the order.** The Cognito pre-token Lambda copies the *verified* email into
     the access token; the booking API stores it in the new `orders.buyer_email` (migration 0004)
     when the order is created. The export reads it from the order (no Cognito `ListUsers` per
     row; that IAM permission was removed), and the ticket worker uses it too (Cognito only for
     orders made before the change). The user pool was already on **Essentials** with the V2
     trigger (needed for access-token claims), so this costs nothing extra.
   - **CSV formula injection:** any cell starting with `=`, `+`, `-`, `@`, tab or CR gets a `'`
     in front.
   - **CloudFront:** `/organiser` and `/organiser/*` got their own cache behaviours (caching
     disabled, all viewer headers, cookies and query strings forwarded, the dev-down 503
     function when the origin is off). Before, they only worked because they fell through to
     the default behaviour, which becomes the S3 buyer site next.
7. **M4 run** (below and in the milestone file).

### Commands I ran

```bash
# tests (local Postgres in Docker on 127.0.0.1:15432)
DATABASE_URL=postgresql+psycopg://surgegate:***@127.0.0.1:15432/surgegate_test \
REDIS_URL=redis://127.0.0.1:16379/0 .venv/Scripts/python.exe -m pytest -q   # booking-api: 157 passed
DATABASE_URL=postgresql://surgegate:***@127.0.0.1:15432/surgegate_test \
.venv/Scripts/python.exe -m pytest -q                                       # workers: 22 passed
ruff check . && ruff format --check .
cd web/organiser && npm ci && npm run lint && npm run typecheck && npm run build

# image smoke test, exactly as the cluster runs it
MSYS_NO_PATHCONV=1 docker run -d --name org --read-only --user 1000 \
  --tmpfs /app/.next/cache -p 8000:8000 surgegate/organiser:local
curl -fsS http://localhost:8000/organiser/api/healthz

# infra (each plan shown to you before apply)
terraform fmt -recursive infra
terraform -chdir=infra/envs/dev validate
terraform -chdir=infra/envs/dev plan -input=false -lock-timeout=5m -var=enable_nat_gateway=true \
  -var=enable_eks=true -var=enable_data=true -var=enable_kinesis=true \
  -var=restore_snapshot_id=surgegate-dev-pg-final-873e7969 -out=t4fix.tfplan
#   Plan: 0 to add, 6 to change, 0 to destroy
terraform -chdir=infra/envs/dev apply -input=false t4fix.tfplan
#   Apply complete! Resources: 0 added, 5 changed, 0 destroyed.

# merge, deploy, migration
gh pr merge 57 --squash --delete-branch
gh pr merge 58 --squash --delete-branch
kubectl -n booking logs job/booking-api-migrate      # Running upgrade 0003 -> 0004

# live checks
python organiser_browser.py <event> ticket_a11.txt    # every redirect followed like a browser
python m4_setup.py && python m4_run.py                # the M4 run
```

### Files created or changed

| File | What it does |
| --- | --- |
| `services/booking-api/app/routes/gate.py` | Check-in (one-time `used_at`), attendee CSV with formula escaping |
| `services/booking-api/alembic/versions/0004_order_buyer_email.py` | `orders.buyer_email` |
| `services/booking-api/app/auth.py`, `orders.py`, `routes/orders.py`, `models.py` | Email claim → `Principal.email` → stored on the order |
| `infra/modules/identity/lambda/pre_token.py` | Adds the verified `email` claim to the access token |
| `services/workers/src/sg_workers/ticket_worker.py` | Sends to the order's stored email (Cognito only as a fallback) |
| `web/organiser/**` | The Next.js SSR dashboard (pages, route handlers, `LivePanel`, `redirect.ts`) |
| `deploy/helm/organiser/**`, `deploy/argocd/organiser.yaml` | Chart and Argo CD app |
| `.github/workflows/build-deploy-organiser.yml`, `ci.yml` | Build/deploy pipeline; organiser job in CI |
| `infra/modules/edge/main.tf`, `variables.tf` | `ssr_path_patterns` → no-cache CloudFront behaviours |
| `infra/envs/dev/main.tf`, `booking_api.tf` | ALB route, behaviours, ticket-key read; `ListUsers` removed |
| `services/booking-api/tests/test_gate.py`, `test_cross_tenant.py`, `helpers.py` | 7 gate/export tests + 8 escaping cases; cross-tenant recipes |
| `services/workers/tests/test_ticket_worker.py` | Stored email used without Cognito |

## 3. How it works

**Server-side rendering (SSR)** means the page's HTML is built on our server for every request,
not in the browser. That lets the organiser app keep the Cognito token in a cookie that page
JavaScript can't read (`HttpOnly`), and call the booking API from inside the cluster. The only
thing the browser gets is a **60-second live token** for one event, which it uses to open the
WebSocket. The live numbers come from the live-dashboard consumer (Task 3a), which pushes each
sale's new totals to every socket subscribed to that event.

**Gate check-in** is a "compare and set" in one SQL statement: `WHERE used_at IS NULL` means only
the first scan can change the row. Two gates scanning the same ticket at the same moment can't
both get "admitted", because Postgres lets only one of the two updates match the row.

**Why the email goes on the order:** the access token (the one the API accepts) doesn't carry the
email by default. Copying the verified address into it at sign-in, and onto the order at
creation, means the export and the ticket email never need one Cognito call per buyer. At 50,000
buyers that would be 50,000 calls, and Cognito's `ListUsers` is rate-limited.

**CSV injection:** a spreadsheet treats a cell starting with `=` (or `+ - @`) as a formula. A
buyer could set a name or email like `=HYPERLINK("http://evil…")`, and it would run when the
organiser opens the export. A leading `'` makes the spreadsheet show it as text.

**Relative redirects:** behind CloudFront the pod doesn't know the public host name. Next.js
built absolute `Location` headers from the pod's own bind address. A relative `Location:
/organiser/events` is resolved by the browser against the host it is already on.

## 4. Errors I hit and how I fixed them

| # | Error (exact message) | Cause | Fix |
| --- | --- | --- | --- |
| 1 | `KeyError: 'TICKET_KEY_SECRET_ID'` (cross-tenant test for check-in) | The test app had no ticket key | `TICKET_KEY_JSON` test key in `conftest.py` |
| 2 | Owner's own request in the cross-tenant test failed with `400 {"result":"refused","reason":"malformed ticket"}` | The owner's recipe sends a dummy token; 400 is the right answer | `owner_status: 400` in that recipe |
| 3 | CI didn't run on #56: `ci.yml` was empty | My edit helper opened the file for **writing before reading** it (`open(p, "w").write(rd(p) + …)`), which truncated it | Restored `ci.yml` from `main` and re-added only the organiser job |
| 4 | `fatal: ambiguous argument 'origin/main:.github/workflows/ci.yml'` (and the first restore pushed an empty file) | Git Bash turned the `:path` argument into a Windows path | `MSYS_NO_PATHCONV=1 git show …` |
| 5 | `invalid mount path: 'C'` (docker smoke test) | Same Git Bash path conversion on `--tmpfs /app/.next/cache` | `MSYS_NO_PATHCONV=1` |
| 6 | Plan wanted to **create** `kubernetes_manifest.argocd_root_app` (already exists) | A one-off bad read of the cluster object | Targeted refresh showed no change; re-ran the plan: clean; never applied |
| 7 | Sign-in answered `303 Location: http://0.0.0.0:8000/organiser/events` | Next.js built absolute redirects from the pod's bind address | #57: `seeOther()` returns relative `Location` headers; cookie set explicitly |
| 8 | `invalid-syntax: missing closing quote in string literal` (gate.py) | My shell heredoc turned `"\t"` and `"\r"` into real tab/CR characters | Fixed with the editor (`"\t"`, `"\r"`) |
| 9 | ruff `E501 Line too long` ×2 | Docstring and SQL line | Wrapped |
| 10 | `runtime: failed to create new OS thread (have 16 already; errno=1450)` / `fatal error: out of memory` (terraform validate/plan, pre-commit hooks, git, kubectl) | Windows had ~125 MB of virtual memory free (IDE 4.7 GB, WSL 3.3 GB) plus an **orphan terraform-provider-aws** left by an earlier run (436 MB, no parent) | Killed the orphan, stopped the idle buildx container; you closed the IDE and ran `wsl --shutdown`; then everything ran (hooks not skipped) |
| 11 | `Error: No valid credential sources found` / `failed to refresh cached credentials, create oauth2 token: login` | `aws login` session expired | You ran `aws login --profile surgegate` |
| 12 | `unexpected EOF while looking for matching '''` | Two nested heredocs in one shell command | Wrote the M4 scripts with the editor |
| 13 | `COLUMN_NOT_FOUND: line 1:14: Column 'occurred_at' cannot be resolved` (Athena) | Guessed the column; the table calls it `at` | Read the Glue columns, queried `at` |
| 14 | `InvalidParameterException … logGroupName … [\.\-_/#A-Za-z0-9]+` | Git Bash path conversion again (one command without the variable) | `MSYS_NO_PATHCONV=1` |
| 15 | **M4 measurement bug:** my script printed "dashboard … after None s" for join, admit and both holds | The pushes **did** reach the socket (live-dashboard Lambda logged `pushed: 1` each time, and a raw dump showed them arriving), but my listener recorded them late, in a burst. Payment and tickets got the same timestamp, which proves it | Took the times from the server side: event time (Athena `at`) → push sent (Lambda log). Raw-dump check: join → dashboard 22.4 s, the same path |
| 16 | (finding) your browser was on **"Valve test"** during the run, not M4 demo | WebSocket logs: your page connected at 06:05:23 and 06:15:29 UTC to event `43635ae3` (Valve test); only my socket was on the M4 event. The events list shows Valve test first; the links themselves are correct | Re-take the recording on the M4 page (milestone file); sorting the list newest-first is a small follow-up |

## 5. How I verified it works

**Live organiser check through CloudFront** (organiser_a, event `24052880…`, your real ticket):

- Signed out → `/organiser/login`. Sign-in → cookie `HttpOnly; SameSite=Strict; Secure`. SSR events
  list (15 events) and event page.
- Live token → WebSocket numbers (2 waiting, 1 admitted, 2 sold, ₹3,000, rate 250). Pause, resume
  and rate 300 → 250 each showed on the page.
- Check-in of seat A-1-1: first scan **admitted**, second **already used** ("first used 21:21:33
  UTC"), a tampered token **refused (forged)**. CSV: A-1-1 checked in, A-1-2 not.
- **After #57, every redirect followed like a browser (10 steps): 0 hops off the CloudFront
  host.** Wrong password → `/organiser/login?error=Incorrect+username+or+password.`; logout →
  `/organiser/login`.
- After #58: fresh access tokens for `buyer_1`, `organiser_a`, `organiser_b` all carry `email`.
  The M4 order has `buyer_email` stored (the fresh buyer's address). The export header is
  `seat,order_id,buyer_email,paid_at,ticket_id,checked_in_at`, and a `=HYPERLINK(...)` email comes
  out as `'=HYPERLINK(...)` (test).

**Emails so far:** 6 ticket emails for 6 distinct orders, one SES message ID each, no duplicates
(your inbox count matches the database). SES's own count is 7 because it includes the
verification email. **All of them landed in Gmail Spam**, as expected: the sender is a verified
Gmail address sent through SES, so the message fails Gmail's DMARC alignment check. A real domain
with SPF/DKIM/DMARC records would fix it (it waits for the domain, as in ADR 003).

**M4 run** (fresh test buyer `m4-buyer-1125112621@example.test`, event "M4 demo",
`5191b64c…`): the full table is in the [milestone file](../phase-4-milestone.md). In short:
queue → admitted → hold → pay → ticket email (sent 1.3 s after payment); 2 duplicate webhooks →
no change anywhere; the unpaid hold released by the 60 s timer (63.4 s); the real 10-minute
timer then found nothing to release.

## 6. Cost impact

No new hourly resources. New: one ECR repository (pennies per GB), one ALB rule and target group
(free on the existing ALB), two CloudFront behaviours (free), one small pod on the existing
nodes. Cognito stays on Essentials inside its free tier. Torn down with the rest of dev by
`make down` (the ECR repo lives in `infra/bootstrap`).

## 7. Interview notes

- **Q:** Two gate staff scan the same ticket at the same second. What stops both from admitting it?
  **A:** One SQL statement: `UPDATE tickets SET used_at = now() WHERE id = :t AND used_at IS NULL
  RETURNING used_at`. Postgres row locking lets only the first update match; the second matches
  nothing, returns no row, and we answer "already used" with the first scan's time.
- **Q:** Why server-side rendering for the organiser app but a static site for buyers?
  **A:** Organisers are few and their pages are private and per-user, so SSR can keep the token in
  an `HttpOnly` cookie and call the API inside the cluster. Buyers are many (50,000 at once), so
  their site must be static files on S3 + CloudFront that cost nothing to serve and never hit
  our servers.
- **Q:** What is CSV injection and how did you stop it?
  **A:** Spreadsheets run cells that start with `= + - @` as formulas, so user-supplied text in an
  export can become a formula (for example a link that leaks data). We prefix those cells with
  `'` so the spreadsheet shows them as text (the OWASP guidance).

## 8. Next task

Buyer site on S3 + the same CloudFront (rename the `/queue/` page, a CloudFront Function for
`/x/` → `/x/index.html`, the booking-pass function stays on `/book/*`, re-run the M3 edge
check), then Day 9: WAF, load test, chaos.
