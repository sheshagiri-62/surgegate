# Week 2 · Day 10 Task 2 — Argo Rollouts canary with automatic rollback

- **Date:** 2026-11-25
- **Phase / milestone:** Phase 5 → M5 ("a deliberately broken release rolls back on its own")
- **Status:** Done (proven live on dev)
- **Commit / PR:**
  - [#69](https://github.com/sheshagiri-62/surgegate/pull/69): Rollouts + analysis;
  - [#70](https://github.com/sheshagiri-62/surgegate/pull/70) / [#71](https://github.com/sheshagiri-62/surgegate/pull/71): the broken release and its revert;
  - [#72](https://github.com/sheshagiri-62/surgegate/pull/72): graceful shutdown, found by this test;
  - [#73](https://github.com/sheshagiri-62/surgegate/pull/73): permanent WAF IP set.

## 1. What the task was

Plan, Day 10 Task 2: *"Argo Rollouts canary for the booking API with automatic rollback on error
rate."* Your conditions:
- steady load during every rollout, so the analysis has data;
- no data or inconclusive counts as failure;
- allow for the ALB metric delay;
- record the time from bad merge to abort, the % of failed requests and the time to full rollback;
- then show a clean rollout passing.

## 2. What I did, step by step

1. **Argo Rollouts controller** (chart 2.43.12 = v1.10.2) through Terraform. Its Pod Identity
   allows **only `cloudwatch:GetMetricData`**, for the analysis.
2. **The booking API became a Rollout** with `workloadRef` to the existing Deployment. The
   Rollout takes over its pods, and the Deployment is scaled down only once the Rollout is ready.
   The HPA now targets the Rollout.
3. **Canary steps:** 25% → analysis → 50% → analysis → 100%. Traffic is split by pod count,
   because CloudFront → ALB → one target group serves stable and canary pods alike.
4. **AnalysisTemplate**, built on the target group's CloudWatch metrics:
   - checks: 5xx rate ≤ 2% and p95 ≤ 0.5 s;
   - **initial delay 3 min**, a **5-minute window of 1-minute points**, 3 measurements a step;
   - **no data = failure** (`len(values) > 0`, and fewer than 10 requests in a minute counts as
     100% errors);
   - **errors fail at once** (`consecutiveErrorLimit: 0`), with no inconclusive band;
   - 2 failed measurements abort.
5. **Broken-release switch:** `faultInjection.errorRate`, the `FAULT_ERROR_RATE` middleware. It
   fails that share of requests with 500 while **`/healthz` stays green**, so the pods pass their
   health checks and only the metric analysis can catch them. Default "0" (off).
6. **Steady load:** `tests/load/k6/steady.js`, 20 requests/s to `GET /me`, run as a **Job inside
   the cluster**. Its traffic leaves through the NAT gateway's Elastic IP, which is what the WAF
   load-test ALLOW rule holds.
7. Ran: a clean canary, the broken release, the revert, then the shutdown fix with two restarts.

### Commands I ran

```bash
terraform -chdir=infra/envs/dev plan <up vars> -out=ro.tfplan && terraform apply ro.tfplan   # controller: 5 added
terraform -chdir=infra/envs/dev plan <up vars> -var-file=loadtest.tfvars -out=lg.tfplan      # WAF allow rule: NAT EIP /32
kubectl -n loadtest apply -f k6-job.yaml                                    # grafana/k6:2.3.0, 20 rps, 50-58 min
gh pr merge 69 && gh pr merge 70 && gh pr merge 71 && gh pr merge 72
kubectl -n booking patch rollout booking-api --subresource=status --type=merge -p '{"status":{"abort":false}}'   # retry
kubectl -n booking patch rollout booking-api --type merge -p '{"spec":{"restartAt":"<now>"}}'                    # restart
kubectl -n booking get rollout,analysisrun; kubectl -n booking get analysisrun <name> -o json
# CloudWatch GetMetricData: RequestCount, HTTPCode_Target_5XX_Count, HTTPCode_ELB_5XX_Count per minute
terraform -chdir=infra/envs/dev plan <up vars> -out=lgoff.tfplan && terraform apply lgoff.tfplan   # allow rule off
```

### Files created or changed

| File | What it does |
| --- | --- |
| `infra/modules/eks/rollouts.tf`, `variables.tf` | Controller + Pod Identity |
| `deploy/helm/booking-api/templates/rollout.yaml`, `analysis.yaml`, `hpa.yaml`, `values.yaml` | Rollout, AnalysisTemplate, HPA → Rollout, `rollout.*`, `faultInjection.*` |
| `deploy/helm/booking-api/templates/deployment.yaml`, `services/booking-api/Dockerfile`, `deploy/argocd/booking-api.yaml` | preStop 15 s, grace 45 s, uvicorn graceful shutdown, ALB readiness gate (#72) |
| `services/booking-api/app/main.py`, `tests/test_fault_injection.py` | The fault switch (off by default) + tests |
| `tests/load/k6/steady.js` | Steady load (IPv4 only) |
| `infra/modules/waf/main.tf`, `infra/envs/dev/waf_moved.tf` | Load-generator IP set always present (#73) |

## 3. How it works

A **canary release** sends a small share of real traffic to the new version first and compares
how it behaves before giving it everything. If the error rate or latency goes past the limits,
the release is **aborted**: the canary pods are removed and the old (stable) version keeps all
the traffic. Nobody has to notice and press a button.

In SurgeGate:
1. A merge to `main` changes the image tag or values in Git, and Argo CD syncs it.
2. Argo Rollouts creates one canary pod (25%) next to the stable pods.
3. An **AnalysisRun** reads the booking API's ALB metrics in CloudWatch every minute, after a
   3-minute delay (ALB metrics arrive late).
4. Healthy → 50% → analysis → 100%. Unhealthy twice → abort.

Because "no data" counts as failure, a release can't sneak through when there's no traffic to
judge it by. This test proved that rule: it aborted a canary while WAF was blocking my load (see
the errors table).

## 4. Errors I hit and how I fixed them

| # | Error (exact message) | Cause | Fix |
| --- | --- | --- | --- |
| 1 | `pull request create failed: GraphQL: Something went wrong …` / `HTTP 502: 502 Bad Gateway` (×4) | GitHub "Partial System Outage" | Retried after it recovered (#69) |
| 2 | Canary aborted at 17:08: `Metric "error-rate-pct" assessed Failed due to failed (2) > failureLimit (1)`, values `[[100 100 100 100 0]]` | **The analysis was right**: the target group got 0 requests after 17:02:30 because WAF was blocking my load. The "no data = failure" rule worked | Found the WAF cause (rows 3–4), then retried the canary |
| 3 | k6 from the laptop: `429` on every request after ~100 s | WAF `RateLimitAll` (2,000 per 5 min per IP): the allow rule didn't match because the laptop **connects over IPv6** (CloudFront has AAAA) and the IP set is IPv4 | k6 `dns: { policy: 'onlyIPv4' }` |
| 4 | Still `429` (2,859 of 2,859) | The laptop's IPv4 **changes**: the IP set had `152.57.108.x`, WAF logs showed `152.57.102.x` (carrier-grade NAT) | k6 runs **inside the cluster**; traffic leaves via the NAT gateway's fixed EIP, which the allow rule now holds |
| 5 | `GoError: GetFileAttributesEx …\tests\load\k6\k6_token.txt: The system cannot find the file specified.` | k6 `open()` resolves relative to the script's folder | Absolute path (later: a Kubernetes Secret) |
| 6 | Plan with the allow rule from `main`: **5 to destroy** (the Rollouts controller) | #69 wasn't merged yet (the same stacking trap as Day 9) | Not applied; planned from #69's branch |
| 7 | `Error acquiring the state lock … PreconditionFailed` (bootstrap, CI) | A CI run cancelled mid-plan (by my next push) left a lock | With your OK: `terraform force-unlock 91ad0234-…`; CI re-run green |
| 8 | `Your session has expired. Please reauthenticate using 'aws login'.` | `aws login` expired at ~17:42 | You logged in again |
| 9 | **Finding:** 75 ALB **502/504** (0.13% of 60,000), 11–31 at **every pod scale-down** (17:02, 17:27, 17:32, 17:35, 17:39, 17:44) | Pods stopped serving at SIGTERM while the ALB still sent them traffic | #72: `preStop sleep 15`, grace 45 s, `--timeout-graceful-shutdown 20`, ALB readiness gate. Proof below |
| 10 | Removing the allow rule: `WAFAssociatedItemException: … your resource is being used by another resource` (×2) | Terraform deleted the IP set before the ACL dropped the rule | #73: the IP set always exists (empty when unused); later toggles: 0 destroys, no error |

## 5. How I verified it works

**Broken release** (#70: `errorRate 0.5`, steady 20 req/s):

| Time (UTC) | Event |
| --- | --- |
| 17:33:28 | Bad release merged |
| 17:35:30 | Canary pod ready (Argo CD's 1-minute poll + pod start) |
| **17:39:25** | **Aborted automatically**: `RolloutAborted: … Metric "error-rate-pct" assessed Failed due to failed (2) > failureLimit (1)` |
| **17:39:34** | **Full rollback**: no bad pods left, only stable pods serving |
| 17:40:52 → 17:42:19 | Revert (#71) merged → synced; Rollout back to Healthy on the stable version |

- **Merge to abort: 5 min 57 s** (3 min 55 s after the canary was ready: the 3-minute initial
  delay plus two failed measurements). **Abort to full rollback: 9 s.**
- **Failed requests while the canary was live (17:35–17:39): 619 of 6,000 = 10.3%** per the ALB
  (6.4% → 11.5% → 12.7% → 13.5% → 7.5% per minute). That matches one canary pod of four or five
  taking about 25% of the traffic and failing half of it.
- **The whole k6 run (17:17–18:07): 60,000 requests, 694 5xx = 1.15%** (619 from the bad canary,
  75 the shutdown finding).

**Clean rollouts:** the same canary process with good images, every analysis Successful:

| Release | Start → Healthy (UTC) | Analyses |
| --- | --- | --- |
| `b1994433d601` (Rollouts) | 17:21:45 → 17:32:21 | 2 × Successful |
| `#72` chart + `0786653c1406` (shutdown fix) | 19:30:23 → 19:41:38 | 3 × Successful |
| `0d42cf531222` (Alpine, Task 3) | 20:53:29 → 21:04:58 | 2 × Successful |

**Graceful shutdown (#72):** two full restarts (6 pod replacements) under 20 req/s, 19:42–19:50:
**10,800 requests, 0 target 5xx, 0 ALB 5xx.** The 35 ALB errors earlier in that run came only
from removing the last pods created before the fix (19:35, 19:41).

## 6. Cost impact

No hourly resources:
- the controller pod;
- `GetMetricData` during analyses (cents);
- the k6 Job on the existing nodes;
- NAT data processing on about 70 MB/h of test traffic (under $0.01);
- the WAF allow rule, $1/month pro rata, only during the test windows.

## 7. Interview notes

- **Q:** How does the canary know the new version is bad?
  **A:** An AnalysisRun reads the ALB's 5xx rate and p95 for the booking API from CloudWatch
  every minute (after a 3-minute delay for late metrics). Two failed checks abort the rollout,
  which removes the canary pods. Here a bad release that still passed its health checks was
  aborted 5 min 57 s after the merge, and fully rolled back 9 s later.
- **Q:** What if there's no traffic during a release?
  **A:** Then we can't tell if it's healthy, so it isn't promoted. No data counts as failure.
  That's why each release window needs steady synthetic traffic (k6 in the cluster, through the
  real edge). It also caught a real problem: WAF was blocking my load test.
- **Q:** What else did the test find?
  **A:** Every pod removal dropped 11–31 requests with ALB 502/504, because pods stopped before
  the ALB stopped sending to them. A 15 s `preStop` sleep, graceful uvicorn shutdown and the ALB
  readiness gate fixed it: 0 errors over two full restarts.

## 8. Next task

Day 10 Task 3: GuardDuty, Security Hub, CloudTrail; base image and HIGH gate.
