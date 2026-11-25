# Week 2 · Day 9 Task 2 — WAF on CloudFront (and the queue API)

- **Date:** 2026-11-25
- **Phase / milestone:** Phase 5 → M5
- **Status:** Done on dev. Your Chrome check of a real join is still open (I can't run a
  browser that solves the challenge). Demo gets the same ACL at the Day 10 apply.
- **Commit / PR:** [#62](https://github.com/sheshagiri-62/surgegate/pull/62) (WAF, origin
  header, buyer site), [#63](https://github.com/sheshagiri-62/surgegate/pull/63) (header
  required by default; this report)

## 1. What the task was

Plan, Day 9 Task 2: *"WAF on CloudFront and API Gateway: rate rules, managed bot rules on
`/queue/*`, challenge before join."*
- From the Day 7 note: `/webhooks/*` must never be challenged.
- Your conditions:
  - an off-by-default ALLOW rule for the load generators;
  - proofs: a burst gets rate-limited, a plain curl to join gets challenged, webhooks are never
    challenged;
  - confirm the buyer site uses CloudFront for `/queue/*` before the Lambdas require the header;
  - exact prices before applying.

## 2. What I did, step by step

1. **Checked the buyer site first.** All 9 deployed JavaScript files contain **0** references to
   `execute-api`. The one that calls `/queue/` uses a relative path, so it goes through
   CloudFront. `.env.example` was the only other place pointing at `execute-api`; it now points
   at CloudFront.
2. **Prices** from the AWS Price List API (global / CloudFront; fixed fees pro rata by the hour):

   | Item | Price |
   | --- | --- |
   | Web ACL | $5.00 / month |
   | Rule or rule group | $1.00 / month each |
   | Requests (ACL < 1,500 WCU; ours is 833 WCU) | $0.60 / million |
   | Bot Control, common level | $10.00 / month; requests: first 10 M a month free, then $1.00 / M |
   | Challenges served | $0.40 / million |

3. **`infra/modules/waf`** (CLOUDFRONT scope, so in us-east-1). Rules in priority order; the first
   terminating action wins:

   | # | Rule | What it does |
   | --- | --- | --- |
   | 0 | AllowLoadGenerators | IP set of the k6 machines → Allow. **Exists only with `waf_load_test_enabled=true`** |
   | 1 | AllowWebhooks | `/webhooks/*` → Allow (HMAC-authenticated, never challenged or rate-limited) |
   | 2 | IpReputation | AWS managed list of known bad IPs |
   | 3 | RateLimitAll | > 2,000 requests per IP per 5 min → 429 |
   | 4 | RateLimitJoin | > 30 joins per IP per minute → 429 (generous: Indian mobile carriers put many users behind one IP) |
   | 5 | ChallengePage | GET `/waiting/*` → Challenge (the browser solves it and gets the `aws-waf-token` cookie) |
   | 6 | ChallengeJoin | POST `/queue/<event>/join` → Challenge (passes with the token) |
   | 7 | BotControl | AWS managed, common level, **scoped down to `/queue/*`** |
   | 8 | CommonRuleSet | AWS managed; the 8 KB body rule only counts (seat-map CSV uploads) |

   Logs go to `aws-waf-logs-surgegate-dev` (7 days) and keep **only** BLOCK, CHALLENGE and COUNT,
   so a 50k test doesn't write gigabytes.
4. **WAF can't attach to an API Gateway HTTP API** (only to REST APIs), so the queue API is
   protected another way. CloudFront now adds the same secret origin header it sends to the ALB.
   The four public queue Lambdas (join, position, admit, serving) refuse requests without it,
   behind `queue_origin_verify_required`. A request straight to `execute-api` would skip WAF;
   now it gets a 403.
5. **Buyer site:** joins detect a WAF challenge (it's also a `202`, so the client checks the
   `x-amzn-waf-action` header). There's also a `challenge.js` helper, which is a no-op for now
   (see error 2).
6. Applied in steps: the ACL (7 rules) → the `ChallengePage` rule (approved separately: +$1/month)
   → merged #62 (buyer site rebuilt) → proofs → the origin-header requirement on.

### Commands I ran

