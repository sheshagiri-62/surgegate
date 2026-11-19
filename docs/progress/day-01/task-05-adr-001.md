# Week 1 · Task 05 — ADR 001: why EKS, SQS for jobs + EventBridge/Kinesis for events, static buyer site

- **Date:** 2026-11-19
- **Phase / milestone:** Phase 1 (Foundations) → M1
- **Status:** Done
- **Commit / PR:** see PR link added below after opening

## 1. What the task was

Plan text: *"ADR 001: why EKS, SQS for jobs + EventBridge/Kinesis for events, static buyer site (copy
from the blueprint)."*

An Architecture Decision Record (ADR) writes down a big decision, why it was made and what was
rejected, so the reasoning isn't lost and anyone (including an interviewer) can follow it. These
three decisions shape every later phase.

## 2. What I did, step by step

1. Created branch `docs/adr-001` from `main`.
2. Read the blueprint's "Key design decisions" table, the "Sale events" section and the Design Q&A
   (the current version, with EventBridge + Kinesis instead of MSK).
3. Wrote `docs/adr/001-eks-sqs-eventbridge-kinesis-static-buyer-site.md` in the same format as ADR
   002 (Context → Decision → Consequences → Alternatives), linking ADR 002 for the MSK change.
4. Ticked the checklist and added the progress log line.

### Commands I ran

```bash
git switch main && git pull
git switch -c docs/adr-001
sed -n '295,336p' docs/blueprint.md
git add docs && git commit -m "docs: ADR 001 (EKS, SQS for jobs + EventBridge/Kinesis for events, static buyer site)"
git push -u origin docs/adr-001
gh pr create --base main --head docs/adr-001
```

### Files created or changed

| File | What it does |
| --- | --- |
| `docs/adr/001-eks-sqs-eventbridge-kinesis-static-buyer-site.md` | ADR 001 |
| `docs/progress/CHECKLIST.md`, `docs/progress/README.md` | Task 5 ticked and logged |

## 3. How it works

**What an ADR is.** A short document with a fixed shape: the *context* (the problem and the
constraints), the *decision*, the *consequences* (good and bad), and the *alternatives* that were
rejected. ADRs are numbered and never rewritten. If a decision changes, a new ADR supersedes it.
ADR 002 did exactly that for the MSK part of the original design.

**The three decisions in one line each:**
1. **EKS for the booking API.** Steady, admission-controlled traffic with long-lived database
   connections suits containers; EKS matches the target job roles; the cluster exists only during
   sessions.
2. **SQS for jobs, EventBridge + Kinesis for events.** A job (a join, a payment, a ticket) must be
   done once by one worker, with retries: that's SQS. An event (`seat_held`, `order_paid`) must
   reach several readers in order, with replay: that's Kinesis, plus EventBridge for AWS routing.
3. **Static buyer site.** 50,000 page loads at 12:00 come from the CloudFront cache, and the page
   becomes dynamic by calling the APIs. The low-traffic organiser dashboard is server-rendered.

**How it fits SurgeGate.** Together these keep the crowd away from the database: CloudFront absorbs
the reads, SQS absorbs the writes, and the admission valve sets how much load EKS and RDS see.

## 4. Errors I hit and how I fixed them

None.

## 5. How I verified it works

- Every claim in the ADR matches the current blueprint (decisions table, sale-events section,
  Design Q&A) and links ADR 002 for the MSK → Kinesis change.
- The pre-commit hooks passed on commit.

## 6. Cost impact

None. Documentation only.

## 7. Interview notes

- **Q:** Why not put jobs on Kinesis too and run one messaging system?
  **A:** A stream has no per-message retry or dead-letter queue: one bad record blocks its shard
  until it's handled. Payments and tickets need "retry this one message, then park it in a DLQ".
  Kinesis also bills by the hour, while SQS is free when idle.

- **Q:** If the buyer site is static, how do users see live queue positions?
  **A:** "Static" is about delivery: HTML and JS come from the CloudFront cache. The JavaScript
  then calls the APIs every few seconds. The shared "now serving" number is itself cached for 5
  seconds, so 5,000 polls/s cost a handful of origin calls.

- **Q:** EKS costs money even when idle. How did you justify it?
  **A:** The control plane and nodes exist only during work sessions and the demo, because
  Terraform builds them with `make up` and removes them with `make down`. The skills it shows (Pod
  Identity, Load Balancer Controller, Karpenter, Helm, Argo CD) are what the target roles ask for.

## 8. Next task

Day 2 · Task 1 — `eks` module: cluster, managed node group, Pod Identity, AWS Load Balancer
Controller. (Hourly cost: EKS control plane + nodes; plan shown before applying.)
