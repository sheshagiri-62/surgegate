# Week 2 · Day 8 · Task 03b — Consumers (2 of 3): analytics (S3 + Athena), lean

- **Date:** 2026-11-25 (early hours IST)
- **Phase / milestone:** Phase 4 (analytics is on the cut list; kept lean)
- **Status:** Done, verified with Athena on real data.
- **Commit / PR:** [#55](https://github.com/sheshagiri-62/surgegate/pull/55)

## 1. What the task was

Plan, Day 8 Task 3: *"… analytics (S3 + Athena table) …"*. Blueprint: *"Writes events to S3 for
Athena queries (sales per minute, drop-off from queue to purchase)."*

## 2. What I did

1. **Sequencer check (before analytics, as you asked):**
   - Mapping: `MaximumBatchingWindowInSeconds` **already 1**, batch 100,
     `ScalingConfig.MaximumConcurrency` 2, no reserved or provisioned concurrency.
   - Queue: `DelaySeconds` 0, long poll 20 s.
   - So **nothing to change.** The before/after measurements are in §5.
2. **`sg_consumers/analytics.py`:** each Kinesis batch becomes one gzip JSON-lines object per
   event-time hour, with a **deterministic key** (`<shard>-<first seq>-<last seq>`), so a
   retried batch overwrites the same object. Rows are flat:
   `id, type, sale_event_id, at, seq, sub, seats, amount_paise, data`.
3. **Infra:**
   - an `analytics` bucket (same hardening as the others);
   - the Lambda and its Kinesis mapping (TRIM_HORIZON back-fill, batch 500, 60 s window);
   - a Glue table with **partition projection** (dt/hour, no crawler);
   - an Athena workgroup (enforced, **100 MB scan cap per query**, SSE-KMS results);
   - saved queries `sales-per-minute` and `queue-to-purchase-funnel`, both de-duplicating by
     `id`.
4. **Fix found live:** the back-fill discarded old records (Errors #1). Fixed, the mapping
   replaced with your OK, and the records re-read.
5. **Docs:**
   - 3a's target is now "updates within 5 s (p95)", cause recorded;
   - the Task 1 report has your phone-scan result and the inbox note.

## 3. How it works

**Simply:** every few seconds of sale events become a small compressed file in S3, filed by day
and hour. Athena runs SQL straight over those files. Glue only describes the columns and where
the files are, and "partition projection" tells it the day/hour folder pattern, so nothing has
to scan the bucket for new folders. A file name is fixed by which records it holds, so writing
the same batch again replaces the file instead of adding a copy. Queries also count each
message ID once.

## 4. Errors I hit and how I fixed them

| # | Error (exact message) | Cause | Fix |
| --- | --- | --- | --- |
| 1 | `consumers-failed` received `RecordAgeExceeded` for `surgegate-dev-events-analytics`, batch 38 (first arrival 2026-11-23T19:32:23Z, last 2026-11-24T18:11:00Z); alarm **ALARM** | My config copied `maximum_record_age_in_seconds = 3600` from the live dashboard, so Lambda **discarded** every record older than 1 hour, which is exactly what a TRIM_HORIZON back-fill needs to keep. The on-failure path caught it, so nothing was lost silently. | `-1` (keep as long as the stream does); `terraform plan -replace=…analytics[0]` (1 add / 1 destroy, approved) to re-read from TRIM_HORIZON; purged the pointer; alarm **OK** 19:53 UTC |
| 2 | `bash: bc: command not found` (my record counter printed 0) | Git Bash has no `bc` | Counted with Athena instead |
| 3 | `AWS.SimpleQueueService.NonExistentQueue` | I guessed the joins queue name (`surgegate-dev-queue-joins`) | The real name is `surgegate-dev-joins` |

## 5. How I verified it works

- **Tests:** event-consumers 12 passed (3 new: per-hour objects with flat rows; a retry overwrites
  the same object, so no copies; an S3 failure retries the whole batch). CI 12/12 green; dev plan
  **No changes** after the apply.
- **Athena on real data** (workgroup `surgegate-dev-analytics`):
  - `count(*)` = **39** rows, `count(DISTINCT id)` = **34**. The 5 extra rows are the records I
    deliberately re-put during the 3a duplicate test (same IDs). The queries count them once.
  - **Re-reading after the replace did not add copies.** The hour-19 batch got the same
    deterministic key and overwrote the first object (otherwise 41 rows).
  - **Funnel:**

    | Sale | Joined | Admitted | Held | Paid | Joined → paid |
    |---|---|---|---|---|---|
    | `24052880` | 3 | 1 | 1 | 1 | 33.3% |
    | `9abf74ae` | 0 | 0 | 7 | 5 | — (buyers got passes minted directly in earlier tests, not via the queue) |

  - **Sales per minute** (`24052880`): 18:10 UTC, 2 seats, ₹3,000, 1 order.
  - Every query **scanned 5.7 KB** (cap 100 MB).
- **Sequencer before/after** (no setting changed; the window was already 1 s):

  | Join | Position assigned after |
  |---|---|
  | Earlier, idle queue | ~21 s (join done 18:09:34.9 → sequencer 18:09:55.0) |
  | Now, idle queue | 11.5 s (cold sequencer) |
  | Warm, 5 s later | 5.9 s |

  **Cause:** the first message after the SQS queue sits idle waits for Lambda's poller, plus a
  cold start. In a real sale, early arrivals sit in the pre-queue and are shuffled at the start
  anyway. For the load test, warm the queue with one synthetic join just before the sale.

## 6. Cost impact

Nothing hourly.

| Item | Cost |
|---|---|
| S3 (a few KB) | Cents |
| Athena | $5/TB scanned; 5.7 KB per query, capped at 100 MB |
| Glue catalog | Free tier |
| Lambda | Free tier |

Shard readers are now 3 (Pipe, dashboard, analytics), under the 5 reads/s limit.

## 7. Interview notes

- **Q:** How do you avoid duplicates in a data lake fed by an at-least-once stream?
  **A:** Two layers. A deterministic object key per batch (shard + sequence range) means a
  retried batch replaces its own file, which was verified: the re-read didn't add rows. A unique
  message ID per event means queries can `SELECT DISTINCT id` when a batch was split
  differently. Here 39 rows held 34 distinct events, and the reports count 34.
- **Q:** Why partition projection?
  **A:** Without it, every new day/hour folder must be added to the catalog by a crawler or
  `MSCK REPAIR`. Projection describes the folder pattern once. Athena computes the partitions
  and prunes them from the `WHERE dt >= …` filter, with nothing to run or pay for.
- **Q:** What did the `RecordAgeExceeded` incident show?
  **A:** One setting can be right for one consumer and wrong for another: one hour is fine for a
  live dashboard, and fatal for a back-fill. The on-failure destination and alarm turned a silent
  data loss into a visible one with a precise pointer (shard and time range).

## 8. Next

Task 3c, **audit** (lean): a hash chain per sale in DynamoDB (conditional put, so duplicates are
ignored), a `verify_audit.py` that reports the first broken link, and a tamper test. The Object
Lock anchor is future work, as you decided.
