# Runbook: booking API slow or erroring

**Alarms that link here:**
- `surgegate-<env>-slo-booking-p95-latency` (p95 > 500 ms, 3 of 5 min);
- `surgegate-<env>-booking-5xx-rate` (> 1%);
- `surgegate-<env>-booking-no-healthy-targets`;
- `surgegate-<env>-rds-cpu-high`, `surgegate-<env>-rds-connections-high`.

**SLO at risk:** booking pages for admitted buyers answer within 500 ms at p95; seats can't be
held, so admitted buyers wait out their 15-minute pass.

## 1. First move: protect the database (1 minute)

**Lower the admission rate** on the organiser dashboard (for example 250 → 100 per minute). The
waiting room absorbs the crowd: buyers wait a little longer in the queue instead of timing out
on a slow seat map. This is the backpressure rule from the blueprint (automatic from Day 10).
Never "open the gates" to clear a backlog.

## 2. Check

1. **Dashboard** `surgegate-<env>-sale-room` → *Booking API*: latency p95/p99 vs the 0.5 s line,
   requests, 5xx, healthy targets. Then *Data*: RDS CPU and connections, Redis CPU and
   hits/misses. Then *Pods*: pod CPU.
2. **One slow request end to end:** X-Ray → Traces, filter `service("booking-api")` and
   `responsetime > 0.5`. Open a trace: the slow span is either the handler itself (CPU),
   DynamoDB/Kinesis/Secrets (boto calls) or Redis. Database time is the part of the request
   span not covered by any child span (no SQL spans: see Day 9 Task 3).
3. **Logs for that trace:** CloudWatch Logs Insights on `/aws/containerinsights/<cluster>/application`:
   ```
   fields @timestamp, kubernetes.pod_name, log_processed.message
   | filter log_processed.trace_id = "1-xxxxxxxx-xxxxxxxxxxxxxxxxxxxxxxxx"
   ```
   Or the dashboard's *Latest ERROR lines* table.
4. **Pods:** `kubectl -n booking get pods`, then `kubectl -n booking describe pod <pod>` (OOMKilled?
   readiness failing?) and `kubectl top pods -n booking`.

## 3. Fix

| Cause | Action |
| --- | --- |
| Pods at their CPU limit | Scale out: `kubectl -n booking scale deploy/booking-api --replicas=<n>` (Karpenter adds nodes in demo); make it permanent in the Helm values |
| No healthy targets | A bad release: Argo CD → booking-api → History → roll back to the previous image tag (Day 10: Argo Rollouts does this automatically). Readiness failing on the DB: see the RDS rows |
| RDS CPU high | Lower the admission rate further. Check slow queries in Performance Insights; seat-map reads should come from Redis (cache hits) |
| RDS connections high | Too many pods × pool size: lower `DB_POOL_SIZE` or the replica count; never raise the pool above what the instance allows |
| Redis down or evicting | The seat map falls back to PostgreSQL (slower, still correct); restore Redis, and the cache refills itself |
| 5xx from one endpoint only | X-Ray: filter `http.status_code >= 500`; read that pod's ERROR logs |

## 4. After

- Put the admission rate back up step by step (100 → 150 → 250) while watching p95.
- Record it: when, the p95 and 5xx peaks, the cause, the fix. Raise `requests` or replicas in
  the Helm values if the load was expected.
