# SurgeGate — Build checklist

Source: [implementation plan](../implementation-plan.md). One plan-day per calendar day,
Thu 19 Nov → Mon 30 Nov 2026. 1–3 Dec is overflow buffer only.
Tick a box only when the task report exists in `docs/progress/day-XX/`.

## Setup (first 4 hours of Day 1)

**Accounts**

- [x] AWS account plan checked: **Free plan**, $140 credit, ends 22 Jan 2027; region `ap-south-1`
- [x] Free-plan service check (read-only, 19 Nov): EKS and WAF reachable; MSK and Kinesis blocked (`SubscriptionRequiredException`)
- [x] Decision: sale-events stream = EventBridge + Kinesis, not MSK ([ADR 002](../adr/002-eventbridge-kinesis-instead-of-msk.md))
- [x] Paid plan confirmed (`accountPlanType: PAID`, 19 Nov; $140 credit kept)
- [ ] Kinesis reachable after the upgrade (still `SubscriptionRequiredException`, 19 Nov) — re-check evening + 20 Nov morning
- [ ] EC2 vCPU quota 16 in ap-south-1 (request CASE_OPENED; current value 8, 19 Nov 06:07 UTC)
- [ ] Root user: MFA on, no access keys, never used again
- [x] IAM user `sheshagiri-admin`; CLI login with `aws login --profile surgegate` (verified with `sts get-caller-identity`)
- [ ] IAM user MFA confirmed
- [ ] AWS Budgets: alerts at $15, $30 and $45 to email
- [ ] Azure for Students account (PES email)
- [x] GitHub repository `surgegate` (public)
- [x] Branch protection on `main` (required check `infra-plan`, 0 approvals)
- [ ] Razorpay account in test mode; test key ID and secret noted (not in Git)
- [ ] Demo domain, managed in Route 53

**Tools**

- [x] Terraform, AWS CLI v2, kubectl, Helm, Docker, Python 3.12, Node.js LTS, k6
- [ ] Argo CD CLI
- [x] pre-commit, tflint, ruff, GNU make (installed in Day 1 Task 1)

**Habits**

- [ ] Provider `default_tags`: `Project=surgegate`, `Env`, `Component`
- [ ] `make down` at the end of every session

## Phase 1 — Foundations (Days 1–2) → M1

**Day 1 — Thu 19 Nov**

- [x] 1. Create the repo structure, Makefile, pre-commit hooks and a README stub
- [x] 2. `infra/bootstrap`: S3 state bucket with versioning and native lock file; GitHub OIDC provider; `plan` (read-only) and `apply` roles
- [x] 3. `infra-plan.yml`: on every pull request, run `terraform fmt`, `validate`, `tflint` and post the plan as a comment
- [x] 4. `network` module: VPC, two AZs, public/private/data subnets, one NAT, S3 and DynamoDB gateway endpoints
- [x] 5. ADR 001: why EKS, SQS for jobs + EventBridge/Kinesis for events, static buyer site

**Day 2 — Fri 20 Nov**

- [x] 1. `eks` module: cluster, managed node group, Pod Identity, AWS Load Balancer Controller
- [x] 2. Install Argo CD on the cluster; point it at `deploy/argocd`
- [x] 3. ECR repository; `build-deploy.yml` builds a hello-world FastAPI image, scans it, pushes it, bumps the Helm tag
- [ ] 4. `edge` module (first part): Route 53 zone, ACM certificate, ALB ingress for `api.<domain>` — **paused**: ALB side done; CloudFront blocked until account verification (ADR 003)
- [x] 5. `make up` / `make down` working for dev

- [ ] **M1:** a merge to `main` deploys hello-world to EKS through Argo CD, it answers at `https://api.<domain>/healthz`, and `make down` leaves nothing billable

## Phase 2 — Booking core (Days 3–4) → M2

**Day 3 — Sat 21 Nov**

- [x] 1. `data` module: RDS PostgreSQL (single-AZ in dev), ElastiCache Redis, S3 buckets, KMS key, Secrets Manager entries (snapshot-restore check pending next `make up`)
- [x] 2. Booking API: SQLAlchemy models and Alembic migrations for tenants, events, seats, holds, orders, order_items
- [x] 3. Cognito user pool with buyer and organiser groups; JWT checks in FastAPI
- [x] 4. Organiser endpoints: create event, upload seat map (CSV), list events — tenant-scoped

**Day 4 — Sun 22 Nov**

- [x] 1. Seat map endpoint with Redis cache and invalidation on change
- [x] 2. Hold endpoint: single conditional `UPDATE`, per-buyer limit in the same transaction
- [x] 3. Concurrency test: 200 parallel requests for the same 10 seats; exactly 10 holds succeed
- [x] 4. Cross-tenant test: organiser A can never read or change organiser B's events
- [x] 5. Buyer Next.js app: event page and seat picker calling the API (no queue yet)

- [x] **M2:** an organiser creates an event with a seat map, a buyer holds seats from the browser, and the concurrency test proves zero double bookings ([phase-2-milestone](phase-2-milestone.md); browser click-through = your demo step)

