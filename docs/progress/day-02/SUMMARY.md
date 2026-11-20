# Day 2 summary — Fri 20 Nov 2026

Phase 1 (Foundations) → M1. **4 of 5 tasks done; Task 4 is partly done and paused** (CloudFront
needs AWS account verification). M1 isn't complete yet: it needs the public HTTPS `/healthz`.

## Finished

| Task | Result | PR |
| --- | --- | --- |
| Setup | `surgegate-monthly` budget ($45; ACTUAL 33/66/100 %, FORECASTED 100 %); 2 old budgets deleted; Support case text drafted (Kinesis/MSK, then CloudFront) | — |
| 1. `eks` module | EKS 1.37, 2 × t3.medium, Pod Identity, LB controller; access entries for you / CI apply / CI plan; node tags fixed | [#7](https://github.com/sheshagiri-62/surgegate/pull/7) |
| 2. Argo CD | Argo CD v3.6.2 by Terraform; root app-of-apps on `deploy/argocd` | [#8](https://github.com/sheshagiri-62/surgegate/pull/8) |
| 3. ECR + `build-deploy.yml` | ECR (shared root), OIDC push role (`main` only, one repo), deploy key + `main-protection` ruleset; **full loop proven**: merge → test → Trivy → ECR push → scan → tag bump (deploy key) → Argo CD → pods on the pushed digest | [#9](https://github.com/sheshagiri-62/surgegate/pull/9), [#10](https://github.com/sheshagiri-62/surgegate/pull/10), [#11](https://github.com/sheshagiri-62/surgegate/pull/11) |
| 4. `edge` module (part) | Terraform-owned ALB (SG = CloudFront prefix list; default 403; secret-header rule), target group + chart TargetGroupBinding, secret in Secrets Manager, 503 CloudFront Function, persistent CloudFront behind `enable_cloudfront`, Route 53/ACM behind `domain_name`, ADR 003 | [#12](https://github.com/sheshagiri-62/surgegate/pull/12) |
| 5. `make up` / `make down` | Full cycle down → up → down: 55 destroyed / 58 added / 55 destroyed; `make up` brings apps back via Argo CD in 14 min; ALB targets healthy; direct ALB refused; new `make billing-check` | `feat/make-up-down` (this PR) |

Also: Day 10 gained "base image upgrade for the 3 HIGH ECR findings + gate on HIGH". ADR 003 got
the follow-up "fix the HTTP CloudFront → ALB hop before Day 7".

## Not finished / open items

| Item | Why | Next step |
| --- | --- | --- |
| **Task 4: CloudFront distribution**, so M1's public `https://…/healthz` and the live no-header 403 test | `AccessDenied: Your account must be verified before you can add new CloudFront resources` | You submitted a combined support case. When verified: `enable_cloudfront = true`, plan, apply, run the CloudFront checks, close M1 |
| Kinesis / MSK | Still `SubscriptionRequiredException` after the Paid upgrade | Same support case; needed Day 8 |
| Route 53 domain | Registration failed | Same support case; optional (ADR 003) |
| vCPU quota 16 | `CASE_OPENED`, value 8 | Needed by Day 9 |
| **Planning note (Days 5–6)** | The waiting room's cached `/serving` counter and the `/book/*` pass check are CloudFront pieces | If CloudFront isn't verified by Day 5: build API Gateway, Lambda, SQS and DynamoDB first; CloudFront pieces last |

## All errors of the day

| # | Task | Error (short) | Cause | Fix |
| --- | --- | --- | --- | --- |
| 1 | 1 | `repo is corrupt or missing repo=prometheus-community …` | Stale personal Helm repos | Harmless for search; see #3 |
| 2 | 1 | tflint: missing version constraint for provider `helm` | Provider used but not declared in dev | Declared `helm ~> 3.3` |
| 3 | 1 | `Error locating chart … no cached repo found … prometheus-community-index.yaml` | helm provider read the personal repo list | Private `repository_config_path` / `repository_cache` under `.helm/` (gitignored) |
| 4 | 1 | `Invalid value for variable enable_eks` | Deliberate guard test (EKS without NAT) | Expected |
| 5 | 1 | `No valid credential sources found … login session has expired` | `aws login` session expired overnight | You re-logged in; same saved plan applied |
| 6 | 1 | `kubectl … custom-columns` printed `<none>` for zone/type | Label-key escaping | Used `kubectl get nodes -L …` |
| 7 | 1 | Node instances lacked `Project`/`Env` tags | `default_tags` don't reach node-group instances | Passed tags into the module; node group rolled |
| 8 | 1 | CI: `cached package for … helm 3.3.0 … does not match any of the checksums` | Lock file had Windows hashes only | `providers lock` for windows + linux |
| 9 | 2 | `Error acquiring the state lock … 412 PreconditionFailed … Who: runner@…` | CI plan held the S3 lock | `-lock-timeout` (now in `make` too) |
| 10 | 3 | Docker API pipe not found | Docker Desktop not running | Image built in CI only |
| 11 | 3 | `Could not retrieve providers for locking`; `lookup sts.ap-south-1.amazonaws.com: no such host` | Short DNS outage | Retried |
| 12 | 3 | ruff `I001 Import block is un-sorted` | `app` not known as first-party | `known-first-party = ["app"]` |
| 13 | 3 | `StarletteDeprecationWarning … install httpx2` | Deprecation warning | Sandbox blocked installing an unknown package name; kept `httpx` |
| 14 | 3 | `namespaces "booking" not found` (dry run) | Namespace created later by Argo CD | Dry-ran into `default` |
| 15 | 3 | Helm cache `.tgz` staged in a commit | Branch lacked the `.helm/` ignore line | Untracked + amended the local commit (never pushed) |
| 16 | 3 | `Post "https://api.github.com/graphql": unexpected EOF` (you) | Network drop | Retried |
| 17 | 3 | `key is already in use` (422) (you) | REST fallback after a successful retry | Expected |
| 18 | 3 | PR #8 `CONFLICTING` | Stacked branch vs squash-merged #7 | `merge -X ours origin/main` (no force push) |
| 19 | 3 | `Waiter ImageScanComplete failed … ScanNotFoundException` | Scan record appears seconds after the push | PR #10: poll; skip build when the tag already exists |
| 20 | 4 | Pricing query `JSONDecodeError` | Filter value with a space split the shell argument | Filtered by `usagetype` only |
| 21 | 4 | **`AccessDenied: Your account must be verified before you can add new CloudFront resources`** | Account restriction | Stopped (rule); support case; `enable_cloudfront = false` |
| 22 | 4 | `terraform state list -lock-timeout` printed nothing | Flag not supported by `state list` | Ran without the flag |
| 23 | 4 | Rebase conflict in CHECKLIST/README | Task 3 lines (main) next to Task 4 lines | Kept both, in order; UTF-8 checked |
| 24 | 5 | Sandbox denied merging PR #12 | Not explicitly requested | Asked; you approved |
| 25 | 5 | (Caught) Task 5 branch on `main` without the edge module | `make down` would have destroyed the persistent secret and function | Rebuilt the branch on `infra/edge` |
| 26 | 5 | `billing-check` blank lines, then `sed: … unknown option to 's'`, then rows on one line | Extra `echo`; malformed sed; no newline for empty results | `VAR=$(…)` + `echo "label: $VAR"` + verdict |
| 27 | 5 | Safety check blocked a heredoc command ("could not be checked for dangerous rm") | Quoting too complex to parse | Same edit with the editor tool |
| 28 | 5 | Secret comparison `MISMATCH` | `aws.exe` CRLF output left a `\r` | Compared in Python by hash: MATCH |

## Cost today (estimate)

Cost Explorer lags about 24 h (and its API costs $0.01 per call), so this is an estimate from the run times:

| Window (UTC, 20 Nov) | Running | Rate | Cost |
| --- | --- | --- | --- |
| ≈ 13:00 → 16:50 | EKS + 2 nodes + NAT/EIP (+ ALB from ≈ 15:40) | $0.256 → $0.29/h | ≈ $1.03 |
| ≈ 16:55 → 17:35 | Second `make up` cycle (verification) | ≈ $0.29/h | ≈ $0.20 |
| Persistent | ECR (2 images, ≈ 0.1 GB), secret, S3 state | ≈ $0.02/day | ≈ $0.02 |
| **Day 2 total** | | | **≈ $1.25** |

Running total for the project: ≈ $1.27 (Day 1 ≈ $0.02). All of it is covered by the $140 credit.

## Still running

**Nothing that bills by the hour.** Checked after the final `make down` (55 destroyed) with
`make billing-check` and an account-wide sweep: no EKS clusters, EC2 instances, load balancers, NAT
gateways, Elastic IPs, public IPv4 ENIs, unattached EBS volumes, RDS, ElastiCache or CloudFront
distributions (ap-south-1 and us-east-1).

Kept on purpose: VPC/subnets/endpoints (free), ECR `surgegate/booking-api` (2 images), secret
`surgegate/dev/edge/origin-verify` ($0.40/month), CloudFront function `surgegate-dev-origin-down`
(free unless invoked), state bucket, CI roles, budget.

## Tomorrow (Day 3, Sat 21 Nov) starts with

1. Read-only re-check: account verification (CloudFront), Kinesis/MSK, vCPU quota. If CloudFront
   is verified: finish Task 4 (`enable_cloudfront = true`) and close **M1**.
2. Merge the Task 5 PR.
3. Day 3 Task 1: `data` module (RDS PostgreSQL single-AZ, ElastiCache Redis, S3, KMS, Secrets
   Manager). RDS and Redis bill by the hour, so plan and costs first. They need `make up` /
   `make down` switches too (RDS kept as a snapshot between sessions, per the plan).
