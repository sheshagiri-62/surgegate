# Week 2 · Day 10 Task 1 — Pre-scaling 15 minutes before a sale + backpressure

- **Date:** 2026-11-25
- **Phase / milestone:** Phase 5 → M5
- **Status:** Done (both proven live on dev)
- **Commit / PR:** [#67](https://github.com/sheshagiri-62/surgegate/pull/67)

## 1. What the task was

Plan, Day 10 Task 1: *"Pre-scaling job 15 minutes before a sale; backpressure Lambda lowering the
admission rate when p95 > 500 ms."* Autoscaling reacts after the load arrives, which is too late
for a crowd that lands at exactly 12:00. So SurgeGate scales **before** the sale and slows the
queue **during** it.

## 2. What I did, step by step

1. **metrics-server** (EKS add-on), so the cluster has CPU numbers.
2. **HPA** for the booking API (CPU 60%, dev 2–4 pods; quick to scale up, 5 minutes to scale
   down). With the HPA on, the Deployment no longer sets `replicas`, and Argo CD **ignores the
   HPA's `minReplicas`** (`ignoreDifferences` + `RespectIgnoreDifferences`), because the
   pre-scaler owns that field.
3. **Pre-scaler**: a CronJob running every minute, `python -m app.prescale`, using the booking
   API's image.
   - If a sale starts within 15 minutes or started less than 60 minutes ago, it sets the HPA
     `minReplicas` to `prescale.minReplicas` (dev 3); otherwise to the base (2).
   - It has its own service account, with Pod Identity to **read** events from the database
     (IAM role `surgegate-dev-prescaler`), and RBAC to **get/patch only the `booking-api` HPA**.
4. **Backpressure Lambda** (`sg_queue.backpressure`, EventBridge Scheduler, every minute).
   - It reads the booking API's ALB metrics for the last full minute: p95, requests, 5xx.
   - **Unhealthy** (p95 > 0.5 s or 5xx > 1%): each open sale's rate × 0.7, with a floor of 20.
   - **Healthy** (p95 < 0.3 s and 5xx < 0.5%) or **idle** (< 20 requests a minute): rate × 1.2 + 1,
     up to `max_admission_rate`.
   - In between it holds; with no ALB (environment down) it does nothing.
   - Every update is conditional on the old value, so an organiser's change at the same moment
     wins.
5. **The booking API stores the organiser's rate as `max_admission_rate`** (when the room opens
   or the rate is changed): backpressure never admits faster than the organiser chose.
6. `backpressure_slow_p95` variable (0.5 s = the SLO), used only to run the live test below
   without touching code or the console.

### Commands I ran

```bash
cd services/queue && pytest -q          # 67 passed (10 new)
cd services/booking-api && pytest -q    # unit 53 passed; DB tests in CI (green)
helm lint deploy/helm/booking-api && helm template t deploy/helm/booking-api
terraform -chdir=infra/envs/dev plan <up vars> -out=bp.tfplan     # 9 add, 15 change, 0 destroy
terraform -chdir=infra/envs/dev apply bp.tfplan                   # 9 added, 8 changed
kubectl top nodes                                                 # metrics-server works
gh pr merge 67 --squash --delete-branch                           # image 700b2c2a7641
# proof 1: POST /org/events with sale_starts_at = now + 10 min, then watch the HPA
kubectl -n booking get hpa booking-api -o jsonpath='{.spec.minReplicas}'
# proof 2
terraform -chdir=infra/envs/dev plan <up vars> -var=backpressure_slow_p95=0.001 -out=bptest.tfplan && terraform apply bptest.tfplan
for i in $(seq 1 240); do curl -s -o /dev/null "$CF/org/events"; sleep 1; done
aws dynamodb get-item --table-name surgegate-dev-queue --key '{"PK":{"S":"EVENT#<m4>"},"SK":{"S":"META"}}'
terraform -chdir=infra/envs/dev plan <up vars> -out=bpback.tfplan && terraform apply bpback.tfplan    # back to 0.5
```

### Files created or changed

| File | What it does |
| --- | --- |
| `services/queue/src/sg_queue/backpressure.py`, `tests/test_backpressure.py` | The Lambda + 10 tests |
| `services/booking-api/app/prescale.py`, `tests/test_prescale.py` | The pre-scaler + tests (incl. the window query on Postgres) |
| `services/booking-api/app/queue_control.py`, `tests/test_queue_control.py` | `max_admission_rate` |
| `deploy/helm/booking-api/templates/hpa.yaml`, `prescale.yaml`, `deployment.yaml`, `values.yaml` | HPA, CronJob + RBAC, no `replicas` with the HPA |
| `deploy/argocd/booking-api.yaml` | `ignoreDifferences` on the HPA's `minReplicas` |
| `infra/modules/eks/main.tf` | metrics-server add-on |
| `infra/modules/queue/*`, `infra/envs/{dev,demo}/main.tf` | backpressure function, schedule, IAM, ALB suffixes, threshold |
| `infra/envs/{dev,demo}/prescaler.tf` | Pre-scaler IAM role + Pod Identity |

## 3. How it works

