# SurgeGate — Progress log

One line per finished task, newest at the bottom. Full checklist: [CHECKLIST.md](CHECKLIST.md).
Reports follow [TEMPLATE.md](TEMPLATE.md).

| Date | Day | Task | Report |
| --- | --- | --- | --- |
| 2026-11-19 | 1 | Task 1 — Repo structure, Makefile, pre-commit hooks, README stub | [task-01-repo-structure](day-01/task-01-repo-structure.md) |
| 2026-11-19 | 1 | Task 2 — `infra/bootstrap`: state bucket, GitHub OIDC provider, plan and apply roles | [task-02-bootstrap](day-01/task-02-bootstrap.md) |
| 2026-11-19 | 1 | Task 3 — `infra-plan.yml`: fmt, validate, tflint, plan comment on PRs | [task-03-infra-plan](day-01/task-03-infra-plan.md) |
| 2026-11-19 | 1 | Task 4 — `network` module: VPC, 2 AZs, 3 subnet tiers, 1 NAT, gateway endpoints | [task-04-network](day-01/task-04-network.md) |
| 2026-11-19 | 1 | Task 5 — ADR 001: EKS, SQS for jobs + EventBridge/Kinesis for events, static buyer site | [task-05-adr-001](day-01/task-05-adr-001.md) |
| 2026-11-20 | 2 | Task 1 — `eks` module: cluster, managed node group, Pod Identity, AWS Load Balancer Controller | [task-01-eks](day-02/task-01-eks.md) |
| 2026-11-20 | 2 | Task 2 — Argo CD on EKS, root app-of-apps on `deploy/argocd` | [task-02-argocd](day-02/task-02-argocd.md) |
| 2026-11-20 | 2 | Task 3 — ECR + `build-deploy.yml`: build, scan, push, Helm tag bump; full loop proven | [task-03-build-deploy](day-02/task-03-build-deploy.md) |
| 2026-11-20 | 2 | Task 4 — `edge` module: Terraform-owned ALB + CloudFront default domain (**paused**: CloudFront needs account verification) | [task-04-edge](day-02/task-04-edge.md) |
| 2026-11-20 | 2 | Task 5 — `make up` / `make down` end to end + `make billing-check` | [task-05-make-up-down](day-02/task-05-make-up-down.md) |
| 2026-11-21 | 3 | Task 1 — `data` module: RDS PostgreSQL, ElastiCache Redis, S3, KMS, Secrets Manager; `make up`/`make down` switches | [task-01-data](day-03/task-01-data.md) |
| 2026-11-21 | 3 | Task 2 — Booking API models + Alembic migrations; migration Job run against RDS by Argo CD | [task-02-models-migrations](day-03/task-02-models-migrations.md) |
| 2026-11-21 | 3 | Task 3 — Cognito user pool (buyer/organiser, tenant claim) + JWT checks in FastAPI | [task-03-cognito-jwt](day-03/task-03-cognito-jwt.md) |
| 2026-11-21 | 3 | Task 4 — Organiser endpoints (create, upload seat map CSV, list), tenant-scoped | [task-04-organiser-endpoints](day-03/task-04-organiser-endpoints.md) |
| 2026-11-21 | 4 | Task 1 — Seat map endpoint with Redis cache (2 s TTL, stampede lock, invalidation) | [task-01-seatmap-cache](day-04/task-01-seatmap-cache.md) |
| 2026-11-21 | 4 | Task 2 — Hold endpoint: single conditional UPDATE + per-buyer limit (advisory lock) | [task-02-holds](day-04/task-02-holds.md) |
| 2026-11-21 | 4 | Task 3 — Concurrency test: 200 parallel → exactly 10 holds (CI + real RDS) | [task-03-concurrency-test](day-04/task-03-concurrency-test.md) |
| 2026-11-21 | 4 | Task 4 — Cross-tenant test over every organiser route (mutation-checked) | [task-04-cross-tenant-test](day-04/task-04-cross-tenant-test.md) |
| 2026-11-21 | 4 | Task 5 — Buyer Next.js app (static export): event page + seat picker; API CORS for localhost | [task-05-buyer-app](day-04/task-05-buyer-app.md) |
| 2026-11-21 | — | **M2 met** — Phase 2 milestone | [phase-2-milestone](phase-2-milestone.md) |
| 2026-11-21 | 5 | Task 1 — `queue` module: HTTP API + JWT authorizer, join → SQS, batched sequencer → DynamoDB | [task-01-queue-module](day-05/task-01-queue-module.md) |
