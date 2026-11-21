# Week 1 · Day 4 · Task 05 — Buyer Next.js app: event page and seat picker calling the API (no queue yet)

- **Date:** 2026-11-21 (evening of Day 3, ahead of schedule)
- **Phase / milestone:** Phase 2 (Booking core) → M2
- **Status:** Done. Every request the page makes was verified against deployed dev. The manual
  click-through in a browser is the M2 demo step (see `phase-2-milestone.md`).
- **Commit / PR:** [#25](https://github.com/sheshagiri-62/surgegate/pull/25)

## 1. What the task was

Plan text: *"Buyer Next.js app: event page and seat picker calling the API (no queue yet)."* You
asked how I'd expose it safely without CloudFront. We agreed: **the app runs on the laptop, and the
API is reached through `kubectl port-forward`.** Nothing is exposed to the internet and nothing
changes in AWS.

## 2. What I did, step by step

1. **`web/buyer`:** Next.js 16.4.6, React 19.3.1, TypeScript 5.9.3 and Tailwind 4.3.5, built as a
   **static export** (`output: "export"`). The site is plain files, to be served from S3 +
   CloudFront later.
   - TypeScript 7 was available, but I chose the mature 5.9 line that the Next and typescript-eslint
     tooling supports.
   - ESLint 9.39 for the same reason.
2. **`/event/?id=<event>`:**
   - name, venue and date, plus a **countdown to the sale**;
   - **the seat map** grouped by section and row (natural order: row 2 before row 10), coloured by
     price zone, with a legend; taken seats are greyed out and disabled;
   - **the picker** stops at the event's per-buyer limit (the server enforces the real limit);
   - **Hold seats** → `POST /book/{event}/holds` → a banner with the seats, total and a
     **10-minute countdown**;
   - **refresh every 2 s** (the API's cache TTL), and any selected seat someone else took is dropped
     from your selection;
   - a 409 shows "Someone just took A-1-3. Pick another."
3. **Sign-in straight against Cognito** (`src/lib/cognito.ts`, no SDK): `USER_AUTH` with
   **email + one-time code** for real buyers, or **password** for the dev `.test` users, which
   can't receive email. The access token is kept in `sessionStorage`, and the page loads no
   third-party scripts.
4. **Pure logic in `src/lib/seatmap.ts`** (grouping, selection rules, money, countdown), with
   9 Jest tests.
5. **API CORS** (`app/main.py`):
   - only the origins in `CORS_ALLOW_ORIGINS` (dev chart: `http://localhost:3000`);
   - only `GET`, `POST` and `PUT`, with the `Authorization` and `Content-Type` headers;
   - no credentials (bearer tokens, not cookies).
   - 2 tests.
6. **CI:** a new `buyer-web` job runs `npm ci`, lint, typecheck, jest and a static build.
   `actions/setup-node` is pinned to `949feb2413d6458794dcd2491c4babbbce0c15c1`, the v7.1.0 commit
   looked up through the GitHub API.

### Commands I ran

```bash
npm view next react typescript eslint … version       # pick exact versions
npm view next@16.4.6 peerDependencies                  # compatibility
npm install --no-audit --no-fund
npx jest && npx tsc --noEmit && npx eslint . && npx next build   # lint: 3 errors, 3 warnings (error 2)
# after fixes: lint clean, tsc ok, 9 tests, build → / and /event static
python -m pytest -q   # API: 82 passed (2 CORS tests)
gh api repos/actions/setup-node/releases/latest ; gh api repos/actions/setup-node/git/ref/tags/v7.1.0
gh pr create … ; gh pr merge 25 --squash               # approved; 4 checks green
kubectl -n booking port-forward svc/booking-api 18080:80      # background
npx next dev --port 3000                                       # background
python … # browser-equivalent flow (below)
```

### Files created or changed

| File | What it does |
| --- | --- |
| `web/buyer/package.json`, `package-lock.json`, `next.config.ts`, `tsconfig.json`, `eslint.config.mjs`, `postcss.config.mjs`, `jest.config.js`, `.env.example`, `.gitignore` | Project setup (static export) |
| `web/buyer/src/app/layout.tsx`, `globals.css`, `page.tsx` | Shell and the "find your event" page |
| `web/buyer/src/app/event/page.tsx` | Event page: countdown, seat map, hold, timer, refresh |
| `web/buyer/src/components/SeatPicker.tsx`, `SignIn.tsx` | Seat grid; email-code or password sign-in |
| `web/buyer/src/lib/seatmap.ts` (+ `.test.ts`), `api.ts`, `cognito.ts` | Pure logic; API client; Cognito client |
| `services/booking-api/app/main.py`, `tests/test_cors.py` | CORS from configured origins only |
| `deploy/helm/booking-api/…` | `CORS_ALLOW_ORIGINS` |
| `.github/workflows/ci.yml` | `buyer-web` job |

## 3. How it works

**"Static" but dynamic.** The page is HTML and JavaScript files, with no server code. In the
browser, the JavaScript signs in to Cognito, then calls the booking API every 2 seconds for the
seat map and once to hold seats. On sale day, the page loads come from the CloudFront cache and
only real API calls reach the cluster.

**CORS.** A browser only lets a page call another origin (here `localhost:3000` calling
`localhost:18080`) if that origin agrees. Before the real request, the browser sends a *preflight*
(`OPTIONS`), and the API answers "yes, `http://localhost:3000` may call me". Any other site gets
400 and no permission header. Behind CloudFront (later), page and API share one origin, so the list
can be empty.

**Safe testing without CloudFront.** The ALB still accepts only CloudFront. For testing, the API is
reached through `kubectl port-forward`: an encrypted tunnel from the laptop to the service, using
your AWS credentials. Tokens never travel over the open internet unencrypted.

## 4. Errors I hit and how I fixed them

| # | Error (exact message) | Cause | Fix |
| --- | --- | --- | --- |
| 1 | `npm warn allow-scripts   @parcel/watcher@2.6.0 (install: node scripts/build-from-source.js)` | npm's allow-scripts protection skipped an install script that isn't approved | Left it unapproved. The build and dev server work with the prebuilt binaries, so nothing extra runs |
| 2 | ESLint: `Error: Calling setState synchronously within an effect can trigger cascading renders` (×2); `Do not use an <a> element to navigate to /. Use <Link />`; warnings `Do not use window.location.href …`, `Assign object to a variable before exporting as module default` (×2) | React 19's hook rules, and Next's link rules | Token read in a lazy `useState` initializer (this page renders only in the browser); first refresh via `setTimeout`; `next/link` and `router.push`; named config exports. Lint is clean |
| 3 | I first wrote `actions/setup-node@49933ea… # v4.4.0` from memory | A pinned action SHA must be real | Resolved the latest release (v7.1.0) to commit `949feb24…` through the GitHub API |
| 4 | `next dev` created an untracked `web/buyer/AGENTS.md` | Next 16 writes a notice for coding agents | Not committed; added to `web/buyer/.gitignore` |

## 5. How I verified it works

| Check | Result |
| --- | --- |
| Unit tests | 9 passed: natural row order, toggle add/remove, no taken seats, limit, prune taken seats, totals and ₹ formatting, zone order, countdown |
| Lint / typecheck / build | clean / ok / static `/` and `/event` |
| API tests | 82 passed (CORS: allowed origin gets `access-control-allow-origin`, no credentials header; `https://evil.example` → 400) |
| CI (#25) | 4 checks green, including `buyer web (lint + typecheck + jest + static build)` |
| Deployed | `cfabad73ec59`, `CORS_ALLOW_ORIGINS=http://localhost:3000` |
| App served locally | `/` → 200 "Find your event"; `/event/` → 200 |
| **The page's requests, replayed against dev** | (1) organiser A created *M2 Demo Night* + 96-seat map (`201`, `200`); (2) buyer-1 signed in with the **buyer-web** client, `USER_AUTH` + password, as `cognito.ts` does; (3) preflight and seat-map `GET` with `Origin: http://localhost:3000` → `200`, 96 seats, `ACAO=http://localhost:3000`; (4) hold A-1-5 and A-1-6 → `201`, ₹3,000, expires in 10 min; (5) a second signed-in viewer **0.40 s later** sees A-1-5 and A-1-6 `held`, A-1-4 `available`; (6) preflight from `https://evil.example` → `400`, no ACAO |
| Browser click-through | Not done by me: no browser tool in this session. Steps in `phase-2-milestone.md` |

## 6. Cost impact

None: the app runs on the laptop, and CORS is config only.

## 7. Interview notes

- **Q:** Why is the buyer site a static export if it shows live seat data?
  **A:** "Static" is about delivery, not behaviour. The files come from a CDN cache, so 50,000 page
  loads at 12:00 never reach a server; the browser then calls the APIs for the live seat map and
  holds. Server rendering would put every page load on EKS at the worst moment.
- **Q:** How did you test the frontend without exposing anything?
  **A:** The app ran locally and reached the API over `kubectl port-forward`, an authenticated
  tunnel. The ALB stayed locked to CloudFront, and the API's CORS allows only `localhost:3000`.
- **Q:** What stops someone picking more seats than allowed in the browser?
  **A:** The browser only stops obvious mistakes. The server enforces the per-buyer limit inside the
  hold transaction, with an advisory lock, and that was proven with 20 parallel requests from one
  buyer.

## 8. Next task

Day 5 (Mon 23 Nov) — Phase 3, waiting room. Per your note: API Gateway, Lambda, SQS and DynamoDB
first; the CloudFront pieces last.