## Phase 3 — Waiting room (Days 5–6) → M3

**Day 5 — Mon 23 Nov**

- [x] 1. `queue` module: API Gateway, `join` Lambda writing to SQS, `sequencer` Lambda assigning positions in batches into DynamoDB
- [x] 2. One place per account (conditional write); pre-queue shuffle at sale start
- [x] 3. `position` endpoint returning a signed queue token (key in Secrets Manager)
- [x] 4. `serving` endpoint behind CloudFront with a 5-second cache — API Gateway done; **5 s CloudFront cache pending CloudFront verification**

**Day 6 — Tue 24 Nov**

- [ ] 1. `valve` Lambda on EventBridge Scheduler raising "serving N" by the admission rate; pause and resume
- [ ] 2. `admit` endpoint issuing a 15-minute booking pass; CloudFront Function checking it on `/book/*`
- [ ] 3. Buyer waiting-room page: countdown, position, estimated wait, automatic redirect when admitted
- [ ] 4. k6 script: 1,000 virtual users join, wait and get admitted

- [ ] **M3:** 1,000 simulated buyers join, the pre-queue is shuffled, they are admitted at the set rate, and `/book/*` without a valid pass is refused at the edge

## Phase 4 — Checkout and live events (Days 7–8) → M4

**Day 7 — Wed 25 Nov**

- [ ] 1. Step Functions hold timer: wait 10 minutes, release only if still held by the same hold
- [ ] 2. Orders with idempotency keys; Razorpay test-mode checkout in the buyer app
- [ ] 3. Webhook endpoint: verify signature, put on SQS; order worker confirms exactly once by payment ID
- [ ] 4. Late-payment rule: re-hold if seats are free, otherwise refund (test mode) and notify

**Day 8 — Thu 26 Nov**

- [ ] 1. Ticket worker: PDF + QR code to S3, email through SES (verified sandbox addresses)
- [ ] 2. `events` module: EventBridge bus + Kinesis stream `sale-events`; producers in the queue Lambdas and the booking API
- [ ] 3. Consumers: live-dashboard (WebSocket push), analytics (S3 + Athena table), audit
- [ ] 4. Organiser SSR dashboard on EKS: live numbers, pause/resume, admission rate, attendee export; gate check-in endpoint

- [ ] **M4:** a buyer goes from queue to paid ticket email in one run, a duplicate webhook changes nothing, an unpaid hold is released after 10 minutes, and the organiser watches it update live

## Phase 5 — Harden and scale (Days 9–10) → M5

**Day 9 — Fri 27 Nov**

- [ ] 1. Build the `demo` environment: two NAT gateways, Multi-AZ RDS, Redis replica, Karpenter, 2+ nodes
- [ ] 2. WAF on CloudFront and API Gateway: rate rules, managed bot rules on `/queue/*`, challenge before join
- [ ] 3. Observability: structured logs, CloudWatch "sale room" dashboards, Container Insights, X-Ray through OpenTelemetry
- [ ] 4. SLO alarms; SNS email alerts; three runbooks (queue backlog, booking latency, payment backlog)

**Day 10 — Sat 28 Nov**

- [ ] 1. Pre-scaling job 15 minutes before a sale; backpressure Lambda lowering the admission rate when p95 > 500 ms
- [ ] 2. Argo Rollouts canary for the booking API with automatic rollback on error rate
- [ ] 3. Security: GuardDuty, Security Hub, CloudTrail; ECR scan and Trivy gates; secrets rotation check
- [ ] 4. k6 runs at 10,000 then 50,000 virtual users; record join success, booking p95, oversold seats, cost
- [ ] 5. Base image upgrade for booking-api (clear the 3 HIGH ECR findings) and a build-deploy gate that fails on HIGH (added 20 Nov)

- [ ] **M5:** the 50,000-user test report shows the SLOs met with zero oversold seats, and a deliberately broken release rolls back on its own

## Phase 6 — Prove and present (Days 11–12) → M6

**Day 11 — Sun 29 Nov**

- [ ] 1. AWS FIS experiment: cut one AZ's subnets for 5 minutes during a k6 run; record lost orders (target 0)
- [ ] 2. Restore drill: point-in-time restore of RDS to a new instance; record the time as RTO
- [ ] 3. Azure: Static Web Apps status page; nightly backup copy to Blob Storage via GitHub Actions federated login
- [ ] 4. Cost report: total spend, cost per sale event from tags and Cost Explorer

**Day 12 — Mon 30 Nov**

- [ ] 1. README with architecture, results table, how to run, cost warning
- [ ] 2. Portfolio write-up and a 5-minute demo video (queue, sale, AZ failure, rollback)
- [ ] 3. Resume bullets with measured numbers; LinkedIn post
- [ ] 4. `make down` on demo; confirm the bill has stopped

- [ ] **M6:** the demo video, results and write-up are public and the AWS bill is back to near zero
