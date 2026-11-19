# ADR 002 — EventBridge + Kinesis instead of MSK for the sale-events stream

- **Date:** 2026-11-19
- **Status:** Accepted
- **Supersedes:** the "Event fan-out = Amazon MSK Serverless" row in the original blueprint

## Context

Every state change in a sale (`joined`, `admitted`, `pass_expired`, `seat_held`, `hold_released`,
`order_paid`, `ticket_issued`) is published once and read by three independent consumers:
`live-dashboard`, `analytics` and `audit`. Consumers need the events **ordered per sale event** and
must be able to **replay** them.

The blueprint chose Amazon MSK Serverless (Kafka). On Day 1 a read-only check showed that MSK is
blocked on the AWS Free plan:

```text
aws kafka list-clusters-v2 --cluster-type-filter SERVERLESS
An error occurred (SubscriptionRequiredException) when calling the ListClustersV2 operation:
The AWS Access Key Id needs a subscription for the service
```

Even on the Paid plan, MSK Serverless bills per cluster-hour and per partition-hour, needs VPC
networking and IAM SASL auth for every producer and consumer, and is the most complex piece in
Phase 4 for a project with a $50 budget and two days for that phase.

## Decision

Use **Amazon EventBridge (custom bus) + Amazon Kinesis Data Streams** for the sale-events stream.
SQS stays the job queue for joins, payments and tickets (unchanged).

- **Kinesis stream `sale-events`**: producers (queue Lambdas, booking API) write each event with
  partition key = sale event ID, so all records for one sale stay in order on one shard. The three
  consumers are Lambda functions with Kinesis event source mappings. They checkpoint by sequence
  number, ignore duplicates by message ID, and send failed batches to an SQS on-failure destination.
  Replay comes from the stream's retention period.
- **EventBridge custom bus**: the same events also go on the bus for AWS-side routing: rules for
  alarms and notifications, plus an archive for long-term replay.
- **Consumers are unchanged:** `live-dashboard` (WebSocket push), `analytics` (S3 + Athena), `audit`.
- The stream is created by Terraform (`events` module) only for work sessions, load tests and the
  demo, and destroyed by `make down`.

## Consequences

**Good**
- **Cost:** no MSK cluster-hours. Kinesis bills per shard-hour (or per stream-hour in on-demand mode)
  plus data, and the stream exists only while testing. EventBridge bills per event, with nothing
  charged while idle.
- **Simplicity:** no brokers, no Kafka client libraries, no VPC or SASL setup. Producers make one
  AWS SDK call, and consumers are plain Lambda event source mappings.
- Same guarantees the design needs: per-key ordering, several independent consumers, replay.

**Bad / trade-offs**
- Kafka on AWS is not shown in this project (it is already shown in LabForge).
- Kinesis retention is limited (24 h by default, extendable for extra cost), so long-term replay
  relies on the EventBridge archive and the analytics copy in S3.
- Each shard has a fixed write limit (1 MB/s or 1,000 records/s). At the demo's peak (about 850
  joins/s) one shard is close to its limit, so the load test must check for
  `ProvisionedThroughputExceededException`, and either use on-demand mode or more than one shard.
- **Precondition:** Kinesis Data Streams is also blocked on the Free plan. This decision depends on
  the account being on the Paid plan before Day 8 (upgrade done 19 Nov; confirm with
  `aws freetier get-account-plan-state` and `aws kinesis list-streams`).

## Alternatives considered

| Option | Why not |
| --- | --- |
| MSK Serverless (original) | Blocked on the Free plan; hourly cost and the most setup work |
| EventBridge only | No strict per-event ordering, and replay only through archives; kept as the fallback if Kinesis consumers slip (plan risk table) |
| SNS + SQS fan-out | Works for fan-out but has no ordered, replayable log for the audit consumer |
