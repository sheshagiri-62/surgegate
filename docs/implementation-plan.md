# SurgeGate — Implementation Plan

Nov 19, 2026 · @sheshagiri

SurgeGate is built at full scope in six two-day phases from Nov 19, 2026 to Nov 30, 2026, about 10–12 hours a day with Claude Code writing most of the code; each plan "week" below is now one day, with a working demo at the end of every phase.

## Timeline

&#91;embedded content: SurgeGate build roadmap · 6 phases, 19 to 30 Nov 2026\]

Each gate is a working demo you can show; if a gate slips, use the cut list at the end rather than moving the final date.

## Setup: first 4 hours of Day 1

Do these once, before any code; they protect your money and your accounts.

**Accounts**

- [x] AWS account: check whether it is on the Free or Paid plan and how much credit is left; region `ap-south-1` (Mumbai).
- [ ] Root user: MFA on, no access keys, then never used again.
- [ ] IAM user `sheshagiri-admin` with MFA and AdministratorAccess; CLI login with `aws login --profile surgegate` (short-term credentials, no access keys). Do not enable IAM Identity Center: creating an organization ends the Free plan credits.
- [ ] AWS Budgets: alerts at $15, $30 and $45 to your email.
- [ ] Azure for Students account with your PES email ($100 credit, no card).
- [x] GitHub repository `surgegate` (public), branch protection on `main`.
- [ ] Razorpay account in test mode; note the test key ID and secret.
- [ ] A domain for the demo (any cheap domain, or one from the GitHub Student Developer Pack if offered), managed in Route 53.

**Tools on your laptop**

- [ ] Terraform, AWS CLI v2, kubectl, Helm, Docker, Python 3.12, Node.js LTS, k6, the Argo CD CLI.
- [ ] VS Code with the Terraform, Python and ESLint extensions; `pre-commit` with `terraform fmt`, `tflint`, `ruff`.

**Habits**

- [ ] Tag every resource: `Project=surgegate`, `Env`, `Component` (Terraform `default_tags`).
- [ ] End of every session: run `make down` and check in the console that no EKS cluster, NAT gateway, ALB or RDS instance is left running in dev.

## Repository and environments

One monorepo holds infrastructure, services, frontends and tests, so one pull request can change an API and the Terraform it needs together.

```text
surgegate/
  infra/
    bootstrap/            # state bucket, GitHub OIDC provider and CI roles (applied once by hand)
    modules/
      network/            # VPC, 2 AZs, public/private/data subnets, NAT, gateway endpoints
      eks/                # EKS cluster, managed node group, Karpenter, LB controller, Pod Identity
      data/               # RDS PostgreSQL, ElastiCache Redis, DynamoDB tables, S3 buckets, KMS
      edge/               # Route 53, ACM, CloudFront, CloudFront Function, WAF
      queue/              # API Gateway, queue Lambdas, SQS, Scheduler, WebSocket API
      async/              # Step Functions, payment and ticket workers, SES
      events/             # EventBridge bus, Kinesis stream, sale-events consumers
      observability/      # log groups, alarms, dashboards, SNS
      security/           # CloudTrail, GuardDuty, Security Hub, Config
      cost/               # Budgets, cost allocation tags
    envs/
      dev/                # small, single NAT, created and destroyed per session
      demo/               # full two-AZ setup, only for load tests and the demo
  services/
    booking-api/          # FastAPI + SQLAlchemy + Alembic
    queue/                # Lambda functions: join, sequencer, position, admit, serving, valve
    workers/              # hold timer tasks, payment worker, ticket worker
    event-consumers/      # live-dashboard, analytics, audit
  web/
    buyer/                # Next.js static export
    organiser/            # Next.js SSR
  deploy/
    helm/                 # charts for booking-api and organiser
    argocd/               # Argo CD applications, Argo Rollouts canary specs
  tests/
    load/k6/              # sale-day scripts
    chaos/fis/            # AZ-disruption experiment
  docs/                   # ADRs, runbooks, results
  .github/workflows/      # ci.yml, infra-plan.yml, infra-apply.yml, build-deploy.yml
  Makefile                # make up / make down / make test / make load
```

