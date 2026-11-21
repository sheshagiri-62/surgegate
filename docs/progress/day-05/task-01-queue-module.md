# Week 1 · Day 5 · Task 01 — `queue` module: API Gateway, `join` Lambda writing to SQS, `sequencer` Lambda assigning positions in batches into DynamoDB

- **Date:** 2026-11-21 (evening of Day 3; Days 5–6 brought forward while CloudFront verification is pending)
- **Phase / milestone:** Phase 3 (Waiting room) → M3
- **Status:** Done
- **Commit / PR:** see the Day 5 summary (`feat/queue-module`)

## 1. What the task was

Plan text: *"`queue` module: API Gateway, `join` Lambda writing to SQS, `sequencer` Lambda assigning
positions in batches into DynamoDB."* This is the front of house: it must accept tens of thousands
of joins at 12:00 without any of them touching the booking database.

## 2. What I did, step by step

1. **DynamoDB table `surgegate-dev-queue`**, in the `data` module as the plan's layout says, and
   persistent ("data between sessions: RDS snapshot + DynamoDB tables"):
   - on-demand billing;
   - single-table keys from the blueprint: `PK = EVENT#<id>`, with `SK = META` (state) or
     `USER#<sub>` (entry);
   - TTL on `expires_at`, deletion protection on, encrypted with the AWS-owned key.
2. **New module `infra/modules/queue`:**
   - **API Gateway HTTP API**, pay per request. Its built-in **JWT authorizer** checks the Cognito
     access token (signature, issuer, expiry, client) before any Lambda runs.
   - Route `POST /queue/{event}/join`.
   - Stage throttling at 1,000 rps (burst 2,000) as a cost and abuse cap; CORS for
     `localhost:3000`; JSON access logs kept 7 days.
   - **SQS `joins`** (long polling, SSE) plus a **dead-letter queue** (after 5 failures, 14-day
     retention). Visibility timeout = 6 × the sequencer timeout (AWS guidance).
   - **Lambdas `join` and `sequencer`:** python3.12, arm64, one zip built with a fixed file mode,
     JSON logs kept 7 days, **one IAM role each with least privilege**:
     - join: `sqs:SendMessage` and `dynamodb:GetItem`;
     - sequencer: SQS receive/delete and `dynamodb:UpdateItem`/`PutItem`.
   - **Event source mapping:** batches of up to 100 messages with a 1 s window, partial-batch
     failure reporting, and at most 2 sequencers in parallel (the account's Lambda limit is 10).
3. **Code in `services/queue/src/sg_queue`** (standard library + boto3 only):
   - `join.py`: buyer role check; queue state read with a **5 s in-memory cache**, so a burst of
     joins doesn't become a burst of reads; message on SQS; **202** with a `request_id`.
   - `sequencer.py`: groups the batch by event and orders it by `joined_at`. **One
     `ADD next_position :n` per event per batch** reserves a block of positions, then each entry is
     written. A bad message is reported on its own and doesn't fail the batch.
4. **`tools/open_queue.py`:** a dev tool that creates an event's queue `META` item, until the
   organiser endpoint arrives (Day 6 Task 1).
5. **Tests:** 6 with moto (DynamoDB and SQS), plus a new CI job.
6. **Lambda concurrency quota:** the account limit is **10**. With your approval I requested
   **1,000** (Service Quotas request `c57e030e…`, status PENDING), which is needed for Day 6's
   1,000-user k6 run.

### Commands I ran

```bash
aws lambda get-account-settings                       # ConcurrentExecutions: 10
aws service-quotas get-service-quota --service-code apigateway --quota-code L-8A5B8E43   # 10000 rps
py -3.12 -m venv .venv && pip install -r requirements-dev.txt
ruff format . && ruff check --fix . && pytest -q       # 6 passed
terraform fmt -recursive infra && terraform -chdir=infra/envs/dev validate && tflint
terraform -chdir=infra/envs/dev plan … -out=queue.tfplan          # 19 to add
aws pricing get-products --service-code AmazonApiGateway|AmazonDynamoDB …
terraform -chdir=infra/envs/dev apply queue.tfplan                 # approved
aws service-quotas request-service-quota-increase --service-code lambda --quota-code L-B99A9384 --desired-value 1000
python tools/open_queue.py <event> --rate 125 --status open        # error 1 first
python qcheck.py      # API checks: 401/401/403/404/202
python … send 300 synthetic joins straight to SQS; read positions back
MSYS_NO_PATHCONV=1 aws logs filter-log-events --log-group-name /aws/lambda/surgegate-dev-queue-sequencer --filter-pattern '"placed"'
```

### Files created or changed

| File | What it does |
| --- | --- |
| `infra/modules/data/main.tf`, `variables.tf`, `outputs.tf` | DynamoDB queue table |
| `infra/modules/queue/main.tf`, `variables.tf`, `outputs.tf`, `versions.tf` | HTTP API + JWT authorizer, SQS + DLQ, Lambdas, IAM, logs |
| `infra/envs/dev/main.tf`, `outputs.tf` | `module "queue"`; `queue_api_endpoint`, `queue_table` outputs |
| `services/queue/src/sg_queue/common.py`, `join.py`, `sequencer.py` | Lambda code |
| `services/queue/tests/*`, `pytest.ini`, `requirements-dev.txt` | moto tests |
| `services/queue/tools/open_queue.py` | Dev tool: open a queue |
| `ruff.toml` | `sg_queue` as first-party |
| `.github/workflows/ci.yml` | `queue` job |

## 3. How it works

**Why a queue in front of a queue?** At 12:00 everyone presses "Join" in the same second. If each
join wrote to a database, the database would have to absorb the whole spike. Instead, the join
Lambda only drops a small message on SQS and answers "202 Accepted" right away; SQS absorbs any
burst. The sequencer then drains SQS at its own steady pace.

**Batching positions.** Positions come from one counter per event. If every join updated that one
counter item, it would become a *hot key*: thousands of writes per second to a single item. The
sequencer takes up to 100 joins at once and makes **one** atomic `ADD next_position 100`, which
reserves positions 1–100 for that batch, so the counter sees one write per batch rather than one
per person. On real AWS, 300 joins needed just 7 counter updates.

**Security before code.** API Gateway's JWT authorizer rejects missing, forged or expired Cognito
tokens itself (401), so attackers' requests never even start a Lambda, and we don't pay for them.

## 4. Errors I hit and how I fixed them

| # | Error (exact message) | Cause | Fix |
| --- | --- | --- | --- |
| 1 | `botocore.exceptions.MissingDependencyException: Missing Dependency: Using the login credential provider requires an additional dependency. You will need to pip install "botocore[crt]" before proceeding.` | Python's boto3 can only use `aws login` credentials with the CRT extra (the Lambdas don't need it: they use role credentials) | `botocore[crt]==1.44.9` in the queue service's dev requirements |
| 2 | `aws logs filter-log-events`: `Value at 'logGroupName' failed to satisfy constraint: Member must satisfy regular expression pattern` | Git Bash rewrote `/aws/lambda/…` into a Windows path | `MSYS_NO_PATHCONV=1` |
| 3 | `/usr/bin/bash: -c: line 95: unexpected EOF while looking for matching ''` | Heredoc quoting in a long command (same as Day 3) | Wrote the files with the editor tool |
| 4 | tflint: `data "aws_region" "current" is declared but not used` | Leftover data source | Removed |

