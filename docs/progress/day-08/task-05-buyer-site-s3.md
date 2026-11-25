# Week 2 · Day 8 Task 5 (added) — Buyer site on S3 behind the same CloudFront

- **Date:** 2026-11-25
- **Phase / milestone:** Phase 4 (carry-over from the blueprint: "static buyer site"); M3 re-checked
- **Status:** Done
- **Commit / PR:** [#60](https://github.com/sheshagiri-62/surgegate/pull/60)

## 1. What the task was

You asked for this one; it isn't a separate line in the plan. The blueprint's buyer site is a
static export served from S3 + CloudFront, so that 50,000 page loads at sale time never reach a
server. Until today it only ran on `localhost:3000`. Your conditions:
- rename the buyer `/queue/` page (it clashed with the API Gateway `/queue/*` behaviour);
- a CloudFront Function rewriting `/x/` → `/x/index.html`;
- the booking-pass function stays on `/book/*`;
- add the site's origin to the callback/CORS allow-lists;
- re-run the M3 edge check afterwards.

## 2. What I did, step by step

1. **Edge module** (`infra/modules/edge/site.tf`):
   - a private S3 bucket (public access blocked, SSE-S3, owner-enforced);
   - an origin access control, so only **this** distribution can read the bucket (bucket policy
     with `AWS:SourceArn`, plus deny-non-TLS);
   - the rewrite function;
   - the distribution's **default behaviour** now points at S3, with the CachingOptimized policy
     and the managed security-headers policy.
2. **Everything the ALB serves got its own behaviour** (`alb_path_patterns`): `/organiser`,
   `/organiser/*`, `/org/*`, `/me`, `/me/*`, `/orders/*`, `/webhooks/*`, `/healthz`,
   `/mockpay/checkout/*`. Caching is disabled, and all headers, cookies and query strings are
   forwarded. `/book/*` keeps the booking-pass function; `/queue/*` and `/queue/*/serving` stay
   on API Gateway.
3. **Buyer app:** `src/app/queue` → `src/app/waiting`, and the two links point to `/waiting/?id=`.
4. **Allow-lists:** the CloudFront origin was added to:
   - the checkout return URLs (booking API `ORDER_RETURN_ORIGINS`, mock-pay
     `CALLBACK_ALLOW_ORIGINS`);
   - the API's CORS list and the queue API's CORS list. The site is same-origin, so these are
     belt-and-braces; `localhost:3000` is kept for laptop work.
5. **CI:**
   - New bootstrap role `surgegate-gha-site-deploy`: main branch only; it can upload to that one
     bucket and invalidate that one distribution.
   - New workflow `build-deploy-buyer.yml`: lint → typecheck → jest → static export with
     same-origin API URLs → `s3 sync`. Hashed assets are cached for a year (`immutable`), pages
     for 60 s. It then invalidates the cache and smoke-tests through CloudFront.
   - The repo variable `AWS_SITE_DEPLOY_ROLE_ARN` was set.
6. Applied (after you approved): bootstrap 2 added / 1 changed; dev 7 added / 2 changed; 0
   destroyed. Merged #60, CI deployed the site, and Argo CD synced the allow-lists.

### Commands I ran

```bash
cd web/buyer && npm run lint && npm run typecheck && npm test   # 24 tests passed
NEXT_PUBLIC_API_BASE= NEXT_PUBLIC_QUEUE_API= NEXT_PUBLIC_COGNITO_CLIENT_ID=<buyer-web> npm run build
node -e "<run site_rewrite.js on / /event/ /event /waiting/ /_next/... /404.html>"
terraform fmt -recursive infra
terraform -chdir=infra/bootstrap validate && terraform -chdir=infra/bootstrap plan -out=site-boot.tfplan
terraform -chdir=infra/envs/dev validate && terraform -chdir=infra/envs/dev plan <up vars> -out=site-dev.tfplan
terraform -chdir=infra/bootstrap apply site-boot.tfplan      # 2 added, 1 changed, 0 destroyed
gh variable set AWS_SITE_DEPLOY_ROLE_ARN --body arn:aws:iam::968077439619:role/surgegate-gha-site-deploy
terraform -chdir=infra/envs/dev apply site-dev.tfplan        # 7 added, 2 changed, 0 destroyed
gh pr merge 60 --squash --delete-branch                      # build-deploy-buyer: success
kubectl -n argocd annotate application booking-api argocd.argoproj.io/refresh=normal --overwrite
kubectl -n argocd annotate application mock-pay argocd.argoproj.io/refresh=normal --overwrite
python site_edge_check.py                                    # FAILED CHECKS: 0
```

### Files created or changed

| File | What it does |
| --- | --- |
| `infra/modules/edge/site.tf` | Bucket, OAC, bucket policy, rewrite function, managed policies |
| `infra/modules/edge/functions/site_rewrite.js` | `/x/` and `/x` → `/x/index.html` |
| `infra/modules/edge/main.tf`, `variables.tf`, `outputs.tf` | S3 origin + default behaviour; `alb_path_patterns`; `buyer_site_enabled`; outputs |
| `infra/envs/dev/main.tf`, `outputs.tf` | Site on; the ALB path list; queue CORS; outputs |
| `infra/bootstrap/site_deploy.tf`, `iam.tf`, `variables.tf` | CI site-deploy role (and in the guardrail's protected list) |
| `.github/workflows/build-deploy-buyer.yml` | Build, upload with cache headers, invalidate, smoke test |
| `web/buyer/src/app/waiting/page.tsx` (renamed), `page.tsx`, `event/page.tsx` | `/queue/` page → `/waiting/` |
| `deploy/helm/booking-api/values.yaml`, `deploy/helm/mock-pay/values.yaml` | CloudFront origin in the allow-lists |

## 3. How it works

A static site is plain files: HTML, JavaScript and CSS made once at build time. S3 stores them,
and CloudFront serves them from edge locations near the buyer. After the first request each file
comes from the edge cache, so a sale's traffic spike for the pages never reaches AWS in Mumbai,
let alone our cluster.

**One distribution, two kinds of origin.** CloudFront matches the request path against its
behaviours in order: `/queue/*` goes to API Gateway, `/book/*` through the booking-pass function
to the ALB, the listed API and SSR paths to the ALB, and **everything else** to S3. The buyer's
browser only ever talks to `d1t9vww2xtyvsz.cloudfront.net`, so there's no CORS and one URL for
the demo. That shared path space is also why the page couldn't stay at `/queue/`: CloudFront
would have sent `/queue/?id=…` to API Gateway.

**Why the rewrite function:** with an origin access control, CloudFront reads S3 through the S3
API, which has no "index document" feature. A request for `/event/` would look for an object
literally named `event/`. The function changes the URI to `/event/index.html` before the cache
lookup. It runs at the edge in under a millisecond and is inside the free tier.

**Cache headers:** Next.js puts a content hash in every `/_next/static` file name, so those files
never change and can be cached for a year. Pages keep the same names, so they're cached for 60 s.
Each deploy also invalidates `/*` (one path, free).

**The site doesn't need dev to be up.** S3 isn't part of `make down`. While dev is down the pages
still load, and their API calls get the origin-down 503.

## 4. Errors I hit and how I fixed them

| # | Error (exact message) | Cause | Fix |
| --- | --- | --- | --- |
| 1 | `Type 'string' is not assignable to type 'never'` (`npm run typecheck`) | Stale generated route types in `.next/types` still listed the deleted `/queue` page | The next `npm run build` regenerated them; `tsc --noEmit` exit 0. CI starts clean, so it never sees this |
| 2 | `Permission for this action was denied … [Destructive or Unwanted Actions]` | I bundled `gh pr merge 59` (the docs PR, which you hadn't approved) with the approved #60 merge | Merged only #60; #59 waits for you |
| 3 | Allow-lists still `http://localhost:3000` in the pods after the merge | Argo CD hadn't polled the new commit yet (3-minute interval) | `argocd.argoproj.io/refresh=normal` on both apps; both pods restarted with the new env |
| 4 | Check "hashed asset": 2nd request `Miss from cloudfront` | An edge location runs many cache servers; the first requests can land on different ones | Not a bug: the 3rd and 4th were Hits, all from MAA51-P3. The check now looks for a Hit within 4 tries |
| 5 | Mock checkout `400` on `outcome=failure` | My script used the wrong value; mock-pay accepts `success` or `fail` | `outcome=fail` → `303` back to the site |

## 5. How I verified it works

`site_edge_check.py` through CloudFront, **0 failed checks**:

- **Pages from S3:** `/`, `/event/?id=…`, `/event` (no slash), `/waiting/?id=…`, `/order/`,
  `/tickets/` all return `200 text/html`, `Server: AmazonS3`, `Cache-Control: public,
  max-age=60`, with HSTS. Hashed assets: `max-age=31536000, immutable`, Hit. A missing page:
  `404`. `/waiting/` is the HTML page, not API Gateway.
- **ALB paths still reach the cluster** (`Server: uvicorn` / Next.js, never S3): `/healthz` 200,
  `/me` 401, `/me/tickets` 401, `/org/events` 401, `/orders/<id>` 401, `/webhooks/razorpay`
  without a signature 400, `/organiser/login` 200, `/organiser/events` without a session 307,
  `/mockpay/checkout/<unknown>` 404 from mock-pay.
- **M3 edge check (re-run):** `/book/*` with no pass, garbage, a forged signature or an expired
  pass → `403`, `X-Cache: FunctionGeneratedResponse` (refused at the edge). A valid pass for
  another user → passes the edge, then refused by the API (`403 … pass belongs to someone else`).
  A valid pass for the right user → `200`, 10 seats. `/queue/<event>/serving`: `Miss Hit Hit Miss
  Hit Miss` (cached 5 s). `/queue/…/position` without a token → `401` from API Gateway.
- **Checkout returns to the site:** an order with `return_url=https://d1t9vww2xtyvsz.cloudfront.net/order/`
  → `201`. Paying with "fail" on the mock checkout → `303` to `…cloudfront.net/order/…`, and
  that page is served from S3.

## 6. Cost impact

No hourly resources. S3: a few MB of files (well under $0.01/month) plus requests (CloudFront
caches most of them). CloudFront requests, data transfer and Functions are inside the always-free
tier (1 TB, 10 M requests, 2 M function invocations a month). Invalidations: one path per deploy,
inside the free 1,000 a month. To remove the site, set `buyer_site_enabled = false` and apply
(`force_destroy` empties the bucket). `make down` leaves it up on purpose.

## 7. Interview notes

- **Q:** Why serve the buyer site and the API from one CloudFront distribution?
  **A:** One origin for the browser: no CORS preflights, and cookies or tokens never cross
  origins. The waiting room's cached counter, the booking-pass check and the static pages are all
  at the edge, with one URL. Path-based behaviours send each request to the right backend (S3,
  API Gateway or the ALB).
- **Q:** How is the bucket protected if CloudFront serves it to everyone?
  **A:** The bucket is private and blocks all public access. Its policy allows reads only to the
  CloudFront service **for this one distribution** (`AWS:SourceArn`), signed with SigV4 through
  an origin access control. Nobody can read S3 directly; everyone goes through CloudFront, and
  with it WAF later.
- **Q:** How do you deploy without users seeing a half-old, half-new site?
  **A:** Hashed asset names: the new HTML points at new files that are uploaded first, and old
  files stay valid in caches. Pages expire in 60 s and are invalidated on deploy, and the old
  hashed files are deleted only after the new ones are in place.

## 8. Next task

Day 9 Task 1: build the `demo` environment (needs hourly cost, so it needs your yes first).
