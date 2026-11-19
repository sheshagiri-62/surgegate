# ADR 001 — EKS for booking, SQS for jobs + EventBridge/Kinesis for events, static buyer site

- **Date:** 2026-11-19
- **Status:** Accepted
- **Source:** blueprint, "Key design decisions" and "Design Q&A"
- **Related:** [ADR 002](002-eventbridge-kinesis-instead-of-msk.md) (why the event stream is Kinesis, not MSK)

## Context

SurgeGate must survive a flash sale: about 50,000 fans arriving within 5 minutes of 12:00, about
850 joins/s at peak, about 5,000 position polls/s, while selling 5,000 seats exactly once. Three
architecture choices shape everything else and need to be settled before the first module is
built:

1. Where the **booking API** (seat map, holds, checkout, orders) runs.
2. How work moves between components: **jobs** that must be done once each (joins, payments,
   tickets) versus **events** that several readers need (live dashboard, analytics, audit).
3. How the **buyer website** is served when the whole crowd loads it at the same second.

Constraints: one developer, 12 days, under $50 of AWS spend, and the project should show the skills
AWS DevOps / platform roles ask for.

## Decision

### 1. Booking API on Amazon EKS

The FastAPI booking service runs as a Docker container on **EKS** (managed node group in 2 AZs,
Karpenter in the demo), deployed with Helm and Argo CD behind an ALB from the AWS Load Balancer
Controller. The organiser SSR dashboard runs on the same cluster.

- Booking traffic is steady (the admission valve fixes it at about 125 buyers/min) and holds
  long-lived PostgreSQL connections. A container service fits this better than per-request
  functions.
- EKS is what AWS DevOps and platform job descriptions ask for, and Helm / Argo CD skills (already
  shown in LabForge) carry over. The new learning is the AWS side: Pod Identity, the Load Balancer
  Controller and Karpenter.
- The cost is the control-plane charge, so Terraform creates the cluster only for work sessions and
  the demo (`make up` / `make down`).

### 2. SQS for jobs, EventBridge + Kinesis for events

- **SQS** carries every job that must be done **exactly once by one worker**: queue joins, payment
  webhooks, ticket generation. It provides per-message retries and dead-letter queues, absorbs
  bursts (a join answers 202 at once and waits in the queue), and costs nothing when idle.
- **Kinesis Data Streams** (`sale-events`) carries every sale state change (`joined`, `admitted`,
  `seat_held`, `order_paid`, …) that **several consumers** read and may replay. The partition key is
  the sale event ID, so each sale's events stay in order on one shard. The consumers are the
  `live-dashboard`, `analytics` and `audit` Lambdas.
- An **EventBridge custom bus** gets the same events for AWS-side routing (alarms, notifications,
  archive).
- Jobs never go on the stream, and events never go on a job queue. A stream has no per-message
  retry or dead-letter queue, and a job queue can't serve several independent, replaying readers.

### 3. Static buyer site, server-rendered organiser site

- The **buyer** app (Next.js) is built as **static files on S3 + CloudFront**. The HTML and
  JavaScript come from the edge cache, then the page calls the APIs (queue position, seats,
  payment) and updates every few seconds. "Static" is how the files are delivered, not what the
  page does.
- 50,000 page loads at 12:00 are served by CloudFront and never touch EKS. The "now serving"
  counter is also cached at CloudFront for 5 seconds, so 5,000 polls/s become a handful of origin
  calls.
- The **organiser** dashboard is low traffic and needs fresh, logged-in data on every load, so it is
  server-rendered (SSR) on EKS.

## Consequences

**Good**
- The size of the crowd never reaches the database. Load on EKS and RDS is set by the admission
  rate, which can be tested and guaranteed.
- Each tool does one job: SQS for exactly-once work, Kinesis for ordered fan-out with replay,
  CloudFront for read traffic.
- Idle cost is close to zero: SQS, EventBridge, S3 and CloudFront bill by use, and EKS and Kinesis
  exist only while testing.

**Bad / trade-offs**
- EKS adds operational work (cluster add-ons, IAM for pods, upgrades) and an hourly control-plane
  charge compared with ECS Fargate.
- Two messaging systems (SQS and Kinesis) to learn, monitor and alarm on instead of one.
- The buyer app can't render per-user HTML on the server. Everything personal is loaded by API
  calls after the page appears.

## Alternatives considered

| Decision | Alternative | Why not |
| --- | --- | --- |
| Booking platform | ECS Fargate | Simpler and has no control-plane charge, but adds less for the target roles; Helm and Argo CD wouldn't carry over |
| Booking platform | Lambda | Long-lived DB connections and steady traffic suit containers; the queue side already uses Lambda for the spiky part |
| Job queues | Kafka / Kinesis for jobs too | No per-message retry or dead-letter queue, and bills hourly even when idle |
| Event fan-out | Amazon MSK (Kafka) | Blocked on the Free plan, bills hourly, and needs the most setup; see ADR 002 |
| Event fan-out | SNS + SQS | Fan-out without an ordered, replayable log for the audit consumer |
| Buyer frontend | Next.js SSR on EKS | Every page load would hit EKS at the worst moment of the sale |
| Organiser frontend | Static export | Works, but loads data after the page appears; SSR is cheap at organiser traffic levels |