```bash
# 1. buyer site: any execute-api in the deployed bundles?
for p in / /waiting/; do curl -s $CF$p | grep -o '/_next/static/[^"]*\.js'; done | sort -u   # 9 files
# ... curl each, grep execute-api -> 0, /queue/ -> 1 (relative)

# 2. prices: Price List API, ServiceCode=awswaf (all 2,586 price items, global ones kept)

# 3-6. build, plan, apply
cd services/queue && pytest -q                                  # 57 passed (4 new)
cd web/buyer && npm run lint && npx tsc --noEmit && npm test    # 26 passed (2 new)
terraform fmt -recursive infra && terraform -chdir=infra/envs/dev validate
terraform -chdir=infra/envs/dev plan <up vars> -out=waf.tfplan  # 4 add, 10 change, 0 destroy
terraform -chdir=infra/envs/dev apply waf.tfplan                # 4 added, 8 changed
terraform -chdir=infra/envs/dev plan <up vars> -out=waf2.tfplan # ChallengePage: 0/1/0
terraform -chdir=infra/envs/dev apply waf2.tfplan
gh pr merge 62 --squash --delete-branch                         # buyer site redeployed
terraform -chdir=infra/envs/dev plan <up vars> -out=origin.tfplan   # ORIGIN_VERIFY_REQUIRED true (7 Lambdas)
terraform -chdir=infra/envs/dev apply origin.tfplan

# proofs (plain curl from the laptop)
curl -s -o /dev/null -D - "$CF/waiting/?id=$EV"            # 202, x-amzn-waf-action: challenge
curl -s -o /dev/null -D - -X POST "$CF/queue/$EV/join"     # 202, x-amzn-waf-action: challenge
curl -s -o /dev/null -D - -X POST -d '{}' "$CF/webhooks/razorpay"   # 400 from uvicorn
for i in $(seq 1 240); do curl -X POST "$CF/queue/$EV/join"; sleep 0.3; done   # 429 from request 52
curl -A "<Chrome UA>" "$CF/queue/$EV/serving"   # 200 (through CloudFront, header added)
curl "$API/queue/$EV/serving"                   # 403 straight to execute-api
```

### Files created or changed

| File | What it does |
| --- | --- |
| `infra/modules/waf/*` | Web ACL (9 rules), IP set, join regex set, logging |
| `infra/modules/edge/main.tf`, `variables.tf` | `web_acl_id`; origin header on the queue origin |
| `infra/modules/queue/main.tf`, `variables.tf` | Header name/secret/required → Lambda env |
| `infra/envs/{dev,demo}/main.tf`, `variables.tf`, `outputs.tf` | WAF module (us-east-1 provider), switches |
| `services/queue/src/sg_queue/common.py` (+ join/position/admit/serving) | `edge_only` check |
| `services/queue/tests/test_edge_only.py` | 4 tests |
| `web/buyer/src/lib/waf.ts`, `queue.ts`, `waf.test.ts`, `.env.example` | Challenge detection, optional SDK, tests |
| `.github/workflows/build-deploy-buyer.yml` | `NEXT_PUBLIC_WAF_SDK_URL` (empty today) |

## 3. How it works

**A web application firewall** looks at every request at the CloudFront edge before it reaches
the cache or our origins, and runs it through an ordered list of rules. Each rule can **Allow**
(stop checking, let it through), **Block** (answer with an error, here 429 or 403), **Challenge**
(answer with a small page that makes a real browser do a short computation and stores a token
cookie), or only **Count**.

- **Rate rules** count requests per client IP over a rolling window and block an IP once it goes
  over the limit, until it calms down.
- **Managed rule groups** (IP reputation, common exploits, bots) are lists AWS keeps up to date.
- **Bot Control's common level** recognises self-identifying automation (curl, scripting
  libraries, crawlers) by its signatures.

**Challenge before join, in SurgeGate:**
1. A buyer's browser opens `/waiting/?id=…`.
2. WAF challenges that page load; the browser solves it in about a second and gets the
   `aws-waf-token` cookie for our domain (valid 30 minutes).
3. The page's `fetch()` to join sends the cookie, so `ChallengeJoin` lets it through.
4. A script that POSTs straight to join has no token and gets the challenge page instead. It
   can't join.

This makes a scripted mass-join expensive, which keeps the waiting room fair.

**The direct-API hole and how it's closed:** API Gateway also has its own public URL
(`execute-api`), which WAF on CloudFront never sees. CloudFront now adds a secret header on the
way to API Gateway, and the queue Lambdas reject any request that doesn't carry it. That's the
same pattern as the ALB, where the origin-verify header lets only our CloudFront in.

**Load tests:** k6 can't solve challenges and looks like a bot. For the Day 10 window only, rule
0 allows the load generators' IPs past everything else, and it's switched off again afterwards.
k6 must also call the CloudFront URL (`QUEUE_API=https://<distribution>`), never `execute-api`.

## 4. Errors I hit and how I fixed them

