# Day 3 summary — Sat 21 Nov 2026

One evening session (about 19:00–22:30 IST) that covered **all of Day 3 and, ahead of schedule,
all of Day 4** (see `day-04/SUMMARY.md`). This file covers the Day 3 tasks.

## Finished

| Task | PR | Report |
| --- | --- | --- |
| Re-check: CloudFront, Kinesis, MSK still blocked (AWS manual verification; you're escalating by chat); vCPU quota 8 (request for 16 open) | — | in task 1 |
| 1. `data` module: RDS PostgreSQL 18 (single-AZ), ElastiCache Redis 7.1, S3 ×2, KMS, Secrets Manager; `make up`/`down` switches; RDS kept as a final snapshot | [#14](https://github.com/sheshagiri-62/surgegate/pull/14) | [task-01-data](task-01-data.md) |
| 2. Booking API models + Alembic migrations; migrations run against RDS by an Argo CD Job | [#15](https://github.com/sheshagiri-62/surgegate/pull/15), [#16](https://github.com/sheshagiri-62/surgegate/pull/16), [#17](https://github.com/sheshagiri-62/surgegate/pull/17) | [task-02-models-migrations](task-02-models-migrations.md) |
| 3. Cognito user pool (buyer/organiser groups, `tenant_id` in access tokens) + JWT checks in FastAPI | [#19](https://github.com/sheshagiri-62/surgegate/pull/19) | [task-03-cognito-jwt](task-03-cognito-jwt.md) |
| 4. Organiser endpoints (create event, upload seat-map CSV, list), tenant-scoped | [#20](https://github.com/sheshagiri-62/surgegate/pull/20) | [task-04-organiser-endpoints](task-04-organiser-endpoints.md) |

Also merged: #13 (Day 2 make up/down + summary) and #18 (Task 2 report).

## Not finished / open items

- **Snapshot-restore check (Task 1): pending.** Marker row `(1, 'day3-before-make-down')` is in
  `ops_restore_check`. Tonight's `make down` writes the final snapshot; on the next `make up`,
  check the row is back.
- **Day 2 Task 4 / M1:** still paused (CloudFront blocked by account verification).
- **Known issue:** `make up` failed twice at `helm_release.lbc` with `getting credentials: exec:
  executable aws failed with exit code 1`, and a re-run succeeded. Likely cause: the 15-minute
  `aws login` credentials refreshing mid-apply. If it repeats, re-run `make up`; I'll look deeper
  then.
- **Follow-up:** archive uploaded seat-map CSVs in the `seatmaps` S3 bucket (needs pod IAM).
- Still open from Day 2: the ADR 003 follow-up (HTTP hop CloudFront → ALB) before Day 7; the Day 10
  task (base image HIGH findings + pipeline gate).

## All errors of the day (Day 3 tasks)

| # | Task | Error (exact message) | Cause | Fix |
| --- | --- | --- | --- | --- |
| 1 | 1 | `Error: installation failed … helm_release.lbc … Kubernetes cluster unreachable … getting credentials: exec: executable aws failed with exit code 1` (×2) | Most likely the 15-minute login credentials refreshing during a 20-minute apply | Re-ran plan + apply; only the 3 missing Helm releases were left |
| 2 | 1 | Perpetual diff `rds.force_ssl` `apply_method "pending-reboot" -> "immediate"` | Static parameter | `apply_method = "pending-reboot"` |
| 3 | 1 | tflint: `"default.redis7" is default parameter group` | Used the AWS default group | Own `surgegate-dev-redis7` group |
| 4 | 1 | `SSL_connect failed: certificate verify failed` | `redis:7.4` image has no CA store | `--cacert` Amazon Root CA 1 (verification kept on) |
| 5 | 1 | `ERROR: unrecognized configuration parameter "rds.force_ssl"` | Not readable through `SHOW` | Proved it with a refused plain-text connection |
| 6 | 1 | `Premium Support Subscription is required` | Support API needs a paid support plan | Asked you |
| 7 | 2 | pip printed nothing for 15 min | Download hung; hidden by `-q` | Re-ran with visible output |
| 8 | 2 | `TypeError: … create_engine() got multiple values for keyword argument 'pool_size'` | Defaults and caller arguments both passed | Merge defaults with caller kwargs |
| 9 | 2 | `ports are not available: exposing port TCP 0.0.0.0:55432 … forbidden by its access permissions` | Windows-reserved port range | Port 15432 on 127.0.0.1 |
| 10 | 2 | `psycopg.errors.ConnectionTimeout` | Container never started (error 9 hidden) | Fixed by 9 |
| 11 | 2 | `FATAL: database "surgegate" does not exist` | Wrong DB name in `docker exec psql` | `-d surgegate_test` |
| 12 | 2 | ruff `F401 'os' imported but unused` | Leftover import | `ruff --fix` |
| 13 | 2 | Migration Job: `root certificate file "/srv/certs/rds-global-bundle.pem" does not exist` | `ADD --chmod=644` made the new directory mode 644 too | `mkdir -m 755` first; new image smoke test in build-deploy (#17) |
| 14 | 2 | Argo CD stuck `waiting for completion of hook … booking-api-migrate` on the old revision | Auto-sync retries the same revision | Terminated the operation; next sync succeeded |
| 15 | 3 | `Error: Provider produced inconsistent final plan` (×2) | Unknown `random_uuid` values in `aws_cognito_user.attributes` | Re-planned once the random values existed |
| 16 | 3 | Test expected `unknown signing key`, got `invalid token` | Garbage token fails at header decoding | Fixed the expectation |
| 17 | 3 | CI: `… surgegate-gha-plan … not authorized to perform: secretsmanager:GetSecretValue on … test-users` | New secret refreshed during plan | Bootstrap: plan role may read `surgegate/dev/test-users-*` (approved) |
| 18 | 3 | CI plan perpetual diff on `source_code_hash` | Zip file modes differ on Windows/Linux | `output_file_mode = "0644"` |
| 19 | 3 | ruff `S106 Possible hardcoded password … "token_use"` | False positive | `# noqa: S106` |
| 20 | 4 | `/usr/bin/bash: -c: line 214: unexpected EOF while looking for matching ''` | Quoting inside a large heredoc command | Wrote the files with the editor |
| 21 | 4 | `ConnectionRefusedError: [WinError 10061]` | Port-forward not ready after a fixed sleep | `pf.sh` waits for `/healthz` |

## Cost today (estimate)

Dev was up from about 13:25 UTC to the session end, roughly **3.5–4 hours** at about $0.33/hour
(EKS $0.10, 2 × t3.medium, NAT, ALB, RDS, Redis): **≈ $1.20–1.35**.
- Persistent additions today: KMS key (about $1/month), 3 secrets ($1.20/month), Cognito (free
  under 10k MAU), the Lambda (free tier).
- Snapshot storage after `make down`: a few cents a month.
- Budgets were deleted on Day 2 at your request, so `make billing-check` is the guard.

## Still running

Until `make down`: the EKS cluster and 2 nodes, the NAT gateway and its Elastic IP, the ALB, RDS
`surgegate-dev-pg`, and Redis `surgegate-dev-redis`. Locally: Docker containers `sg-pg` and
`sg-redis`, the `kubectl port-forward` and `next dev`. `make down` removes everything hourly and
ends with `make billing-check`.

## Next session starts with

1. `make up`, then **check the snapshot restore**: `ops_restore_check` must contain
   `day3-before-make-down`. That closes Task 1's pending item.
2. Day 5 (Mon 23 Nov), Phase 3, waiting room: API Gateway, Lambda, SQS and DynamoDB first; the
   CloudFront pieces last (your note).
