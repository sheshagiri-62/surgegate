# Week 2 · Day 9 Task 4 — SLO alarms, SNS alerts, runbooks (+ budget fix)

- **Date:** 2026-11-25
- **Phase / milestone:** Phase 5 → M5
- **Status:** Done
- **Commit / PR:** [#64](https://github.com/sheshagiri-62/surgegate/pull/64) (alarms + runbooks),
  [#65](https://github.com/sheshagiri-62/surgegate/pull/65) (budget in Terraform)

## 1. What the task was

Plan, Day 9 Task 4: *"SLO alarms from the blueprint; SNS email alerts; three runbooks (queue
backlog, booking latency, payment backlog)."* An alarm is only useful if someone is told and
knows what to do, so each alarm emails and links its runbook.

## 2. What I did, step by step

1. **14 alarms** in `infra/modules/observability/alarms.tf`, all to the existing SNS topic
   `surgegate-dev-alerts` (confirmed email subscription):

   | SLO (blueprint) | Alarm |
   | --- | --- |
   | Joins 99.9% successful | `slo-queue-api-5xx-fast-burn`: 5xx > 1.44% over 5 min (14.4 × the 0.1% budget), at least 100 requests; `queue-{join,admit,sequencer,valve}-errors`: errors + throttles in 2 of 3 min |
   | Booking p95 < 500 ms | `slo-booking-p95-latency`: p95 > 0.5 s in 3 of 5 min; `booking-5xx-rate` > 1%; `booking-no-healthy-targets` |
   | Paid orders confirmed within 60 s (99%) | `payments-oldest-message-age` > 60 s |
   | Ticket email within 5 min (99%) | `tickets-oldest-message-age` > 300 s |
   | Queue keeps moving | `joins-oldest-message-age` > 60 s |
   | Supporting | `rds-cpu-high` > 80%, `rds-connections-high` > 70, `sale-events-write-throttled` > 0 |
   | (existing) | DLQ alarms: payments, tickets, consumers-failed |

   "0 oversold seats" isn't an alarm: the database makes it impossible (row locks + constraint),
   and the load test checks it.
2. **Three runbooks** in `docs/runbooks/`: `queue-backlog.md`, `booking-latency.md`,
   `payment-backlog.md`. Each has: what the buyer sees, a 5-minute check (dashboard → logs →
   traces), a cause → action table, and the "after" steps.
3. **Budget fix (your yes):** the Day-1 budget `surgegate-monthly` was created by hand and
   **included credits**, so it showed $0.00 while usage before credits was about $15, and no alert
   could fire.
   - Imported into `infra/bootstrap`, now counting usage before credits.
   - Exact alerts at $15 / $30 / $45, plus a forecast > 100% alert.
   - Recipients only in the uncommitted `budget.auto.tfvars`.
4. **WAF immunity 3,600 s** (your request; #65).

### Commands I ran

```bash
terraform -chdir=infra/envs/dev plan <up vars> -out=alarms.tfplan   # 14 to add
terraform -chdir=infra/envs/dev apply alarms.tfplan
aws cloudwatch set-alarm-state --alarm-name surgegate-dev-joins-oldest-message-age --state-value ALARM --state-reason "test"
aws cloudwatch describe-alarm-history --alarm-name surgegate-dev-joins-oldest-message-age --history-item-type Action
terraform -chdir=infra/bootstrap plan -out=budget.tfplan             # 1 import, 1 change
terraform -chdir=infra/bootstrap apply budget.tfplan
terraform -chdir=infra/bootstrap plan                                # without the tfvars: No changes
```

### Files created or changed

| File | What it does |
| --- | --- |
| `infra/modules/observability/alarms.tf`, `variables.tf` | The 14 alarms |
| `infra/envs/dev/main.tf` | Alarms → `module.async.alerts_topic_arn` |
| `docs/runbooks/*.md` | Three runbooks |
| `infra/bootstrap/budget.tf`, `variables.tf` | Imported budget, usage before credits, $15/$30/$45 |
| `infra/modules/waf/variables.tf` | Challenge immunity 3,600 s |

## 3. How it works

An **SLO** (service level objective) is a promise like "99.9% of joins succeed". The 0.1% that may
fail is the **error budget**. A **burn-rate** alarm asks how fast we're spending it: errors at
14.4 × the allowed rate would use a month's budget in about 2 days, which deserves a page now. A
small blip doesn't fire it (at least 100 requests are needed in the window).

Queue-based SLOs ("confirmed within 60 s") are watched through the **age of the oldest message**:
if the oldest payment has waited over 60 s, the SLO is being missed right now, whatever the cause.

**Alarm → SNS → email:** CloudWatch publishes the change (ALARM and back to OK) to an SNS topic,
which emails the subscriber. The description names the runbook.

**Why the budget was broken:** AWS Budgets can count costs after credits. With $140 of credits,
"actual" stays $0 until the credits run out, so the $15/$30/$45 alerts would never warn us about
our own $50 limit. Counting usage before credits makes the alerts track what we actually use.

## 4. Errors I hit and how I fixed them

| # | Error (exact message) | Cause | Fix |
| --- | --- | --- | --- |
| 1 | (caught before commit) runbook named schedules `surgegate-<env>-queue-tick*` | Guessed; they're `-queue-valve` and `-queue-starter` | Grepped the module; fixed the text |
| 2 | (finding) budget `ActualSpend 0.0` with `IncludeCredit: true` | Created by hand on Day 1 with credits included | Imported, `include_credit = false` → actual **$15.73**, forecast **$23.92** |
| 3 | The budget import plan **printed the alert email** in its local output (removed notifications) | The existing values in AWS weren't marked sensitive | Deleted that output file. Applied locally first, so state now marks them sensitive. Added `ignore_changes = [notification]`, because CI has no tfvars and would otherwise post the diff in a PR comment. Checked: a plan without the tfvars → **No changes**, 0 `@` in the output |
| 4 | 10 alarms `INSUFFICIENT_DATA` right after creation | No traffic yet on those metrics (normal) | None needed; they go OK/ALARM as data arrives |

## 5. How I verified it works

- `set-alarm-state ALARM` on `joins-oldest-message-age` → alarm history:
  **`Successfully executed action arn:aws:sns:ap-south-1:968077439619:surgegate-dev-alerts`**; the
  SNS subscription is `email`, confirmed; the test email should be in your inbox.
- States after creation: 6 OK, 10 INSUFFICIENT_DATA (no traffic), 1 ALARM (the test).
- Budget: `IncludeCredit: false`, notifications ACTUAL 15 / 30 / 45 (ABSOLUTE_VALUE) + FORECASTED
  100%, 1 subscriber each. **Actual $15.73**, so the $15 alert is due, and it's real.

## 6. Cost impact

Alarms: 9 single-metric + 5 metric-math (12 metrics) × $0.10/metric-month ≈ **$2.10/month**
(prorated). Budgets: the first 2 are free. SNS email: free at this volume.

## 7. Interview notes

- **Q:** Why a burn-rate alarm instead of "error rate > 0.1%"?
  **A:** A plain threshold at the SLO fires on every short blip and trains people to ignore it. A
  burn rate fires only when we'd run out of error budget soon (14.4 × = budget gone in ~2 days),
  so pages mean real trouble. A slow-burn alarm over hours can catch the rest.
- **Q:** How do you alarm on "paid orders confirmed within 60 s"?
  **A:** On the age of the oldest message in the payments queue: every webhook goes through that
  queue, so if the oldest one is over 60 s, someone's confirmation is late right now, whatever
  the cause (worker down, DB slow, poison message).
- **Q:** Your budget alerts showed $0. Why, and why does it matter?
  **A:** They counted costs after credits. A budget's job is to warn before you overspend, so it
  should track usage before credits; otherwise you find out when the credits run out and the bill
  arrives.

## 8. Next task

Day 10 Task 1: pre-scaling 15 minutes before a sale + the backpressure Lambda (admission rate
down when booking p95 > 500 ms).