| # | Error (exact message) | Cause | Fix |
| --- | --- | --- | --- |
| 1 | tflint: `"POST /queue/<event id>/join" does not match valid pattern ^[\w+=:#@/\-,\.][\w+=:#@/\-,\.\s]+[\w+=:#@/\-,\.]$` (and the same for the ACL description) + 2 version-constraint warnings | WAF descriptions can't contain `< > ( )` | Plain-text descriptions (also the IP set's, which tflint doesn't check); `required_version` + `version` in `versions.tf` |
| 2 | `terraform output waf_challenge_sdk_url` = `challenge.js` (no host); `curl` → `000` | AWS issues an SDK integration URL **only** for ATP, ACFP or Bot Control TARGETED; ours is COMMON, so `application_integration_url` is empty (`GetWebACL`: no `ApplicationIntegrationURL`). I had set the repo variable to the bad value | Deleted the variable. New rule `ChallengePage` challenges the page load, so the browser gets the token without the SDK (approved: +$1/month). The output is now `null` when there's no URL |
| 3 | During that gap, browser joins were challenged and failed | ChallengeJoin was live before the browser had a way to get a token | Closed by error 2's fix about 20 minutes later (dev only) |
| 4 | `Permission for this action was denied … [Destructive or Unwanted Actions]` (apply of the extra rule) | It changed the approved cost, so it needed its own yes | Asked you; applied after your yes |
| 5 | `Permission … denied` on `gh pr merge 63` | Merges need your OK | #63 is waiting for you |
| 6 | ruff `I001 Import block is un-sorted` ×3 | `edge_only` added at the front of the imports | `ruff check --fix` |
| 7 | `pull request create failed: GraphQL: No commits between main and feat/waf` | The first commit had failed on tflint (error 1) | Committed after the fix → #62 |

## 5. How I verified it works

| Check | Result |
| --- | --- |
| Plain curl GET `/waiting/?id=…` | `202`, `x-amzn-waf-action: challenge` |
| Plain curl POST `/queue/<event>/join` | `202`, `x-amzn-waf-action: challenge` |
| POST `/webhooks/razorpay` (no signature) | `400` from **uvicorn**: reached the app, no challenge |
| Burst: POST join every ~0.3 s from the laptop | Requests 1–51 `202` (challenged), **from request 52 (42 s) `429`**, 15 × 429 in a row |
| **Webhook while that IP was rate-limited** | `400` from uvicorn: still not challenged or blocked |
| Curl GET `/queue/<event>/serving` | `403` (Bot Control: HTTP library); a browser User-Agent gets `200` |
| Home page | `200` from S3 (not challenged) |
| Through CloudFront after the header became required | `200` (the header is added by CloudFront) |
| Straight to `execute-api`: serving / join / position (join and position with a valid buyer token) | `403 "use the site's address, not the API's"` |
| WAF logs (us-east-1) | ChallengeJoin 52, RateLimitJoin 16, ChallengePage 3, BotControl 1; **no `/webhooks` entry at all** |
| ACL capacity | **833 WCU** (< 1,500, so the $0.60/M request price) |

**Still for you:** open `https://d1t9vww2xtyvsz.cloudfront.net/waiting/?id=<event>` in Chrome,
sign in, and join. You should briefly see "verifying…" and then your place in the queue.

## 6. Cost impact

- **Dev web ACL:** $5 + 8 rules × $1 + Bot Control $10 = **$23/month, about $0.032/h, about
  $0.76/day**, so about $4.30 if kept to 30 Nov. Requests: $0.60 per million (dev traffic: cents).
- **Day 10 load tests** (demo ACL):
  - requests: about 26 requests per user → 0.26 M + 1.3 M ≈ **$0.94**;
  - Bot Control requests: **$0** (k6 traffic is allowed at rule 0 and never reaches Bot Control;
    even if it did, it's under the 10 M free allowance);
  - fixed fees for a ~10-hour window: **about $0.32**;
  - **total ≈ $1.25**.
- **Teardown:** `-var=enable_waf=false` and apply (removes the ACL, so the fixed fees stop).

## 7. Interview notes

- **Q:** Why a challenge instead of a CAPTCHA before join?
  **A:** A challenge is invisible to a real browser: about a second of JavaScript work, no
  puzzle. It still stops scripts that don't run a browser. CAPTCHA costs $0.40 per 1,000
  attempts and annoys 50,000 real fans; a challenge costs $0.40 per **million**. You'd add CAPTCHA
  only for traffic that already looks suspicious.
- **Q:** WAF can't be attached to an HTTP API. How did you stop people bypassing CloudFront?
  **A:** CloudFront adds a secret header on its origin request, and the queue Lambdas compare it
  in constant time (`hmac.compare_digest`). Without it they answer 403, so the `execute-api` URL
  is useless on its own. It's the same "origin verify" pattern as in front of the ALB.
- **Q:** How do you load-test through a WAF that blocks bots?
  **A:** An Allow rule with the load generators' IP set at the highest priority. It's off by
  default and switched on only for the test window, so the test measures the system, not the
  bot rules. WAF itself is proven separately with a laptop burst, a challenged curl, and webhooks
  passing.

## 8. Next task

Day 9 Task 3: observability (structured logs, a CloudWatch "sale room" dashboard, Container
Insights, X-Ray through OpenTelemetry).
