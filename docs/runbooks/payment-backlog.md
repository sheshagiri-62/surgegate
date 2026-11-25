# Runbook: payments or tickets backing up

**Alarms that link here:**
- `surgegate-<env>-payments-oldest-message-age` (> 60 s);
- `surgegate-<env>-tickets-oldest-message-age` (> 5 min);
- `surgegate-<env>-payments-dlq-not-empty`, `surgegate-<env>-tickets-dlq-not-empty`;
- `surgegate-<env>-consumers-failed-not-empty`.

**SLOs at risk:** 99% of paid orders confirmed within 60 s; 99% of ticket emails within 5 min.

## 1. What the buyer sees

- **Payments behind:** they paid, but the order page still says "confirming payment". Their hold
  is safe: an order with a captured payment is confirmed when the worker catches up, and the
  late-payment rule re-holds or refunds if the hold had expired.
- **Tickets behind:** the order is paid and the seats are theirs, but the email (and the PDF in
  "My tickets") arrives late.

**No money is lost while a queue waits.** Webhooks are on SQS; the order worker confirms each
payment exactly once by payment ID, so a replay is safe.

## 2. Check

1. **Dashboard** → *Payments + tickets*: queue depth and DLQs; *Ticket worker*: errors and p95.
2. **Order worker** (EKS):
   ```
   kubectl -n booking get pods -l app.kubernetes.io/component=order-worker
   kubectl -n booking logs deploy/booking-api-order-worker --since=15m
   ```
   The logs are JSON: look for `"level": "ERROR"`, `AccessDenied` (IAM), DB connection errors.
3. **Ticket worker** (Lambda):
   ```
   aws logs tail /aws/lambda/surgegate-<env>-ticket-worker --since 15m
   ```
   Common: `MessageRejected` (SES: recipient not verified in sandbox), S3 `AccessDenied`,
   `claimed elsewhere: retry` (another run is sending; normal for a few seconds).
4. **DLQ contents** (what failed and why):
   ```
   aws sqs receive-message --queue-url <dlq-url> --max-number-of-messages 5 --visibility-timeout 0
   ```

## 3. Fix

| Cause | Action |
| --- | --- |
| Order worker pod down or crash-looping | `kubectl -n booking rollout restart deploy/booking-api-order-worker`; for IAM errors, check `infra/envs/<env>/order_worker.tf` was applied |
| Payments arriving faster than one worker handles | Scale the worker: `kubectl -n booking scale deploy/booking-api-order-worker --replicas=2` (safe: exactly-once by payment ID) |
| Unknown order in a webhook | It lands in the payments DLQ by design (it can't be matched); check the provider's dashboard, then delete or redrive |
| SES rejected / throttled | Sandbox: verify the recipient, or request production access. Then redrive the tickets DLQ: every order gets exactly one email (claim + `ticket_email_sent_at`) |
| A bug in a worker | Fix, deploy, then **redrive** the DLQ: SQS console → DLQ → *Start DLQ redrive*, or `aws sqs start-message-move-task --source-arn <dlq-arn>` |
| Payment provider slow (no webhooks) | Nothing is queued, so the alarm won't fire; buyers' holds expire and seats return to sale. Consider pausing the waiting room until the provider recovers |

The 5-minute **ticket sweep** re-queues any paid order without an email, so even a lost message
gets its ticket.

## 4. After

- DLQs back to 0; the alarms return to OK by themselves.
- Check: `SELECT count(*) FROM orders WHERE status='paid' AND ticket_email_sent_at IS NULL` should
  be 0 after a few minutes.
- Record the time window and the number of orders affected.
