# Week 2 · Day 7 · Task 02 — Step Functions hold timer: wait 10 minutes, release only if still held by the same hold

- **Date:** 2026-11-24
- **Phase / milestone:** Phase 4 → M4 ("an unpaid hold is released after 10 minutes")
- **Status:** Done. Verified live (with a 60-second wait instead of 600 so the test is quick).
- **Commit / PR:** [#42](https://github.com/sheshagiri-62/surgegate/pull/42) (squash `fe155df`),
  deployed by `8242122 ci: deploy booking-api fe155df99955`

## 1. What the task was

Plan, Day 7 Task 1: *"Step Functions hold timer: wait 10 minutes, release only if still held by
the same hold."* A hold reserves seats for 10 minutes while the buyer pays. If the buyer never
pays, the seats must go back on sale by themselves, but a seat that was **paid for**, or that
**another buyer** holds now, must never be touched.

## 2. What I did, step by step

1. **Release worker** (`services/workers`, a new Python package): one transaction frees the
   seats still held by this hold and marks the hold `released`. It then publishes
   `hold_released` on the Kinesis sale-events stream, but only if something was released.
   - Uses pg8000, a pure-Python PostgreSQL driver vendored into the zip, so there are no native
     builds for Lambda's arm64.
   - Reads the RDS-managed secret.
   - Connects with TLS, using the RDS CA bundle.
2. **Booking API:** after a hold commits, it starts one Step Functions execution **named by the
   hold ID**. If the timer cannot start, the API releases the hold at once and returns 503, so a
   hold can never stay forever.
3. **Infrastructure:** a new `infra/modules/async` module (the plan's layout puts Step Functions
   and the workers there). It contains:
   - a Standard state machine: `Wait (SecondsPath $.wait_seconds)` → `Release` Lambda, with 6
     retries;
   - the release Lambda in the private subnets, with its own security group;
   - that security group allowed into PostgreSQL;
   - IAM roles with the smallest rights needed;
   - `states:StartExecution` added to the booking-api pod role.
4. **CI:** a new `workers` job. It builds the schema with the booking API's own Alembic
   migrations, then runs the worker tests against it.
5. Plan, then apply after approval (12 added, 1 changed), then a PR. CI showed drift, which led
   to a real bug fix (see Errors). Merge after approval; Argo CD rolled out the new image.
6. Live test inside a booking-api pod, using the app's own code and the pod's IAM role:
   1. Hold a real seat.
   2. Start the timer with a 60-second wait.
   3. Watch it release the seat.

### Commands I ran

```bash
# workers tests against a local PostgreSQL migrated by the booking API's alembic
cd services/booking-api && DATABASE_URL=postgresql+psycopg://...@localhost:15432/workers_test alembic upgrade head
cd services/workers && pytest -q            # 5 passed
cd services/booking-api && pytest -q        # 101 passed

# infrastructure (Windows: terraform runs through cmd so it keeps the environment)
terraform fmt -recursive infra
terraform -chdir=infra/envs/dev init
terraform -chdir=infra/envs/dev validate
(cd infra/modules/async && tflint --config=../../../.tflint.hcl)
terraform -chdir=infra/envs/dev plan -var=enable_nat_gateway=true -var=enable_eks=true \
  -var=enable_data=true -var=enable_kinesis=true \
  -var=restore_snapshot_id=surgegate-dev-pg-final-873e7969 -out=async.tfplan   # 12 add, 1 change
terraform -chdir=infra/envs/dev apply async.tfplan                              # after your "yes"

# smoke test: Lambda -> RDS (unknown hold, nothing to release)
aws lambda invoke --function-name surgegate-dev-hold-release \
  --payload '{"hold_id":"<random uuid>","event_id":"<random uuid>"}' out.json

git commit -m "feat: 10-minute hold timer - Step Functions + release worker (Day 7 Task 2)"
git push -u origin feat/hold-timer && gh pr create ...                          # PR #42
gh pr checks 42 --watch

# fix found by CI (see Errors)
git check-ignore -v services/workers/src/sg_workers/rds-global-bundle.pem   # .gitignore:28:*.pem
git commit -m "fix: track the public RDS CA bundle ..."                     # .gitignore negation
git ls-files --eol services/workers/src | grep w/crlf                       # 5 pip RECORD files
rm <those files> && git checkout -- <those files>                           # back to LF
terraform -chdir=infra/envs/dev plan ... -out=sync.tfplan                   # same hash as CI
terraform -chdir=infra/envs/dev apply sync.tfplan                           # after your "yes"
gh pr merge 42 --squash
gh run watch 45248899775                                                    # build-deploy: success
kubectl -n booking rollout status deploy/booking-api                        # image fe155df99955

# live check inside the pod (scratchpad script hold_live.py: list / hold / check)
kubectl -n booking exec -i <pod> -- python - hold 9abf74ae-c14f-46e1-9e8f-8ee9872b7995 < hold_live.py
aws stepfunctions describe-execution --execution-arn ...:execution:surgegate-dev-hold-timer:cf0ba751-...
aws stepfunctions get-execution-history --execution-arn ...
kubectl -n booking exec -i <pod> -- python - check cf0ba751-007d-446a-a091-1c13b5c73f51 < hold_live.py
aws logs filter-log-events --log-group-name /aws/events/surgegate-dev-sale-events --filter-pattern '"cf0ba751-..."'
```

### Files created or changed

| File | What it does |
| --- | --- |
| `services/workers/src/sg_workers/release_hold.py` | Release in one transaction; publishes `hold_released`; Lambda handler |
| `services/workers/src/sg_workers/db.py` | Connects with pg8000: RDS lookup, managed secret, TLS with the CA; one retry |
| `services/workers/src/sg_workers/_vendor/` | Vendored pg8000 and its pure-Python dependencies |
| `services/workers/src/sg_workers/rds-global-bundle.pem` | Public AWS RDS CA certificates (no keys) |
| `services/workers/tests/test_release_hold.py` | 5 tests: unpaid released, sold untouched, other hold untouched, twice harmless, publish once |
| `services/booking-api/app/hold_timer.py` | `start()` (execution named by hold ID) and `release_now()` |
| `services/booking-api/app/routes/buyer.py` | Starts the timer after the hold; 503 and release if it can't |
| `services/booking-api/tests/test_hold_timer.py` | 3 tests: started, already exists = OK, failure releases the seats |
| `infra/modules/async/*` | State machine, release Lambda, IAM, security group |
| `infra/envs/dev/main.tf`, `booking_api.tf` | Wires the module; lets the Lambda into PostgreSQL; pod may start the timer |
| `deploy/helm/booking-api/*` | `HOLD_TIMER_ARN` env var |
| `.github/workflows/ci.yml` | New `workers` job |
| `.gitignore`, `ruff.toml`, `.pre-commit-config.yaml` | Track the CA bundle; skip lint on vendored code |

## 3. How it works

**The idea, simply.** Picture a cloakroom ticket with a 10-minute timer. When the timer rings,
the attendant looks at the hook. If **your** coat is still there unpaid, it goes back on the
rack. If you already paid, or somebody else's coat is on the hook now, the attendant does
nothing. That check-at-the-end is the key: the timer never trusts what it knew 10 minutes ago.

**In SurgeGate:**

```
buyer holds seats ─► booking API commits the hold
                     └─► StartExecution(name = hold_id, {hold_id, event_id, wait_seconds: 600})
Step Functions:  Wait 600 s ──► Release Lambda (in the VPC)
                                 UPDATE seats SET status='available', hold_id=NULL
                                  WHERE hold_id = :this_hold AND status = 'held'   ← only this hold's unpaid seats
                                 UPDATE holds SET status='released' WHERE id = :this_hold AND status='active'
                                 └─► Kinesis "hold_released" ─► EventBridge bus (organiser live view)
```

- **Why Step Functions?** A Standard workflow can wait for up to a year, and you pay per state
  change, not per second of waiting. 10,000 holds cost about 40,000 transitions, about $1. A
  cron job that scans for expired holds would also work, but the plan wants exact per-hold
  timing and a visible history for each hold.
- **Why name the execution by the hold ID?** Step Functions refuses a second execution with the
  same name, so a retried request can't start two timers. The API treats
  `ExecutionAlreadyExists` as success.
- **Why is the release safe to run twice?** Both UPDATEs have conditions (`status='held'`,
  `status='active'`), so the second run changes nothing and publishes nothing. That makes the
  6 automatic retries safe.
- **What if the timer can't start?** Then the API gives the seats back at once and returns 503
  "please try again". A hold without a timer would block the seats forever.

## 4. Errors I hit and how I fixed them

| # | Error (exact message) | Cause | Fix |
| --- | --- | --- | --- |
| 1 | ruff `E501 Line too long` in `tests/test_release_hold.py` | One assert line was over 100 characters | Split the line |
| 2 | CI plan on PR #42: `Plan: 0 to add, 2 to change` with `source_code_hash = "2oYP…" -> "GKRH…"` | `git check-ignore` showed `.gitignore:28:*.pem`. The RDS CA bundle (a public certificate file) was ignored, so CI's zip lacked it. If CI had applied, the Lambda would have lost TLS to RDS. | Added `!services/workers/src/sg_workers/rds-global-bundle.pem` to `.gitignore` (checked: 114 certificates, 0 private keys) and committed it |
| 3 | CI plan still `2 to change` (`"2oYP…" -> "UMRH…"`) | pip on Windows wrote 5 `dist-info/RECORD` files with CRLF. Git stores them as LF, so my local zip and CI's zip differed. | Deleted them and ran `git checkout --` to get LF. The local plan then had the same hash as CI (`UMRH…`). Applied that 1-change plan after approval. |
| 4 | `Post "https://api.github.com/graphql": ... wsarecv: An established connection was aborted by the software in your host machine.` | Home network dropped during `gh pr checks --watch` | Re-ran the check |
| 5 | `Blocked: sleep 30 followed by: gh run list ...` | The tool blocks chained sleeps | Used `gh run watch` instead |
| 6 | `ImportError: cannot import name 'SessionLocal' from 'app.db'` | My live-check script guessed a name; the app's factory is `_session_factory()` | Used `_session_factory()` |

## 5. How I verified it works

- **Tests:** workers 5 passed, booking API 101 passed; all 10 CI checks green on #42.
- **Smoke test:** invoking the Lambda directly for an unknown hold returned
  `{"released_seats": [], "hold_was_active": false}`. This proves the path: Lambda in the
  VPC → RDS describe → managed secret → TLS → PostgreSQL.
- **Live run:**
  1. Hold `cf0ba751-007d-446a-a091-1c13b5c73f51` on seat **A-1-3** of the event "seat_held
     check".
  2. Execution `surgegate-dev-hold-timer:cf0ba751-…`: `WaitStateEntered 19:31:21` →
     `WaitStateExited 19:32:21` (exactly 60 s) → `TaskSucceeded 19:32:23` → **SUCCEEDED**.
     Output: `{"released_seats": ["A-1-3"], "hold_was_active": true}`.
  3. Database afterwards: hold `released`; seat A-1-3 `available`, `hold_id` NULL.
  4. EventBridge log group: `detail-type: sale-event`, `type: hold_released`, with its
     `kinesis_sequence`.
- **Never a sold seat:** covered by `test_sold_seat_is_never_released` and
  `test_seat_held_by_another_hold_is_untouched`, on the real schema in CI.
- **Final local `terraform plan`:** no changes.

**Known leftover (dev test data only):** 9 seats are still `held` by test holds made **before**
the timer existed (2 in "seat_held check", 2 in "SurgeGate Fest", 5 in "M2 Demo Night"). They
have no timer, so they stay held. A one-off run of the release worker over those expired holds
would free them. I have not done it without your OK.

## 6. Cost impact

- **New billable resources:** yes, but nothing hourly.
  - Step Functions Standard costs $0.025 per 1,000 state transitions (about 4 per hold).
  - The Lambda is pay per use (256 MB, about 2.5 s per run).
  - The log group keeps logs 7 days.
  - Today's testing cost well under $0.01.
- **Not part of make up/down:** with dev down, it sits idle at $0. (With the database off, a
  release would fail and retry 6 times, then stop. Holds don't exist then anyway.)
- **Teardown:** remove `module "async"` from `infra/envs/dev/main.tf`, then plan and apply.

## 7. Interview notes

- **Q:** Why not just put an `expires_at` on the hold and check it when someone else tries to
  book the seat?
  **A:** That "lazy expiry" works for booking, but the seat map and the organiser's live view
  would show the seat as taken until someone tries it. The timer frees the seat and announces
  `hold_released`. The conditional UPDATE still protects correctness: the timer can't release a
  paid seat.
- **Q:** What stops a race where the buyer pays at 9:59 and the timer fires at 10:00?
  **A:** Both sides use conditional updates in one database. Payment flips the seats to `sold`
  and the hold to `converted`. The release only touches `status='held'` seats of an `active`
  hold, so whichever commits second sees the changed status and does nothing. (Late payments
  after a release get the Day 7 Task 4 rule: re-hold if free, otherwise refund.)
- **Q:** Why name the execution after the hold ID?
  **A:** Idempotency for free. Step Functions rejects a duplicate name, so retries can't create
  two timers, and you can find the timer for any hold by its ID.

## 8. Next task

Day 7 Task 2 in the plan: **orders with idempotency keys; Razorpay test-mode checkout in the
buyer app.** This needs the Razorpay test keys in Secrets Manager; the secret container exists,
and you set the value by hand.