| Setting | dev | demo |
| --- | --- | --- |
| When it exists | Days 1–10, only during work sessions | Days 9–12, only for load tests and the demo |
| NAT gateways | 1 | 2 (one per AZ) |
| EKS nodes | 1–2 small nodes | 2+ nodes across 2 AZs, Karpenter on |
| RDS | Single-AZ, smallest class | Multi-AZ |
| Redis | 1 node | Primary + replica |
| WAF, Kinesis, Security Hub | Off (Kinesis on from Day 8, only during sessions) | On |
| Data between sessions | Kept as RDS snapshot + DynamoDB tables | Destroyed after the demo |

## Phases 1–3: platform, booking core, waiting room

### Phase 1 — Foundations (Days 1–2, 19–20 Nov)

**Day 1 (Thu 19 Nov)**

- [ ] Create the repo structure, Makefile, pre-commit hooks and a README stub.
- [ ] `infra/bootstrap`: S3 state bucket with versioning and native lock file; GitHub OIDC provider; `plan` (read-only) and `apply` roles.
- [ ] `infra-plan.yml`: on every pull request, run `terraform fmt`, `validate`, `tflint` and post the plan as a comment.
- [ ] `network` module: VPC, two AZs, public/private/data subnets, one NAT, S3 and DynamoDB gateway endpoints.
- [ ] ADR 001: why EKS, SQS for jobs + EventBridge/Kinesis for events, static buyer site (copy from the blueprint).

**Day 2 (Fri 20 Nov)**

- [ ] `eks` module: cluster, managed node group, Pod Identity, AWS Load Balancer Controller.
- [ ] Install Argo CD on the cluster; point it at `deploy/argocd`.
- [ ] ECR repository; `build-deploy.yml` builds a hello-world FastAPI image, scans it, pushes it, bumps the Helm tag.
- [ ] `edge` module (first part): Route 53 zone, ACM certificate, ALB ingress for `api.<domain>`.
- [ ] `make up` / `make down` working for dev.

**M1 — done when:** a merge to `main` deploys a hello-world API to EKS through Argo CD, it answers at `https://api.<domain>/healthz`, and `make down` leaves nothing billable running.

### Phase 2 — Booking core (Days 3–4, 21–22 Nov)

**Day 3 (Sat 21 Nov)**

- [ ] `data` module: RDS PostgreSQL (single-AZ in dev), ElastiCache Redis, S3 buckets, KMS key, Secrets Manager entries.
- [ ] Booking API: SQLAlchemy models and Alembic migrations for tenants, events, seats, holds, orders, order\_items.
- [ ] Cognito user pool with buyer and organiser groups; JWT checks in FastAPI.
- [ ] Organiser endpoints: create event, upload seat map (CSV), list events — tenant-scoped.

**Day 4 (Sun 22 Nov)**

- [ ] Seat map endpoint with Redis cache and invalidation on change.
- [ ] Hold endpoint: the single conditional `UPDATE` from the blueprint, per-buyer limit in the same transaction.
- [ ] Concurrency test: 200 parallel requests for the same 10 seats; assert exactly 10 holds succeed.
- [ ] Cross-tenant test: organiser A can never read or change organiser B's events.
- [ ] Buyer Next.js app: event page and seat picker calling the API (no queue yet).

**M2 — done when:** an organiser creates an event with a seat map, a buyer holds seats from the browser, and the concurrency test proves zero double bookings.

### Phase 3 — Waiting room (Days 5–6, 23–24 Nov)

**Day 5 (Mon 23 Nov)**

- [ ] `queue` module: API Gateway, `join` Lambda writing to SQS, `sequencer` Lambda assigning positions in batches into DynamoDB.
- [ ] One place per account (conditional write); pre-queue shuffle at sale start.
- [ ] `position` endpoint returning a signed queue token (key in Secrets Manager).
- [ ] `serving` endpoint behind CloudFront with a 5-second cache.