## 5. How I verified it works

| Check | Result |
| --- | --- |
| Unit tests (moto) | 6 passed: join → 202 and only an SQS message (no table write); organiser 403, unknown/invalid event 404, closed queue 409; **25 joins → positions 1–25 in join order with ONE counter update**; next batch continues at 4–6; mixed events + a bad message → only the bad one retried; unknown event retried, not lost |
| Apply | 19 added; `queue_api_endpoint = https://ed4hbsgtq9.execute-api.ap-south-1.amazonaws.com` |
| Real API Gateway | no token → `401 Unauthorized`; garbage token → `401`; organiser → `403 buyer role required`; unknown event → `404 no waiting room for this event`; **buyer-1 → `202` in 284 ms** |
| Real sequencer | buyer-1's entry at **position 1** about 6 s later, `request_id` matches, `next_position = 1` |
| Burst (300 joins straight to SQS) | 300 entries in 30 s, **positions 1–300 unique and without gaps**; sequencer logs: **7 batches** (27, 53, 44, 4, 100, 46, 26), 0 failures |

## 6. Cost impact

No hourly cost. Per request in ap-south-1:
- API Gateway HTTP about $1.3 per million;
- DynamoDB $0.71 per million writes and $0.14 per million reads;
- Lambda and SQS within the free tier;
- logs kept 7 days.

Tonight's tests cost well under $0.01. An idle month costs about $0, plus pennies for storage.

## 7. Interview notes

- **Q:** How does the queue survive 50,000 joins in one second?
  **A:** The join path does no database work: API Gateway checks the token, and the Lambda puts a
  message on SQS and returns 202. SQS absorbs the burst, and a sequencer drains it in batches. The
  database never sees the spike.
- **Q:** How do you hand out positions without a hot counter?
  **A:** One atomic `ADD next_position n` per batch of up to 100 reserves a block, and each joiner
  takes the next number in it. 300 joins needed 7 counter writes. DynamoDB's conditional and atomic
  updates keep it correct even with two sequencers in parallel.
- **Q:** What happens if a join message can't be processed?
  **A:** The sequencer reports just that message as failed (partial batch response), SQS retries
  it, and after 5 tries it goes to a dead-letter queue to be inspected. The rest of the batch isn't
  affected.

## 8. Next task

Day 5 Task 2 — One place per account (conditional write); pre-queue shuffle at sale start.
