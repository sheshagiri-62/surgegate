# Week 1 · Day 3 · Task 01 — `data` module: RDS PostgreSQL, ElastiCache Redis, S3, KMS, Secrets Manager

- **Date:** 2026-11-21
- **Phase / milestone:** Phase 2 (Booking core) → M2
- **Status:** Done. Snapshot/restore check **pending**: the marker row is written; tonight's
  `make down` takes the final snapshot and the next `make up` restores it, then the row is checked.
- **Commit / PR:** [#14](https://github.com/sheshagiri-62/surgegate/pull/14)

## 1. What the task was

Plan text: *"`data` module: RDS PostgreSQL (single-AZ in dev), ElastiCache Redis, S3 buckets, KMS
key, Secrets Manager entries."* PostgreSQL is the single source of truth for seats and orders;
Redis caches the seat map and holds rate limits; S3 stores tickets and seat-map files. Everything
hourly must follow `make up` / `make down`, and the database must survive between sessions.

## 2. What I did, step by step

1. **New module `infra/modules/data`**, split into two parts:
   - **Persistent (cents/month):** KMS key with rotation, two S3 buckets (`tickets`, `seatmaps`),
     the Redis AUTH secret, an empty Razorpay secret container, subnet groups, security groups,
     and parameter groups.
   - **Hourly (`compute_enabled`):** the RDS instance and the Redis replication group.
2. **RDS PostgreSQL 18:**
   - `db.t4g.micro`, single-AZ, 20 GiB gp3, KMS-encrypted, not public.
   - The **master password is generated and rotated by RDS** in Secrets Manager
     (`manage_master_user_password`), so no password exists in Git or Terraform state.
   - Parameter group: `rds.force_ssl=1` (TLS required) and `log_min_duration_statement=500`
     (logs queries slower than the booking SLO).
3. **Between sessions:**
   - `make down` destroys the instance after a uniquely named **final snapshot**
     (`surgegate-dev-pg-final-<random>`).
   - `make up` finds the newest snapshot and restores from it.
   - `make prune-snapshots` keeps only the newest 2.
4. **Redis 7.1:** `cache.t4g.micro`, 1 node, at-rest encryption (KMS), in-transit TLS, AUTH token,
   and our own parameter group with `maxmemory-policy=allkeys-lru`, because it is a cache.
5. **S3:** bucket-owner-enforced, all public access blocked, versioning, SSE-KMS with bucket keys,
   a lifecycle rule (old versions expire after 30 days, incomplete uploads after 7), and a TLS-only
   bucket policy.
6. **Security groups:** Postgres port 5432 and Redis port 6379 are open **only to the EKS node
   security group**, and the rules exist only while EKS is up.
7. **Bootstrap:** the CI plan role may also read `…/data/redis-auth-*`, because Terraform refreshes
   the secret version during plan. The value is already in state anyway. The RDS master secret and
   the Razorpay secret are *not* readable by CI.
8. **Makefile:**
   - `up` restores `LATEST_SNAPSHOT`.
   - `down` switches `enable_data=false`, then runs `prune-snapshots`.
   - `billing-check` now also lists RDS instances and ElastiCache groups.
9. **Applied:** first the bootstrap plan, then `make up APPROVE=yes`. After that I verified
   everything from a temporary pod inside the cluster.

### Commands I ran

```bash
terraform fmt -recursive infra && terraform -chdir=infra/envs/dev validate && tflint --chdir=infra/modules/data
make -n up                      # "Restoring the database from snapshot: <none - new empty database>"
make prune-snapshots            # "DB snapshots kept: "
# bootstrap (1 change: plan role may read the redis-auth secret)
cd infra/bootstrap && terraform plan -lock-timeout=5m -out=data-secrets.tfplan && terraform apply data-secrets.tfplan
# dev
make up APPROVE=yes             # failed at helm_release.lbc (error 1 below)
make up APPROVE=yes             # failed again the same way
terraform -chdir=infra/envs/dev plan -var=enable_nat_gateway=true -var=enable_eks=true \
  -var=enable_data=true -var=restore_snapshot_id= -out=up.tfplan
TF_LOG_PROVIDER=DEBUG terraform -chdir=infra/envs/dev apply up.tfplan   # Apply complete! 3 added, 1 changed
aws eks update-kubeconfig --name surgegate-dev --alias surgegate-dev
kubectl get applications -n argocd   # booking-api, root: Synced / Healthy
# fix the perpetual diff (error 2), re-plan → "No changes."
# verification (temporary namespace "verify"; credentials piped from Secrets Manager into a
# temporary Kubernetes Secret, never printed)
kubectl create namespace verify
kubectl -n verify create configmap rds-ca --from-file=rds-global-bundle.pem
kubectl apply -f verify-data.yaml    # postgres:18 and redis:7.4 pods
kubectl -n verify exec verify-pg -- psql "sslmode=verify-full sslrootcert=/ca/rds-global-bundle.pem" -c "select ssl, version, cipher from pg_stat_ssl where pid = pg_backend_pid()"
kubectl -n verify exec verify-pg -- psql "sslmode=disable" -c "select 1"
kubectl -n verify exec verify-pg -- psql ... -c "create table ops_restore_check ...; insert ... 'day3-before-make-down'"
kubectl -n verify exec verify-redis -- redis-cli --tls --cacert /tmp/amazon-root-ca1.pem -h $REDIS_HOST PING
aws rds describe-db-instances ... ; aws ec2 describe-route-tables ... ; aws s3api get-bucket-encryption ...
aws s3api get-object ... --endpoint-url http://s3.ap-south-1.amazonaws.com    # must be denied
kubectl delete namespace verify
```

### Files created or changed

| File | What it does |
| --- | --- |
| `infra/modules/data/main.tf` | KMS, S3 (x2), secrets, subnet/parameter/security groups; RDS and Redis behind `compute_enabled` |
| `infra/modules/data/variables.tf`, `outputs.tf`, `versions.tf` | Inputs (instance sizes, restore snapshot), outputs (endpoints, secret ARNs, buckets) |
| `infra/envs/dev/main.tf`, `variables.tf`, `outputs.tf` | `module "data"`, `enable_data`, `restore_snapshot_id`, new outputs |
| `infra/bootstrap/iam.tf` | Plan role may read the Terraform-generated Redis AUTH secret |
| `Makefile` | `up` restores the newest snapshot; `down` → `enable_data=false` → `prune-snapshots`; `billing-check` lists RDS and Redis |

## 3. How it works

**A managed database that can be "switched off" without losing data.** RDS bills for every hour
the instance exists. A snapshot is a stored copy of the disk and costs only storage. So at the end
of the day, `make down` tells Terraform to remove the instance. Because `skip_final_snapshot = false`,
RDS first writes a final snapshot. The next morning, `make up` asks AWS for the newest snapshot and
passes its name to Terraform as `restore_snapshot_id`, and RDS builds a new instance from it. Each
instance gets a random suffix for its final-snapshot name, so two sessions never collide.

**Secrets without secrets in code.**
- RDS creates the master password itself and keeps it in Secrets Manager, encrypted with our KMS
  key and rotated automatically. Terraform never sees it.
- The Redis AUTH token is generated by Terraform (`random_password`), so it *is* in the
  (encrypted, private) state file. Only the CI plan role may also read it.
- Razorpay keys will be put into their secret by hand; Terraform only creates the empty container.

**Defence in depth on the network.** The data subnets have no route to the internet: only `local`
plus the S3/DynamoDB gateway endpoints. RDS is `publicly_accessible = false`, and the security
groups accept connections only from the EKS nodes. On top of that, both databases require TLS:
Postgres refuses plain connections (`rds.force_ssl`), and Redis only speaks TLS and needs the AUTH
token.

**How it fits SurgeGate.** The hold logic (Day 4) is one conditional `UPDATE` in this PostgreSQL. The
seat map is read through this Redis. Ticket PDFs (Day 8) go into the `tickets` bucket. Dev is
single-AZ with one Redis node to save money; `demo` (Day 9) uses Multi-AZ and a replica via the
same module variables.

## 4. Errors I hit and how I fixed them

| # | Error (exact message) | Cause | Fix |
| --- | --- | --- | --- |
| 1 | `Error: installation failed … helm_release.lbc … Kubernetes cluster unreachable: Get "https://E475…eks.amazonaws.com/version": getting credentials: exec: executable aws failed with exit code 1` (twice) | The Helm provider runs `aws eks get-token`, and that call failed. The same command worked from my shell straight afterwards. The `aws login` credentials last **15 minutes** and `make up` runs about 20, so the most likely cause is the Terraform AWS provider and the AWS CLI both refreshing the same login session mid-apply. Not proven: the debug run succeeded. | Re-ran the same plan and apply (only the 3 missing Helm releases were left), and it succeeded. **Known issue:** if `make up` fails at a `helm_release` with this message, run `make up` again; it only adds what's missing. I'll look deeper if it repeats. |
| 2 | Every plan showed `~ aws_db_parameter_group.postgres` … `- apply_method = "pending-reboot"` / `+ apply_method = "immediate"` for `rds.force_ssl` | `rds.force_ssl` is a *static* parameter, so AWS stores it as `pending-reboot`, but the provider defaults to `immediate`. A perpetual diff. | Set `apply_method = "pending-reboot"` explicitly. The plan is now `No changes.` It was applied when the instance was created, so it's already in force (test 2 below). |
| 3 | `tflint`: `"default.redis7" is default parameter group. You cannot edit it.` (notice) | I used the AWS default Redis parameter group. | Created our own `surgegate-dev-redis7` group (also sets `allkeys-lru`). |
| 4 | `redis-cli`: `SSL_connect failed: certificate verify failed` | The `redis:7.4` image has no CA certificate store (`/etc/ssl/certs` doesn't exist). | Passed Amazon Root CA 1 with `--cacert`, keeping certificate verification on (not `--insecure`). |
| 5 | `psql`: `ERROR: unrecognized configuration parameter "rds.force_ssl"` | `SHOW` can't read RDS-specific settings. | Proved it instead with a plain-text connection, which is refused (test 2). |
| 6 | Support API: `Premium Support Subscription is required` | `aws support describe-cases` needs a paid support plan, so the CloudFront case can't be read from the CLI. | Asked you instead (you're escalating by chat). |

## 5. How I verified it works

| Check | Result |
| --- | --- |
| `make up` (after the retry) | Apply complete; nodes Ready; Argo CD `booking-api` and `root` **Synced/Healthy**; re-plan shows `No changes.` |
| Postgres TLS with full certificate check (`sslmode=verify-full` + RDS CA) | `PostgreSQL 18.3 …` · `t\|TLSv1.3\|TLS_AES_256_GCM_SHA384` |
| Postgres without TLS (`sslmode=disable`) | `FATAL: no pg_hba.conf entry for host "10.20.27.97", user "surgegate_admin", database "surgegate", no encryption` (refused) |
| Credentials | Came from the **RDS-managed secret** (`rds!db-…`, KMS key `038a0e32…`, rotation on) |
| Marker row for snapshot test | `1\|day3-before-make-down\|2026-11-21 13:58:04+00` in `ops_restore_check`. **Pending:** check it after the next `make up` restores the final snapshot. |
| RDS not public | `PubliclyAccessible: false`; endpoint resolves to private `10.20.8.79`; data-subnet route tables have only `local` + S3/DynamoDB endpoints (no `0.0.0.0/0`); SG 5432 ingress only from `sg-0008a1fbba5697abf` (EKS nodes) |
| Redis TLS + AUTH | `PONG`, `redis_version:7.1.0`, SET/GET OK. Without a token or with a wrong one: `NOAUTH Authentication required.` Without TLS: timed out. API shows `TransitEncryption/AtRest/AuthToken: true`, `maxmemory-policy = allkeys-lru` |
| S3 (both buckets) | `aws:kms` with our key, bucket key on; all 4 public-access blocks true; versioning `Enabled`; policy `DenyInsecureTransport`. Upload over HTTPS → `SSE: aws:kms`. **Plain HTTP GET → `AccessDenied … with an explicit deny in a resource-based policy`** |
| Tags | Every data resource has `Project=surgegate, Env=dev, Component=data` (Resource Groups Tagging API) |

## 6. Cost impact

Yes, new billable resources (ap-south-1, AWS Pricing API):

| Item | While up | While down |
| --- | --- | --- |
| RDS `db.t4g.micro` + 20 GiB gp3 | $0.021 + $0.004 /hour | none (instance destroyed) |
| Redis `cache.t4g.micro` | $0.020 /hour | none |
| Final snapshots (2 kept) | none | $0.095 /GB-month of used data (a few cents) |
| KMS key; 2 data secrets; S3 | $1/month; $0.80/month; cents | same |

The data layer adds **≈ $0.045/hour**. The whole dev environment while up is **≈ $0.33/hour**.
**Teardown:** `make down` (snapshot → destroy RDS, destroy Redis, prune old snapshots, then
`billing-check`).

## 7. Interview notes

- **Q:** How do you avoid paying for a database 24/7 in a dev environment and still keep its data?
  **A:** The instance is created per work session. On teardown RDS writes a final snapshot, which
  costs only storage. On the next start, Terraform restores the newest snapshot, found by the
  Makefile. Unique snapshot names and a "keep 2" prune avoid collisions and storage creep.
- **Q:** Where is the database password?
  **A:** Nowhere in our code or state. RDS generates it and stores it in Secrets Manager, encrypted
  with our KMS key, and rotates it automatically. The app reads it at runtime through its IAM role
  (Task 2), scoped to that one secret.
- **Q:** How is the database protected if someone gets into the VPC?
  **A:** Layers: data subnets have no internet route, RDS is not public, and the security group only
  admits the EKS nodes. Connections must use TLS (`rds.force_ssl`; plain connections are refused)
  and need credentials from Secrets Manager. Storage, snapshots, Redis and S3 are KMS-encrypted.

## 8. Next task

Day 3 Task 2 — Booking API: SQLAlchemy models and Alembic migrations for tenants, events, seats,
holds, orders, order_items; run the migrations against RDS through the cluster.