**Day 6 (Tue 24 Nov)**

- [ ] `valve` Lambda on EventBridge Scheduler raising "serving N" by the admission rate; pause and resume.
- [ ] `admit` endpoint issuing a 15-minute booking pass; CloudFront Function checking it on `/book/*`.
- [ ] Buyer waiting-room page: countdown, position, estimated wait, automatic redirect when admitted.
- [ ] k6 script: 1,000 virtual users join, wait and get admitted.

**M3 — done when:** 1,000 simulated buyers join, the pre-queue is shuffled, they are admitted at the set rate, and a request to `/book/*` without a valid pass is refused at the edge.

## Phases 4–6: checkout, hardening, proof

### Phase 4 — Checkout and live events (Days 7–8, 25–26 Nov)

**Day 7 (Wed 25 Nov)**

- [ ] Step Functions hold timer: wait 10 minutes, release only if still held by the same hold.
- [ ] Orders with idempotency keys; Razorpay test-mode checkout in the buyer app.
- [ ] Webhook endpoint: verify signature, put on SQS; order worker confirms exactly once by payment ID.
- [ ] Late-payment rule: re-hold if seats are free, otherwise refund (test mode) and notify.

**Day 8 (Thu 26 Nov)**

- [ ] Ticket worker: PDF + QR code to S3, email through SES (verify your test addresses in the SES sandbox).
- [ ] `events` module: EventBridge bus + Kinesis stream `sale-events`; producers in the queue Lambdas and the booking API.
- [ ] Consumers: live-dashboard (WebSocket push), analytics (S3 + Athena table), audit.
- [ ] Organiser SSR dashboard on EKS: live numbers, pause/resume, admission rate, attendee export; gate check-in endpoint.

**M4 — done when:** a buyer goes from queue to paid ticket email in one run, a duplicate webhook changes nothing, an unpaid hold is released after 10 minutes, and the organiser watches it all update live.

### Phase 5 — Harden and scale (Days 9–10, 27–28 Nov)

**Day 9 (Fri 27 Nov)**

- [ ] Build the `demo` environment: two NAT gateways, Multi-AZ RDS, Redis replica, Karpenter, 2+ nodes.
- [ ] WAF on CloudFront and API Gateway: rate rules, managed bot rules on `/queue/*`, challenge before join.
- [ ] Observability: structured logs, CloudWatch dashboards ("sale room"), Container Insights, X-Ray through OpenTelemetry.
- [ ] SLO alarms from the blueprint; SNS email alerts; three runbooks (queue backlog, booking latency, payment backlog).

**Day 10 (Sat 28 Nov)**

- [ ] Pre-scaling job 15 minutes before a sale; backpressure Lambda lowering the admission rate when p95 > 500 ms.
- [ ] Argo Rollouts canary for the booking API with automatic rollback on error rate.
- [ ] Security: GuardDuty, Security Hub, CloudTrail; ECR scan and Trivy gates; secrets rotation check.
- [ ] k6 runs at 10,000 then 50,000 virtual users; record join success, booking p95, oversold seats, cost.

**M5 — done when:** the 50,000-user test report shows the SLOs met with zero oversold seats, and a deliberately broken release rolls back on its own.

### Phase 6 — Prove and present (Days 11–12, 29–30 Nov)

**Day 11 (Sun 29 Nov)**

- [ ] AWS FIS experiment: cut one AZ's subnets for 5 minutes during a k6 run; record lost orders (target 0).
- [ ] Restore drill: point-in-time restore of RDS to a new instance; record the time as your RTO.
- [ ] Azure: Static Web Apps status page; nightly backup copy to Blob Storage via GitHub Actions federated login.
- [ ] Cost report: total spend, cost per sale event from tags and Cost Explorer.

**Day 12 (Mon 30 Nov)**

- [ ] README with architecture, results table, how to run, cost warning.
- [ ] Portfolio write-up and a 5-minute demo video (queue, sale, AZ failure, rollback).
- [ ] Fill the resume bullets with your measured numbers; LinkedIn post.
- [ ] `make down` on demo; confirm the bill has stopped.

