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
