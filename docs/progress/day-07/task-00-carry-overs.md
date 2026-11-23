# Week 2 · Day 7 · Task 00 — Carry-overs: make on Windows, snapshot test, CloudFront (M1 + M3), VPC origins, k6 re-run

- **Date:** 2026-11-23 (session start; ran into the night of 23–24 Nov)
- **Phase / milestone:** closes M1 and M3; prepares Phase 4 (payments need a non-public origin hop)
- **Status:** Done
- **Commit / PR:** [#36](https://github.com/sheshagiri-62/surgegate/pull/36) (make), [#37](https://github.com/sheshagiri-62/surgegate/pull/37) (no `/position` before the sale), [#38](https://github.com/sheshagiri-62/surgegate/pull/38) (CloudFront), [#39](https://github.com/sheshagiri-62/surgegate/pull/39) (debug access, M1 live 403, M3 met), [#40](https://github.com/sheshagiri-62/surgegate/pull/40) (VPC origin)

## 1. What the tasks were

Your list for this session:
1. Merge #35 and fix `make`'s AWS CLI failure ("verify the HOME fix").
2. Read-only re-checks.
3. `make up` only from the expected snapshot, then the marker-row test.
4. CloudFront: enable it, copy the pass key to the edge, run every pending check, update M1/M3.
5. Propose (then build) the fix for the plain-HTTP CloudFront → ALB hop.
6. Stop calling `/position` before the sale.

Plus: re-run k6 with 1,000 users.

## 2. What I did, step by step

1. **`make` on Windows (#36):**
   - **Root cause:** `make` is MSYS2's (`C:\msys64\usr\bin\make.exe`). Started from Git Bash, a
     different MSYS runtime, it received **7 of 97** environment variables: `USERPROFILE`,
     `TEMP`, `APPDATA` and others were lost, and `HOME` became `/home/shesh`. That broke the AWS
     CLI, and earlier Terraform's provider download.
   - From PowerShell or `cmd.exe` it works.
   - **The fix:**
     - a guard that stops with `make lost the Windows environment … run: cmd //c "make …"`;
     - **`make up` can't silently create an empty DB:** the snapshot lookup must succeed, the
       `\r` from aws.exe is stripped, and `EXPECT_SNAPSHOT=<id>` stops on any other snapshot;
     - `billing-check`, `prune-snapshots` and `up` abort if the AWS CLI fails.
2. **Re-checks:**
   - **Lambda concurrency limit now 1,000**, although the support case still shows open;
   - Kinesis `ListStreams` works; CloudFront reads work; EC2 vCPU quota 16.
3. **`make up EXPECT_SNAPSHOT=surgegate-dev-pg-final-873e7969`:** it printed exactly that
   snapshot; 66 added; Argo CD Synced/Healthy. **The marker row `(1, 'day3-before-make-down')`
   survived** the final snapshot and restore. That closes Day 3 Task 1's pending check.
4. **CloudFront (#38):**
   - `enable_cloudfront = true`, then plan and apply (4 added): distribution
     `https://d1t9vww2xtyvsz.cloudfront.net`, the 5 s cache policy, the booking-pass function and
     its KeyValueStore.
   - **The function crashed at the edge:**
     `SyntaxError: await in arguments not supported in 37` (`X-Cache: FunctionExecutionError`).
     Fixed (await into a variable first), and re-tested with `TestFunction`.
   - The **pass key was copied** from Secrets Manager into the KVS, never printed; verified equal.
5. **Live no-header 403 (#39):** an optional `debug_ingress_cidr` (default empty, /32 only).
   Applied with your IP → `curl` straight to the ALB without the header → **`HTTP/1.1 403
   Forbidden`** (wrong header also 403) → removed (1 destroyed).
6. **k6 re-run:** 1,000 real Cognito accounts (deleted afterwards), **through CloudFront**, with
   the #37 page change. **All thresholds passed** (below).
7. **VPC origins (#40), the option you chose:**
   - the ALB is internal, in the private subnets;
   - `aws_cloudfront_vpc_origin`;
   - the distribution's `api` origin uses `vpc_origin_config` while dev is up.
   - **A local network outage** (`lookup …s3.ap-south-1.amazonaws.com: no such host`) broke the
     apply after the ALB was replaced: the state wasn't saved and the lock was left behind.
     **Recovered with your approval:**
     1. `force-unlock` (my own dead lock);
     2. `state push errored.tfstate` (same lineage, serial 94 > 92, no `-force`);
     3. waited for the VPC origin to be **Deployed**, then `untaint` (avoiding a 30-minute
        rebuild);
     4. a final plan (0 add, 2 change), then apply.
   - ADR 003 updated: still HTTP on the private path; HTTPS once the domain is approved.

## 3. How it works

- **CloudFront VPC origins** let CloudFront talk to a load balancer that has **no public
  address**: AWS puts a CloudFront-managed network interface in our private subnets, and
  requests travel on AWS's own network. Nobody on the internet can reach the ALB any more, even
  if they knew its name.
- **A broken apply** leaves real resources that the remote state doesn't know about. Terraform
  writes what it knew to `errored.tfstate`. Pushing that file back (it's newer, from the same
  "family") restores the record, and untainting avoids pointlessly destroying a resource that
  turned out healthy.

## 4. Errors I hit and how I fixed them

| # | Error (exact message) | Cause | Fix |
| --- | --- | --- | --- |
| 1 | `RuntimeError: Could not determine home directory.` / `[PYI-…:ERROR] Failed to execute script 'aws'` (inside make) | MSYS2 make started from Git Bash loses 90 of 97 environment variables | Guard + fail-fast (#36); run as `cmd //c "make …"` or from PowerShell |
| 2 | Command blocked by the safety check (complex quoting) | Couldn't be parsed | Wrote the test Makefile with the editor |
| 3 | `X-Cache: FunctionExecutionError` → `SyntaxError: await in arguments not supported in 37` | cloudfront-js-2.0 doesn't allow `await` inside call arguments | Await into a variable |
| 4 | `Error acquiring the state lock … PreconditionFailed` (#39 CI) | My apply held the lock | Re-ran the CI job after the apply |
| 5 | `Error: failed to upload state … dial tcp: lookup surgegate-tfstate-968077439619.s3.ap-south-1.amazonaws.com: no such host`; `Error releasing the state lock`; `waiting for CloudFront VPC Origin (vo_AAyDlmmnJSoBBFVbvDCjUO) create` | Local network/DNS outage during the apply | Force-unlock, state push, untaint, final apply (all approved) |
| 6 | `Post "https://api.github.com/graphql": net/http: TLS handshake timeout` / `connectex: A connection attempt failed` | Same flaky network | Retried |
| 7 | ADR edit not applied: `File has not been read yet. Read it first` | Editor needs the file read first | Read, then edit |

## 5. How I verified it works

| Check | Result |
| --- | --- |
| make guard / fail-fast | from Git Bash → guard message; via `cmd //c` → real billing-check; broken profile → `ERROR: the AWS CLI does not work here`; wrong `EXPECT_SNAPSHOT` → `STOP … Nothing created.` |
| Snapshot test | `make up` printed `surgegate-dev-pg-final-873e7969`; marker row present (written 2026-11-21 13:58:04 UTC); 7 events, 384 seats, 4 holds intact |
| **M1** | `https://…cloudfront.net/healthz` → **200** via CloudFront; HTTP → 301; direct ALB → no connection; **live no header → 403** |
| **M3 edge** | no/garbage/forged/expired pass → **403 `FunctionGeneratedResponse`**; valid pass but wrong user → refused by the API; valid → 200 (96 seats) |
| Serving cache | Miss → Hit (Age 1) → Hit (Age 3) → Miss … (5 s) |
| **k6, 1,000 users** | **1,000/1,000 joined and admitted, 0 failed of 25,690 requests, 0 throttles**; 250/min exactly; shuffle (earliest arrivals → 556, 9, 687, …); serving Lambda only **70** invocations (CloudFront cache); peak concurrency 168 |
| VPC origin | `/healthz` 200 through the VPC origin; ALB `internal`, resolves to 10.20.30.206 / 10.20.32.199, no public IP; organiser API 200; edge `/book` 403s; serving OK |

## 6. Cost impact

- CloudFront and VPC origins: $0 extra (free tier and free feature). The internal ALB saves the
  public IPv4 charge.
- k6: about $0.01, plus Cognito about 2,010 MAU this month (free tier: 10,000).
- **`make up` / `make down` each take about 15 minutes longer** (the VPC origin follows the ALB).

## 7. Interview notes

- **Q:** How is the origin protected now?
  **A:** The ALB has no public address at all. CloudFront reaches it through a VPC origin (a
  managed ENI in our private subnets), the security group admits only CloudFront, and a secret
  header is checked as well. A direct request can't even connect. Requests without the header
  get a fixed 403 from the ALB (shown live).
- **Q:** An apply failed half-way because the network dropped. What did you do?
  **A:** Stopped and looked before touching anything. AWS had the new ALB and a VPC origin still
  deploying; the remote state had the ALB but not the origin; the lock was stuck. With approval:
  force-unlocked my own dead lock, pushed Terraform's `errored.tfstate` (same lineage, newer
  serial), waited for the origin to finish and untainted it, then applied the remaining change.
- **Q:** What changed between the 977/1,000 and the 1,000/1,000 runs?
  **A:** The Lambda limit went from 10 to 1,000, CloudFront caches the shared counter (70 Lambda
  calls instead of 11,430), and the page no longer polls `/position` before the sale. Zero
  throttles.

## 8. Next task

Day 7 Task 1 — sale events on EventBridge + Kinesis (ADR 002).