**Two control loops, before and during a sale.**
- **Before:** the pre-scaler looks at the calendar (`sale_starts_at`). 15 minutes before a sale
  it raises the minimum number of booking-API pods, so they are running and warm when the doors
  open. In demo, Karpenter adds the nodes those pods need. An hour after the start the minimum
  drops again, and the HPA scales down by itself.
- **During:** the backpressure Lambda looks at the booking API's health every minute. If it's
  slow, it lowers the **admission rate**, the number of people the waiting room lets in per
  minute. The waiting room gets longer instead of the booking API falling over. Once it recovers,
  the rate climbs back step by step, never above what the organiser set.

This is a **feedback loop** with a fixed ceiling and floor and gentle steps (−30%, +20%), so it
doesn't swing wildly. The trade-off is reaction time: CloudWatch publishes ALB metrics with about
1–2 minutes' delay, so the loop reacts in about 3 minutes (measured below). That's fine for
SurgeGate, because admitted buyers hold 15-minute passes, and the queue protects the database by
design.

## 4. Errors I hit and how I fixed them

| # | Error (exact message) | Cause | Fix |
| --- | --- | --- | --- |
| 1 | `E501 Line too long (102 > 100)` | Docstring | Wrapped |
| 2 | `AssertionError: assert 'unhealthy' == 'unknown'` (test) | My test called `booking_health` while it was still replaced by the stub | Kept a reference to the real function |
| 3 | `E501` ×2, `S310 Audit URL open for permitted schemes` | Long f-string / SQL; `urllib.request.Request` | Split the lines; `noqa: S310` with the reason (fixed https base, the in-cluster API server) |
| 4 | Error: metrics-server missing, `Metrics API not available` | EKS doesn't install it | metrics-server EKS add-on |
| 5 | CI `plan (infra/envs/demo)`: `Error in function call … coalesce(var.booking_alb_arn_suffix, "") … var.booking_alb_arn_suffix is null` | `coalesce` skips empty strings, so `coalesce(null, "")` is an error. Dev passed only because its ALB exists: **`make down` would have failed** | `var.x == null ? "" : var.x`; demo plan 228 to add, dev No changes |
| 6 | Pre-scaler job: `/usr/local/bin/python: No module named app.prescale` (2 runs) | Argo CD created the CronJob on its first sync, with the old image, before CI's tag-bump commit | Fixed itself on the next sync (image `700b2c2a7641`); the next run completed |

## 5. How I verified it works

**Pre-scaling (live):**

| Time (UTC) | What |
| --- | --- |
| 15:41:25 | Event "Prescale test" created, sale at **15:51:25** |
| 15:42:06 | Pre-scaler: `sales_in_window: [Prescale test]`, HPA `minReplicas 2 → 3` |
| 15:42:13 | **3 booking-api pods ready**, 9 minutes before the sale |
| later | `minReplicas` still 3 and Argo CD **Synced / Healthy** (it didn't "heal" the field back) |

**Backpressure (live, test threshold 0.001 s, ~40 requests/min to the booking API):** event "M4
demo", organiser rate 250.

| Time (UTC) | State | p95 | Requests/min | Rate |
| --- | --- | --- | --- | --- |
| 15:46:34 | unhealthy | 0.003 s | 41 | **250 → 175** |
| 15:47:34 | unhealthy | 0.004 s | 42 | **175 → 122** |
| 15:48:34 | unhealthy | 0.005 s | 26 | 122 → 85 (the threshold went back to 0.5 s at 15:48:41) |
| 15:49:35 → 15:54:34 | idle | — | 0 | 85 → 103 → 125 → 151 → 183 → 221 → **250** (capped at the organiser's rate) |

The traffic began at 15:43:35 and the first step came at 15:46:34: **a reaction time of about
3 minutes** (CloudWatch metric delay plus "last full minute"). Recovery to the full rate took
6 minutes.

## 6. Cost impact

No hourly resources.
- Backpressure Lambda: 1 run/minute, free tier.
- `GetMetricData`: 3 metrics/minute × $0.01 per 1,000 ≈ **$0.04/day**.
- metrics-server and the pre-scaler: small pods on the existing nodes.
- In demo, pre-scaling adds real pods and Karpenter nodes **only around a sale**.

## 7. Interview notes

- **Q:** Why pre-scale instead of relying on the HPA?
  **A:** An HPA needs a minute or two of high CPU to notice, then pods need time to start, and in
  a flash sale everyone arrives in the first seconds. We know the start time, so the pre-scaler
  raises the floor 15 minutes early. The HPA still handles anything above that.
- **Q:** What stops backpressure from fighting the organiser?
  **A:** The organiser's rate is stored as `max_admission_rate`, a ceiling backpressure never
  exceeds. Every backpressure write is conditional on the value it read, so if the organiser
  changes the rate in the same second, their change wins.
- **Q:** What's the weakness of this loop?
  **A:** Reaction time: about 3 minutes, because ALB metrics reach CloudWatch with a delay. To
  make it faster, the booking API could publish its own latency (high-resolution metrics or
  EMF), or the valve could read a Redis counter. For SurgeGate it's acceptable, because the queue
  already limits load and admitted buyers have 15-minute passes.

## 8. Next task

Day 10 Task 2: Argo Rollouts canary for the booking API, with automatic rollback on error rate
(broken-release test).
