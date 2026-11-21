# Week 1 · Day 3 · Task 02 — Booking API: SQLAlchemy models and Alembic migrations

- **Date:** 2026-11-21
- **Phase / milestone:** Phase 2 (Booking core) → M2
- **Status:** Done. Migrations ran against dev RDS through the cluster (Argo CD Job).
- **Commit / PR:** [#15](https://github.com/sheshagiri-62/surgegate/pull/15) (models, migrations,
  CI, IAM) · [#16](https://github.com/sheshagiri-62/surgegate/pull/16) (migration Job) ·
  [#17](https://github.com/sheshagiri-62/surgegate/pull/17) (fix: CA bundle permissions + image smoke test)

## 1. What the task was

Plan text: *"Booking API: SQLAlchemy models and Alembic migrations for tenants, events, seats, holds,
orders, order_items."* You also asked for the migrations to run against RDS **through the cluster**.
This is the schema that makes "never sell a seat twice" a database rule rather than a hope.

## 2. What I did, step by step

1. **Models** (`app/models.py`, SQLAlchemy 2.1):
   - Six tables, with UUID keys and money as integer paise.
   - Postgres enums for the statuses.
   - A naming convention, so every constraint has a stable name.
   - Safety rules in the database itself:
     - `order_items.seat_id` **UNIQUE** (the blueprint's second safety net);
     - `ck_seats_held_has_hold` (a held seat must point to a hold and have an expiry);
     - `per_buyer_limit BETWEEN 1 AND 10`;
     - `sale_starts_at < starts_at`;
     - unique `idempotency_key` on orders.
   - Indexes for the hold `UPDATE` (`event_id, status`) and the per-buyer limit check
     (`event_id, buyer_id, status`).
2. **Migration `0001`**, written by hand. Autogenerate needs a live DB, and a hand-written
   migration is easier to review. A test proves it matches the models exactly.
3. **Connection** (`app/db.py`):
   - With `DATABASE_URL` set (tests, CI), it is used directly.
   - In the cluster, it reads `DB_INSTANCE_ID`, calls `rds:DescribeDBInstances` for the endpoint
     and the **RDS-managed secret ARN**, then reads that secret.
   - The password is re-read every 5 minutes through a `do_connect` hook, so rotation never breaks
     new connections.
   - TLS uses `sslmode=verify-full` with the RDS CA bundle baked into the image.
4. **IAM without keys** (`infra/envs/dev/booking_api.tf`):
   - A Pod Identity role for the `booking/booking-api` service account.
   - It can describe only `surgegate-dev-pg`.
   - It can read only a secret tagged `aws:rds:primaryDBInstanceArn` = that DB.
   - It can call `kms:Decrypt` only via Secrets Manager.
   - Applied with a saved plan (3 to add, IAM only, free).
5. **Chart** (`deploy/helm/booking-api`):
   - A ServiceAccount in wave −10.
   - `DB_INSTANCE_ID` and `AWS_REGION` env vars.
   - A **migration Job as an Argo CD Sync hook in wave −5**, which must succeed before the
     Deployment (wave 0).
   - Argo CD retry with backoff.
6. **CI** (`ci.yml`, new): ruff and pytest with a `postgres:18` service container on every
   booking-api PR. `build-deploy` got the same service and, after #17, an image smoke test.
7. **Split into two PRs (#15 code, #16 chart),** so the migration Job never runs on an old image
   without Alembic. The pipeline bumps the image tag about 5 minutes after a merge.

### Commands I ran

```bash
git worktree add ../surgegate-wt -b feat/booking-models infra/data   # don't switch branches during make up
py -3.12 -m venv .venv && .venv/Scripts/python -m pip install -r requirements-dev.txt
ruff format . && ruff check --fix .
python -m pytest -q -ra                                   # 4 passed, 4 skipped (no DB)
docker run -d --name sg-pg -e POSTGRES_USER=surgegate -e POSTGRES_PASSWORD=local-only \
  -e POSTGRES_DB=surgegate_test -p 127.0.0.1:15432:5432 postgres:18
DATABASE_URL=postgresql+psycopg://surgegate:local-only@127.0.0.1:15432/surgegate_test python -m pytest -q -ra   # 8 passed
docker build -t sg-booking:local . && docker run --rm --read-only --user 10001 -e DATABASE_URL=… sg-booking:local alembic upgrade head
terraform -chdir=infra/envs/dev plan … -out=pod-identity.tfplan && terraform apply pod-identity.tfplan   # 3 added
kubectl -n booking create serviceaccount booking-api
kubectl apply -f verify-iam.yaml && kubectl -n booking exec verify-iam -- aws …   # allowed / denied checks
helm lint deploy/helm/booking-api
gh pr create …  # #15, #16;  gh pr merge 14/15/16 --squash (approved)
gh run watch <build-deploy run>
kubectl -n booking logs job/booking-api-migrate      # error 7 below → fix PR #17 → merged (approved)
kubectl -n argocd patch application booking-api --type merge -p '{"status":{"operationState":{"phase":"Terminating"}}}'
kubectl -n booking exec <pod> -- python -c "… from app.db import get_engine …"
```

### Files created or changed

| File | What it does |
| --- | --- |
| `services/booking-api/app/models.py` | The six tables, enums, constraints and indexes |
| `services/booking-api/app/db.py` | Engine/session; RDS discovery + RDS-managed secret + TLS verify-full in the cluster |
| `services/booking-api/alembic.ini`, `alembic/env.py`, `alembic/script.py.mako` | Alembic setup (URL comes from `app.db`; `lock_timeout=10s`) |
| `services/booking-api/alembic/versions/0001_booking_core.py` | The initial schema migration (upgrade and downgrade) |
| `services/booking-api/tests/conftest.py`, `tests/test_migrations.py` | Unit tests + integration tests (run when `DATABASE_URL` is set) |
| `services/booking-api/Dockerfile` | Adds the RDS CA bundle (dir mode 755) and the Alembic files |
| `services/booking-api/requirements.txt`, `pytest.ini` | SQLAlchemy 2.1.9, Alembic 1.20.1, psycopg 3.3.9, boto3; `integration` marker |
| `infra/envs/dev/booking_api.tf` | Pod Identity role, scoped policy, association |
| `deploy/helm/booking-api/templates/serviceaccount.yaml`, `migrate-job.yaml`, `_helpers.tpl`, `deployment.yaml`, `values.yaml` | SA, migration Job (Sync hook, wave −5), DB env |
| `deploy/argocd/booking-api.yaml` | Sync retry with backoff |
| `.github/workflows/ci.yml` (new), `build-deploy.yml` | PR tests with Postgres 18; Postgres service and image smoke test after merge |

## 3. How it works

**Models and migrations.** A *model* is a Python class that describes a table. A *migration* is a
numbered script that changes the real database from one version to the next: `upgrade` creates
things and `downgrade` removes them. Alembic records which version the DB is at in
`alembic_version`, so `alembic upgrade head` only runs what's missing. A test runs the migration on
a fresh Postgres and asks Alembic to compare the result with the models. The answer must be
"no differences", so the two can never drift apart silently.

**Why the database enforces the rules.** Application code has bugs, and a flash sale has thousands
of requests racing at once. A `UNIQUE` constraint on `order_items(seat_id)` means that even if two
requests both believed a seat was free, the database accepts only one of them. The check constraint
on seats makes a half-held seat (status `held` with no hold) impossible to store.

**Migrations in the cluster.** Argo CD applies resources in *sync waves* and waits for each wave to
be healthy before the next:
- wave −10: the ServiceAccount;
- wave −5: the migration Job, which must **complete successfully**;
- wave 0: the Deployment rolls out the new pods.

If the migration fails, the sync stops and the old pods keep serving. That really happened (error
7), and users weren't affected.

**Credentials.** The pod has no password in its config. EKS Pod Identity gives it short-lived AWS
credentials for its own role. With those, it asks RDS where the database is and which secret holds
the password, then reads only that secret. When `make up` restores from a snapshot, RDS creates a
new secret, and the app finds it automatically.

## 4. Errors I hit and how I fixed them

| # | Error (exact message) | Cause | Fix |
| --- | --- | --- | --- |
| 1 | `pip install` printed nothing for ~15 minutes, and nothing was installed (`-q` hid progress) | The pip self-upgrade/download step hung (network); cause not visible because of `-q` | Stopped it and re-ran without `-q`, with `--progress-bar off` and a timeout; it finished in under a minute from the cache |
| 2 | `TypeError: sqlalchemy.engine.create.create_engine() got multiple values for keyword argument 'pool_size'` | `make_engine()` passed its own `pool_size` default **and** the caller's `pool_size` (Alembic env) | Merge the defaults with the caller's arguments (`defaults \| kwargs`, explicit wins) |
| 3 | `docker: Error response from daemon: ports are not available: exposing port TCP 0.0.0.0:55432 … bind: An attempt was made to access a socket in a way forbidden by its access permissions.` | Windows reserves some port ranges (Hyper-V / WinNAT) and refuses to bind them | Used `127.0.0.1:15432` instead |
| 4 | `psycopg.errors.ConnectionTimeout … connection timeout expired` (4 tests, 266 s) | A consequence of #3: the Postgres container never started (I had hidden `docker run`'s output) | After #3, all 8 tests pass. Lesson: don't hide `docker run` errors |
| 5 | `psql: … FATAL: database "surgegate" does not exist` | My `docker exec psql` connected to the default DB (= user name), which doesn't exist in the test container | Added `-d surgegate_test` |
| 6 | `F401 [*] 'os' imported but unused` | Leftover import in the test file | `ruff check --fix` |
| 7 | Migration Job in dev: `connection to server at "10.20.8.79", port 5432 failed: root certificate file "/srv/certs/rds-global-bundle.pem" does not exist` | `ADD --chmod=644 <url> /srv/certs/…` also created the **directory** with mode 644 (`drw-r--r--`, no execute bit), so UID 10001 couldn't enter it. My local container test used `DATABASE_URL` (no CA file), so it missed this | PR #17: `RUN mkdir -m 755 /srv/certs` before the `ADD`, plus a **build-deploy smoke test** that runs the image as UID 10001 with a read-only filesystem and checks the CA bundle, imports and `alembic heads` before the push |
| 8 | Argo CD: `waiting for completion of hook batch/Job/booking-api-migrate`, still on revision `cbf94f4` (retry 1) after #17 was deployed | An auto-sync operation retries **the same revision**; a newer commit isn't picked up until the operation ends (up to ~30 min of backoff) | Terminated the stuck operation (`operationState.phase=Terminating`, same as `argocd app terminate-op`); auto-sync took the latest revision and succeeded |

Two design problems were caught *before* they broke anything:
- **PreSync hook:** that phase runs before the ServiceAccount exists on the first sync, so I
  switched to a Sync hook in wave −5.
- **Chart and code in one PR:** the Job would have run on the old image, so I split the work into
  #15 and #16.

## 5. How I verified it works

| Check | Result |
| --- | --- |
| Local tests (Postgres 18 container) | `8 passed`: models = migration (`compare_metadata == []`), downgrade → upgrade round trip, a seat can't be in two orders (`uq_order_items_seat_id`), a held seat needs a hold (`ck_seats_held_has_hold`) |
| CI (`ci.yml`, `postgres:18` service) | `8 passed`, none skipped |
| Image as in the cluster (UID 10001, read-only) | `Running upgrade -> 0001`, `0001 (head)`, 6 tables. After #17, the smoke test passes locally and in the pipeline |
| Pod Identity scope (pod as `booking-api`) | Assumed `surgegate-dev-booking-api`. Own DB describe OK; own secret keys `['password','username']`. **Denied:** Razorpay secret, edge secret, describe all DBs, S3 list |
| Migration Job in dev | `job/booking-api-migrate Complete 1/1 8s`; log `Running upgrade -> 0001, booking core…`; Argo CD `Succeeded`, `Synced/Healthy`; pods `1cdf00d7aca7` 2/2 |
| Query from an app pod via `app.db` | `sslmode=verify-full`, `(True, 'TLSv1.3')`, `alembic: 0001`, all six tables present, `uq_order_items_seat_id` present, marker row `(1, 'day3-before-make-down')` still there |

## 6. Cost impact

No new hourly resources. IAM role and Pod Identity association are free. CI minutes on a public
repo are free.

## 7. Interview notes

- **Q:** How do you stop the same seat being sold twice if the application has a bug?
  **A:** The database enforces it. Holds are one conditional `UPDATE … WHERE status='available'`
  (Day 4), and `order_items.seat_id` is UNIQUE, so the second insert for a seat fails whatever the
  code thought. A check constraint makes inconsistent seat states impossible.
- **Q:** How do migrations run in Kubernetes without breaking a running service?
  **A:** As an Argo CD hook Job in an earlier sync wave than the Deployment. Argo CD waits for the
  Job to succeed before rolling out new pods; if it fails, the sync stops and the old pods keep
  serving. That happened once here, with no user impact. Migrations must also be backward
  compatible, because old pods run against the new schema during a rollout.
- **Q:** How does the pod get the database password?
  **A:** It doesn't have one in its config. EKS Pod Identity gives it a short-lived IAM role. The
  role may describe only our DB and read only the secret RDS tags with that DB's ARN, so it can't
  read the payment keys. The app re-reads the secret every few minutes, so RDS can rotate it.

## 8. Next task

Day 3 Task 3 — Cognito user pool with buyer and organiser groups; JWT checks in FastAPI.