**M6 — done when:** the demo video, results and write-up are public and the AWS bill is back to near zero.

## Ways of working

**Git flow.** Trunk-based: short branches (`feat/`, `fix/`, `infra/`), one pull request per task, squash-merge to `main`. Conventional commit messages (`feat:`, `fix:`, `infra:`). Infrastructure changes only through the plan/apply pipeline, never by clicking in the console.

**Testing strategy**

| Level | Tool | What it proves |
| --- | --- | --- |
| Unit | pytest, Jest | Business rules: limits, hold expiry, signatures, fairness shuffle |
| Integration | pytest with a PostgreSQL container | Seat holds under concurrency, idempotent orders, cross-tenant isolation |
| Infrastructure | `terraform validate`, `tflint`, Checkov | Modules are valid and follow security rules |
| End to end | Playwright | Queue → seat → payment → ticket in a real browser |
| Load | k6 | Join success, booking p95, oversold seats at 1k / 10k / 50k users |
| Resilience | AWS FIS, restore drill | No lost orders on AZ loss; measured RTO |

**Definition of done** for any task:

1. Code and Terraform merged through a pull request with CI green.
2. Tests added for the new behaviour.
3. Deployed to dev by the pipeline, not by hand.
4. A line in `docs/` if it changes how the system works (ADR or runbook).

**Daily rhythm (10–12 hours).** Morning: `make up`, read yesterday's summary, start the day's first task in Claude Code. Two or three focused blocks with breaks; review each task report before typing "next". Evening: run the day's demo check, tick the checklist, `make down`, confirm nothing billable is left. If a task slips, it goes first on the next morning's list.

## Budget, risks and open questions

**Budget controls.** Target under $50 of AWS spend for the whole build.

- Budgets alerts at $15 / $30 / $45; check Cost Explorer every Sunday.
- Hourly items (EKS control plane, NAT, ALB, RDS, Redis, Kinesis, WAF) exist only during work sessions; `make down` every time.
- The `demo` environment lives only on Days 9–12 and only while testing.
- Logs kept 14 days; S3 lifecycle rules on every bucket.

**Risks and responses**

| Risk | Likelihood | Response |
| --- | --- | --- |
| EKS setup eats Day 2 | Medium | Use the community `terraform-aws-modules/eks` module; fall back to one managed node group without Karpenter until Phase 5 |
| Forgetting to tear down → surprise bill | Medium | `make down` habit, Budgets alerts, Sunday cost check |
| Exams or other projects cut a day | High | Leftover tasks move to the next morning; 1–3 December is the overflow buffer; the cut list is a last resort only |
| SES sandbox limits emails | High | Verify your own test addresses; show the email in the demo from those |
| 50,000-user load test is costly | Medium | Run at 10,000 first; run 50,000 once, in the demo environment, for 10 minutes |
| Kinesis consumers harder than expected | Medium | Ship Phase 4 with EventBridge rules first, add the Kinesis stream when the consumers work |

**Cut list (drop in this order if behind; never cut M2's no-oversell test or the M4 end-to-end flow)**

1. Azure status page and backup copy.
2. Analytics and audit consumers (keep the live-dashboard consumer).
3. Argo Rollouts canary (keep the plain Argo CD rollback).
4. Karpenter (keep a managed node group with fixed size + pre-scaling).
5. Gate check-in and attendee export.

**Open questions**

- When are your ESA exams? Those days lose build hours; plan to use the 1–3 December buffer for them.
- When is your final project review? The demo and write-up are ready by 30 November either way.
- Free plan: finishing by 30 November keeps the whole build inside your free period (it ends 22 January 2027), but some services may still be blocked on the Free plan. Day 1 check: MSK Serverless is blocked, so the sale-events stream uses EventBridge + Kinesis (ADR 002). EKS and WAF passed read-only checks; if their creation is blocked, upgrade directly (Billing → Upgrade, never via Organizations, which wipes the credits). The 5-vCPU EC2 limit covers dev; request more before the Day 9 demo build if needed.
