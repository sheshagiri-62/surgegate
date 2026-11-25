# Runbook: waiting-room backlog (joins not moving)

**Alarms that link here:**
- `surgegate-<env>-joins-oldest-message-age` (> 60 s);
- `surgegate-<env>-slo-queue-api-5xx-fast-burn`;
- `surgegate-<env>-queue-<fn>-errors` (join, admit, sequencer, valve);
- `surgegate-<env>-sale-events-write-throttled`.

**SLO at risk:** 99.9% of queue joins succeed. Buyers stuck on "joining…" also miss their place.

## 1. What the buyer sees

- **Joins stuck:** the page says "joining" and never shows a position.
- **5xx burn:** "Something went wrong, try again". A retry joins again, safely, because a join is
  idempotent per buyer.
- **Valve errors:** positions don't move, and "now serving" is frozen.

## 2. Check (5 minutes)

1. **Dashboard** `surgegate-<env>-sale-room` → section *Waiting room*:
   - *Join backlog*: are visible messages growing, and is the oldest age climbing?
   - *Queue Lambdas: errors + throttles*: which function?
   - *Lambda concurrency (account)*: near the account limit (1,000)? Then it's throttling.
2. **Logs** (Lambda logs are JSON):
   ```
   aws logs tail /aws/lambda/surgegate-<env>-queue-sequencer --since 15m --format short
   ```
   Look for `"level":"ERROR"`, `ProvisionedThroughputExceeded` (DynamoDB) or `AccessDenied`.
3. **The queue state** (DynamoDB `META` item for the event): `status`, `serving_up_to`,
   `admission_rate`.
4. **WAF**: is `RateLimitJoin` blocking real users (one carrier IP, CGNAT)? Section *Edge*,
   *WAF: blocked / challenged*.

## 3. Fix

| Cause | Action |
| --- | --- |
| Sequencer throttled (concurrency) | Raise its reserved concurrency, or ask for a higher account limit; messages wait in SQS and are processed in order, so nothing is lost |
| Sequencer erroring on a bad message | The message goes to `surgegate-<env>-joins-dlq` after the retries; inspect it and fix the code, then redrive |
| DynamoDB throttling | The table is on-demand; check for a hot key; contact AWS for a pre-warm before a big sale |
| Valve not ticking | Check its EventBridge Scheduler schedule `surgegate-<env>-queue-valve` (and `-queue-starter` for opening) is enabled; invoke the valve Lambda once by hand |
| WAF over-blocking joins | Raise `join_limit_per_min` (infra/modules/waf) and apply |
| Kinesis writes throttled | Buyers aren't affected (events are best-effort); for a big sale use ON_DEMAND (demo already does) |

If the backlog keeps growing: **pause admissions** from the organiser dashboard. Joins are still
accepted, so nobody loses their place. Then fix, and resume.

## 4. After

- Check the DLQ is empty again: `aws sqs get-queue-attributes --queue-url <joins-dlq> --attribute-names ApproximateNumberOfMessages`.
- Note the start and end time, the cause and the fix in the incident log for the sale.
