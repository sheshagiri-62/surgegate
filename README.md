# SurgeGate

A flash-sale ticketing platform with a fair virtual waiting room, built on AWS.

When tens of thousands of fans arrive at once, SurgeGate puts them in a fair queue, admits only as
many as the booking system can serve, holds seats for 10 minutes while they pay, and never sells
the same seat twice.

> **Status:** under construction (19–30 Nov 2026). Architecture, results and a demo video land here
> on Day 12.

> **Cost warning:** `make up` creates AWS resources that bill by the hour (EKS, NAT gateway, ALB,
> RDS, ElastiCache). Always run `make down` when you finish.

## Stack

AWS (CloudFront, WAF, API Gateway, Lambda, SQS, DynamoDB, EKS, RDS PostgreSQL, ElastiCache,
Step Functions, EventBridge, MSK), Terraform, GitHub Actions (OIDC), Helm, Argo CD,
Python 3.12 / FastAPI, Next.js + TypeScript.

## Repository layout

| Path | What lives there |
| --- | --- |
| `infra/bootstrap` | State bucket, GitHub OIDC provider and CI roles (applied once) |
| `infra/modules` | Terraform modules: network, eks, data, edge, queue, async, events, observability, security, cost |
| `infra/envs` | `dev` (small, per session) and `demo` (full two-AZ, load tests and demo only) |
| `services` | booking-api (FastAPI), queue Lambdas, workers, event consumers |
| `web` | `buyer` (Next.js static export), `organiser` (Next.js SSR) |
| `deploy` | Helm charts and Argo CD applications |
| `tests` | k6 load tests, AWS FIS chaos experiments |
| `docs` | Blueprint, implementation plan, ADRs, runbooks, progress reports |

## Getting started

Needs: Terraform, AWS CLI v2, kubectl, Helm, Docker, Python 3.12, Node.js LTS, k6, GNU make,
pre-commit, tflint, ruff.

```bash
aws login --profile surgegate   # short-term credentials, never access keys
make init                       # git hooks + tflint plugin
make help                       # list all commands
```

## Docs

- [Blueprint and system design](docs/blueprint.md)
- [Implementation plan](docs/implementation-plan.md)
- [Progress reports](docs/progress/README.md)
