# Week 1 · Day 5 · Task 04 — `serving` endpoint (5-second CloudFront cache pending CloudFront verification)

- **Date:** 2026-11-21 (evening of Day 3)
- **Phase / milestone:** Phase 3 (Waiting room) → M3
- **Status:** Done for API Gateway. **The CloudFront 5-second cache is pending CloudFront
  verification**: written, plan-checked, behind `enable_cloudfront` (not created).
- **Commit / PR:** see the Day 5 summary (`feat/queue-serving`)

## 1. What the task was

Plan text: *"`serving` endpoint behind CloudFront with a 5-second cache."* Your change for
tonight: serve it directly from API Gateway (no cache), keep the 5-second CloudFront behaviour as a
pending change behind `enable_cloudfront`, and **don't** enable API Gateway caching (it bills
hourly).

## 2. What I did, step by step

1. **`GET /queue/{event}/serving`** (`sg_queue/serving.py`):
   - returns `event_id`, `status`, `serving_up_to`, `admission_rate` (0 while paused) and
     `sale_starts_at`;
   - **public, no sign-in**: it's one number, the same for everyone, and nothing personal is in it;
   - sends **`Cache-Control: public, max-age=5`** (404s are cacheable too, 10–60 s);
   - the queue state is cached **2 s inside the function**.
2. **Route without the JWT authorizer.** The routes map now has `auth` per route
   (`serving = false`); join and position still require a token.
3. **Pending CloudFront verification** (in `infra/modules/edge`, all created only when
   `enable_cloudfront = true`):
   - cache policy `surgegate-dev-queue-serving-5s` (min 0, default 5, max 5 s; no headers,
     cookies or query strings in the key);
   - a second origin `queue`, API Gateway over HTTPS only;
   - an ordered behaviour **`/queue/*/serving`, cached 5 s**;
   - an ordered behaviour **`/queue/*`, not cached**, forwarding `Authorization`. The site and the
     queue then share one origin, so no CORS is needed.
   - dev passes `queue_api_domain` from the queue module.
4. **No API Gateway cache:** HTTP APIs don't have one, and the REST API cache bills by the hour.

### Commands I ran

```bash
git checkout -b feat/queue-serving feat/queue-position
pytest -q                                                    # 36 passed
terraform validate && tflint (queue, edge)
terraform -chdir=infra/envs/dev plan … -out=serving.tfplan   # 7 add, 9 change, no CloudFront
terraform -chdir=infra/envs/dev plan … -var=enable_cloudfront=true   # PLAN ONLY: cache policy + 2 behaviours compose
terraform -chdir=infra/envs/dev apply serving.tfplan          # approved: 7 added, 4 changed
curl -D - $API/queue/<event>/serving                          # no token
for i in 1..20: curl -w '%{time_total}' …                     # latency
```

### Files created or changed

| File | What it does |
| --- | --- |
| `services/queue/src/sg_queue/serving.py` | The endpoint |
| `services/queue/tests/test_serving.py` | 4 tests |
| `infra/modules/queue/main.tf` | serving Lambda + role; routes with per-route auth |
| `infra/modules/edge/main.tf`, `variables.tf` | **Pending:** 5 s cache policy, queue origin, `/queue/*/serving` and `/queue/*` behaviours |
| `infra/envs/dev/main.tf` | `queue_api_domain` → edge |

## 3. How it works

With 50,000 people waiting and each browser checking every 10 seconds, that's 5,000 requests a
second, all asking the same question: "who is being served now?". The answer is the same for
everyone, so it doesn't need to be computed per person. With CloudFront in front, the first request
in each 5-second window goes to the Lambda and every other one gets the cached copy from the
nearest edge location, so 5,000 polls a second become roughly one origin call per edge location
every 5 seconds.

Until CloudFront is verified, every poll reaches the Lambda. Two things keep that cheap:
- the function keeps the state in memory for 2 seconds, so DynamoDB is barely touched;
- the stage throttle caps total requests.

The browser still honours `max-age=5`.

## 4. Errors I hit and how I fixed them

None.

## 5. How I verified it works

| Check | Result |
| --- | --- |
| Tests | 36 passed (4 new): public and `Cache-Control: public, max-age=5`, nothing personal in the body; paused → rate 0; in-function cache 2 s; unknown or bad event 404 |
| Apply | 7 added, 4 changed, 0 destroyed |
| AWS, no token | `200`, `{"status": "open", "serving_up_to": 0, "admission_rate": 125, …}`, header `cache-control: public, max-age=5` |
| Latency from the laptop (20 polls) | mostly 0.11–0.35 s (one 0.89 s) |
| Unknown event | `404 no waiting room for this event` |
| CloudFront part, plan only | `aws_cloudfront_cache_policy.serving` with `default_ttl = 5`; behaviours `/queue/*/serving` and `/queue/*` → origin `queue`. **Live 5-second caching check: pending CloudFront verification** |

## 6. Cost impact

Per request only, nothing hourly: about $1.3 per million API calls, plus Lambda within the free
tier. No API Gateway cache. The CloudFront cache will cut these calls further once enabled.

## 7. Interview notes

- **Q:** How do 50,000 browsers poll a counter without melting your backend?
  **A:** The counter is identical for everyone, so it's public and cacheable. CloudFront caches it
  for 5 seconds, turning thousands of polls a second into a handful of origin calls. Behind that,
  the function caches the state for 2 s, so DynamoDB is barely touched.
- **Q:** Why not use API Gateway's own cache?
  **A:** HTTP APIs don't have one, and the REST API cache bills per hour per size even when idle.
  CloudFront caching is pay-per-request and closer to the user.
- **Q:** Why is this endpoint public when the others need sign-in?
  **A:** It holds nothing personal, and a shared cache can only work if responses don't depend on
  who's asking. The personal data (position, token) is behind sign-in on `/position`.

## 8. Next task

Day 6 Task 1 — `valve` Lambda on EventBridge Scheduler raising "serving N" by the admission rate;
pause and resume.
