# Week 2 · Day 10 Task 3 — GuardDuty, Security Hub, CloudTrail; base image + HIGH gate

- **Date:** 2026-11-25
- **Phase / milestone:** Phase 5 → M5
- **Status:** Done. **The 24-hour follow-up is open** (measured Config and Security Hub cost,
  FSBP score, quick fixes for high/critical findings).
- **Commit / PR:**
  - [#73](https://github.com/sheshagiri-62/surgegate/pull/73): GuardDuty, Security Hub, Config,
    CloudTrail, `make security-off`;
  - [#74](https://github.com/sheshagiri-62/surgegate/pull/74): Alpine base image, HIGH gate,
    exception file.

## 1. What the task was

Plan, Day 10 Task 3 + 5: *"GuardDuty, Security Hub, CloudTrail; ECR scan and Trivy gates; secrets
rotation check"* and *"base image upgrade for booking-api (clear the HIGH ECR findings) and a
build-deploy gate that fails on HIGH."* Your conditions:
- prices and trial status first;
- Config records only what FSBP needs, with no snapshots;
- a `make security-off` for before the trials end;
- an exception file (CVE, reason, expiry);
- p95 and CPU per pod before vs after Alpine, reverting if p95 is more than 20% worse.

## 2. What I did, step by step

1. **Prices and status** (Price List API, Mumbai):
   - GuardDuty: no detector yet, so **30-day free trial** (every data source $0 during it).
     Afterwards CloudTrail events cost $4.40 per million and S3 data events $1.00 per million.
   - Security Hub CSPM: not subscribed, so **30-day trial**. Afterwards $0.001 per check (first
     100k), and the first 10,000 findings a month are free.
   - Config: **not in the trial**, about $0.003 per configuration item.
   - CloudTrail: one trail with management events only is **free**; you pay just S3 storage.
2. **`infra/modules/security`** (shared env, Terraform):
   - **CloudTrail:** multi-region trail, management events only, log-file validation, its own
     S3 bucket (SSE-S3, versioned, TLS-only policy, 90-day lifecycle).
   - **GuardDuty:** EKS audit logs and S3 data events on; Runtime Monitoring, EBS malware, RDS,
     Lambda and AI protection off.
   - **Security Hub:** FSBP v1.0.0 only (no default standards); consolidated control findings.
   - **AWS Config:** one recorder for **27 FSBP-relevant resource types** (no "all supported", no
     global types, no ENIs), continuous recording, and **no snapshot delivery**.
   - **`make security-off`**: plans `enable_security_services=false`, asks "yes", and removes
     GuardDuty, Security Hub and the Config recorder (CloudTrail stays). It's in the Day 12
     checklist: **before ~26 Dec 2026**.
3. **Base image:** `python:3.12-slim` (Debian 13) had **9 HIGH in ECR** (all `openssl
   3.5.9-1~deb13u1`) and **54 HIGH in Trivy**, **none with a fixed version** (installed =
   candidate). The alternatives, scanned with Trivy:

   | Base | HIGH | CRITICAL | Fixable |
   | --- | --- | --- | --- |
   | `python:3.12-slim` (Debian 13) | 54 | 0 | 0 |
   | `python:3.12-slim-bookworm` (Debian 12) | 100 | 2 | 0 |
   | `python:3.12-alpine` | 16 (`krb5-libs`) | 0 | **16** |

   I chose **`python:3.12.16-alpine3.24` + `apk upgrade`**. Result: **0 HIGH, 0 CRITICAL** (OS
   and Python packages).
4. **Gates (`build-deploy.yml`):**
   - Trivy fails on **fixable HIGH and CRITICAL** (was CRITICAL only).
   - New **ECR scan gate**: any HIGH or CRITICAL after the push stops the job, so the tag is
     never bumped and nothing is deployed.
   - **One exception file, `.trivyignore.yaml`** (id, statement = reason, `expired_at`): Trivy
     reads it natively, and the ECR gate accepts only entries that haven't expired
     (`.github/scripts/vuln_exceptions.py`). It's empty today.
5. **Before / after Alpine**, under the same 20 req/s (k6 in the cluster): see section 5.

### Commands I ran

```bash
# status + prices: guardduty ListDetectors, securityhub DescribeHub, cloudtrail DescribeTrails, pricing GetProducts
terraform -chdir=infra/envs/shared plan -out=sec.tfplan        # 22 to add
terraform -chdir=infra/envs/shared apply sec.tfplan            # 22 added
docker run aquasec/trivy:0.67.2 image --severity HIGH,CRITICAL <python:3.12-slim | -slim-bookworm | -alpine>
docker build -t sg-booking:alpine services/booking-api
docker run --read-only --user 10001 sg-booking:alpine          # /healthz {"status":"ok"}
docker run aquasec/trivy:0.67.2 image --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1 sg-booking:alpine   # exit 0
kubectl -n booking top pods                                    # every 30 s, 7 min before + 7 min after
gh pr merge 73 && gh pr merge 74                               # Alpine canary under 20 rps: Healthy
```

### Files created or changed

| File | What it does |
| --- | --- |
| `infra/modules/security/*`, `infra/envs/shared/main.tf`, `variables.tf` | Trail, GuardDuty, Security Hub, Config |
| `Makefile` | `security-off` |
| `services/booking-api/Dockerfile` | `python:3.12.16-alpine3.24` + `apk upgrade`, `adduser` |
| `.github/workflows/build-deploy.yml` | Trivy HIGH+CRITICAL (fixable), ECR gate, exception file |
| `.trivyignore.yaml`, `.github/scripts/vuln_exceptions.py` | Exceptions with reason + expiry |
| `docs/progress/CHECKLIST.md` | `make security-off` before ~26 Dec (Day 12) |

## 3. How it works

- **CloudTrail** records every AWS API call (who, what, when, from where) into S3, with
  validation files that prove the logs weren't changed afterwards.
- **GuardDuty** reads CloudTrail, VPC flow logs, DNS logs, EKS audit logs and S3 data events, and
  raises findings for suspicious behaviour: stolen keys used from odd places, a pod talking to a
  crypto-mining domain, an IAM user disabling logging.
- **AWS Config** keeps the current configuration of each recorded resource.
- **Security Hub** runs the **AWS Foundational Security Best Practices** checks against Config's
  data (e.g. "S3 bucket blocks public access", "RDS is encrypted") and collects GuardDuty's
  findings in one place, with a score.
- **Image gates:** every build is scanned twice, by Trivy before the push and by ECR after it. A
  HIGH or CRITICAL with a fix available stops the release. A finding can be accepted only through
  a reviewed entry with a reason and an **expiry date**, so an exception can't quietly become
  permanent.

## 4. Errors I hit and how I fixed them

| # | Error (exact message) | Cause | Fix |
| --- | --- | --- | --- |
| 1 | `InvalidAccessException: Account 968077439619 is not subscribed to AWS Security Hub CSPM` | Expected: the status check before enabling | Enabled through Terraform |
| 2 | Trivy JSON parse error `Expecting value: line 1 column 1` for 2 of 3 images | The scan output was empty (first run of the container, no cache) | Re-ran with a cache volume; all three scanned |
| 3 | The workflow edit script stopped with `AssertionError` (on the last replacement), so the first #74 commit had only the Dockerfile | The replacement text didn't match exactly (escaping) | Made the edits with the editor; second commit |
| 4 | Pre-commit `ruff check … Failed` / `ruff format … Failed` (new script) | Formatting | The hook reformatted it; committed again |

## 5. How I verified it works

**Services (API):**
- GuardDuty `ENABLED`, with CLOUD_TRAIL, DNS_LOGS, FLOW_LOGS, S3_DATA_EVENTS, EKS_AUDIT_LOGS
  enabled and RUNTIME_MONITORING, EBS_MALWARE_PROTECTION, RDS_LOGIN_EVENTS, LAMBDA_NETWORK_LOGS,
  AI_PROTECTION disabled.
- Security Hub subscribed at 20:06:37 UTC, FSBP `READY`.
- Config recording, last status `SUCCESS`, `allSupported: false`, 27 types.
- CloudTrail `IsLogging: true`.

**Gates on the real build (#74):** Trivy passed (fixable HIGH/CRITICAL), `accepted (not
expired): none`, **`ECR gate passed: no HIGH/CRITICAL findings`**. The parser test: an expired
entry and an entry without `expired_at` are not accepted.

**Before / after Alpine (same 20 req/s, ALB target-group metrics, 7-minute windows):**

| | Debian slim (20:41–20:48) | Alpine (21:05–21:12) | Change |
| --- | --- | --- | --- |
| **p95** | **4.67 ms** | **5.37 ms** | **+15.0%** (limit +20%: **keep Alpine**) |
| p50 | 3.50 ms | 3.91 ms | +11.7% |
| CPU per pod | 31.2m (3 pods) | 24.8m (4 pods) | total 93.6m → 99.2m: **+6%** for the same load |
| Memory per pod | 103 Mi | 90 Mi | −13% |
| Requests / 5xx | 8,400 / 0 | 8,400 / 0 | — |
| HIGH / CRITICAL | 9 (ECR), 54 (Trivy), 0 fixable | **0 / 0** | — |

Alpine's musl C library and allocator are a little slower for Python (+0.7 ms p95), far inside
the 500 ms SLO. The HPA happened to run 4 pods in the second window, so the total CPU is the fair
comparison.

**Still open (24 h):** the measured Config + Security Hub cost, the FSBP score, quick fixes for
high/critical findings, and the rest listed with reasons.

**Secrets rotation check** (Secrets Manager `ListSecrets`, 9 secrets):

| Secret | Rotation | Note |
| --- | --- | --- |
| `rds!db-…` (PostgreSQL master) | **on, every 7 days** (RDS-managed) | The app reads it at connect time, so rotation needs no restart |
| `surgegate/dev/queue/token-key`, `queue/pass-key`, `data/ticket-key`, `events/live-key` | off | HMAC signing keys. Every token carries a `kid`, but **only the ticket verifier accepts several keys** (`{kid: key}`). The booking-pass, queue-token and live-token verifiers hold **one** key and refuse any other `kid`, so rotating one today would invalidate live tokens (passes 15 min, queue tokens 6 h, live tokens 60 s). A safe rotation first needs "accept old + new" in those three verifiers (small change, future work) |
| `surgegate/dev/edge/origin-verify` | off | Shared CloudFront/ALB/queue header; rotate by Terraform (new `random_password`), the same apply updates all three |
| `surgegate/dev/data/redis-auth`, `data/razorpay` | off | Terraform-generated; mock provider (ADR 004) |
| `surgegate/dev/test-users` | off | Dev-only test accounts |

Not done (future work): multi-key verification in the three single-key verifiers, then
scheduled rotation of the signing keys.

## 6. Cost impact

| Item | Cost |
| --- | --- |
| CloudTrail (management events) | $0 + S3 storage (cents) |
| GuardDuty | $0 during the trial (to ~26 Dec) |
| Security Hub | $0 during the trial |
| AWS Config | ~$0.003 per configuration item: **to be measured after 24 h** |
| Image gates | $0 |

**`make security-off` before ~26 Dec 2026**, or GuardDuty and Security Hub start billing.

## 7. Interview notes

- **Q:** What do GuardDuty and Security Hub each do?
  **A:** GuardDuty detects threats by analysing activity (CloudTrail, flow logs, DNS, EKS audit
  logs). Security Hub checks configuration against best practices (via AWS Config) and gathers
  all findings, GuardDuty's included, in one place with a score.
- **Q:** Your scanner found HIGH CVEs with no fix. What did you do?
  **A:** Blocking every release on them helps no one. I compared base images with Trivy, moved to
  Alpine (0 HIGH/CRITICAL after `apk upgrade`), measured the cost (+0.7 ms p95, +6% CPU) against
  a 20% limit, and kept the gate strict for **fixable** findings. Unfixable ones can only be
  accepted through an entry with a reason and an expiry.
- **Q:** How do you stop the security bill from surprising you?
  **A:** Use the free trials while building, record only the Config resource types the checks
  need, measure after 24 hours, and have one command (`make security-off`) on the teardown
  checklist with a date.

## 8. Next task

Day 10 Task 4: k6 at 10,000 then 50,000 virtual users on the `demo` environment (needs your yes
on cost and the load-generator plan).
