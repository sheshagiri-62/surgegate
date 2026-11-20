# Week 1 · Day 2 · Task 03 — ECR repository; `build-deploy.yml` builds, scans, pushes and bumps the Helm tag

- **Date:** 2026-11-20
- **Phase / milestone:** Phase 1 (Foundations) → M1
- **Status:** Done (full loop proven once, end to end)
- **Commit / PR:** [PR #9](https://github.com/sheshagiri-62/surgegate/pull/9) (feature), [PR #10](https://github.com/sheshagiri-62/surgegate/pull/10) (scan-wait fix) · successful run [44761340742](https://github.com/sheshagiri-62/surgegate/actions/runs/44761340742) · tag bump `ca93405`

## 1. What the task was

Plan text: *"ECR repository; `build-deploy.yml` builds a hello-world FastAPI image, scans it, pushes it,
bumps the Helm tag."*

This is the delivery half of M1: a merge to `main` must turn into a running container on EKS
without anyone touching the cluster. CI builds and pushes the image, writes the new tag into Git,
and Argo CD (Task 2) deploys it.

The same session also: merged PRs #7 and #8, deleted the two old budgets, generated the deploy key,
and checked your `main-protection` ruleset (deploy-key bypass) and the `DEPLOY_KEY` secret.

## 2. What I did, step by step

1. **Budgets:** showed the commands, deleted "My Zero-Spend Budget" and "My Monthly Cost Budget";
   only `surgegate-monthly` remains.
2. **Deploy key:** generated `~/.ssh/surgegate_deploy_key` (ed25519, outside the repo) and gave you
   the public key and the `gh` commands. You added it (read-write), set `DEPLOY_KEY`, created the
   `main-protection` ruleset and deleted the classic rule. I verified all of it through the API.
3. **ECR (approved):** new Terraform root `infra/envs/shared` (state `envs/shared/…`, `Env=shared`)
   with `surgegate/booking-api`: immutable tags, scan on push, keep last 10. Planned and applied.
4. **ECR push role:** `surgegate-gha-ecr-push` in `infra/bootstrap`. I showed you the plan (2 add, 1
   change), applied it after your "yes", then verified the trust policy and permissions with the IAM
   policy simulator.
5. **App:** `services/booking-api` FastAPI hello world (`/healthz`, `/`), 2 pytest tests, ruff, and a
   non-root multi-stage Dockerfile.
6. **Chart + Argo CD app:** `deploy/helm/booking-api` (Deployment + Service; non-root, read-only
   root filesystem, probes, zone spread) and `deploy/argocd/booking-api.yaml`. Linted, rendered and
   server-side dry-run.
7. **Pipeline:** `.github/workflows/build-deploy.yml` (test → build → Trivy → push → ECR scan →
   tag bump with the deploy key).
8. **Merges:** #7 squash-merged; #8 retargeted to `main`, `main` merged into it (no force push),
   green, squash-merged; `feat/build-deploy` rebased, PR #9 green (3 roots, no changes), merged.
9. **First run failed** after a successful push (ECR scan waiter race), so I fixed it in PR #10.
   Merging #10 ran the full loop successfully, and I verified every link.

### Commands I ran

```bash
# Budgets
aws budgets delete-budget --account-id 968077439619 --budget-name "My Zero-Spend Budget"
aws budgets delete-budget --account-id 968077439619 --budget-name "My Monthly Cost Budget"
aws budgets describe-budgets --account-id 968077439619

# Deploy key (you then ran: gh repo deploy-key add … --allow-write; gh secret set DEPLOY_KEY)
ssh-keygen -t ed25519 -N "" -C "surgegate-build-deploy" -f ~/.ssh/surgegate_deploy_key
ssh-keygen -lf ~/.ssh/surgegate_deploy_key.pub
gh api repos/sheshagiri-62/surgegate/keys
gh api repos/sheshagiri-62/surgegate/rulesets/27730459
gh api repos/sheshagiri-62/surgegate/branches/main/protection      # 404 = classic rule deleted
gh secret list

# Versions / action SHAs
git switch -c feat/build-deploy
gh api repos/<action>/releases/latest --jq .tag_name ; gh api repos/<action>/commits/<tag> --jq .sha
py -3.12 -m pip index versions fastapi    # + uvicorn, pytest, httpx, ruff

# Terraform (PowerShell, AWS_PROFILE=surgegate)
cd infra/envs/shared
terraform init; terraform providers lock -platform=windows_amd64 -platform=linux_amd64   # failed once (DNS)
terraform validate; tflint --config=../../../.tflint.hcl
terraform plan -lock-timeout=3m '-out=shared.tfplan'                                     # failed once (DNS)
terraform apply -lock-timeout=3m shared.tfplan
aws ecr describe-repositories --repository-names surgegate/booking-api
aws ecr get-lifecycle-policy --repository-name surgegate/booking-api
cd ../../bootstrap
terraform validate; tflint --config=../../.tflint.hcl
terraform plan -lock-timeout=3m '-out=ecr-push.tfplan'    # shown to you: 2 add, 1 change
terraform apply -lock-timeout=3m ecr-push.tfplan
aws iam get-role --role-name surgegate-gha-ecr-push
aws iam simulate-principal-policy --policy-source-arn arn:aws:iam::968077439619:role/surgegate-gha-ecr-push \
  --action-names ecr:PutImage --resource-arns arn:aws:ecr:ap-south-1:968077439619:repository/surgegate/booking-api   # + 9 more

# App, chart
py -3.12 -m venv <scratchpad>/venv-booking && pip install -r requirements-dev.txt
pytest -q && ruff check . && ruff format --check .
helm lint deploy/helm/booking-api
helm template booking-api deploy/helm/booking-api | kubectl apply --dry-run=server -n default -f -
kubectl apply --dry-run=server -f deploy/argocd/booking-api.yaml
gh variable set AWS_ECR_PUSH_ROLE_ARN --body arn:aws:iam::968077439619:role/surgegate-gha-ecr-push
git rm -r --cached infra/envs/dev/.helm && git commit --amend --no-edit    # cache wrongly staged, never pushed

# Merges and PRs
gh pr merge 7 --squash ; gh pr edit 8 --base main
git switch infra/argocd && git merge -X ours origin/main && git push ; gh pr checks 8 --watch ; gh pr merge 8 --squash
git switch feat/build-deploy && git rebase origin/main && git push -u origin feat/build-deploy
gh pr create … ; gh pr checks 9 --watch ; gh pr merge 9 --squash
gh run watch 44760723158                                   # failed at the ECR scan waiter
gh run view 44760723158 --log-failed
aws ecr describe-image-scan-findings --repository-name surgegate/booking-api --image-id imageTag=7620d5b71b1e
aws ecr get-registry-scanning-configuration
git switch -c fix/build-deploy-scan-wait origin/main ; git commit ; git push ; gh pr create …
gh pr merge 10 --squash ; gh run watch 44761340742         # success

# Verify the loop
gh run view 44761340742 --log
aws ecr describe-images --repository-name surgegate/booking-api
git log --oneline -3 origin/main
gh api repos/sheshagiri-62/surgegate/commits/ca93405…
kubectl get application booking-api -n argocd
kubectl get pods -n booking -o custom-columns=…IMAGE…IMAGEID…
kubectl -n booking run curl-check --rm -i --restart=Never --image=curlimages/curl:8.11.1 -- sh -c 'curl -s http://booking-api/healthz; curl -s http://booking-api/'
```

### Files created or changed

| File | What it does |
| --- | --- |
| `infra/envs/shared/*.tf` (+ lock) | New long-lived root: ECR repo, lifecycle "keep last 10", `Env=shared`, `Component=ecr` |
| `infra/bootstrap/ecr_push.tf`, `variables.tf`, `iam.tf` | `surgegate-gha-ecr-push` role + policy; added to the apply-role guardrails |
| `services/booking-api/app/main.py`, `tests/test_health.py` | FastAPI hello world and tests |
| `services/booking-api/Dockerfile`, `.dockerignore`, `requirements*.txt`, `pytest.ini` | Image build and test setup |
| `deploy/helm/booking-api/*` | Helm chart (Deployment, Service, helpers, values with `image.tag`) |
| `deploy/argocd/booking-api.yaml` | Argo CD Application → chart, namespace `booking`, auto-sync |
| `.github/workflows/build-deploy.yml` | The pipeline |
| `ruff.toml` | `app` is a first-party package for import sorting |
| `.gitignore` | `.helm/` cache (same line as PR #7) |
| Repo variable `AWS_ECR_PUSH_ROLE_ARN`, secret `DEPLOY_KEY`, ruleset `main-protection` | CI settings |

## 3. How it works

**The loop (what happens on a merge):**

```text
merge to main (services/booking-api/** changed)
 └─ build-deploy.yml
     1. test     pytest + ruff
     2. build    docker build → image tagged with the first 12 chars of the commit SHA
     3. scan     Trivy: fail the run on any fixable CRITICAL vulnerability
     4. push     OIDC → role surgegate-gha-ecr-push → docker push to ECR (scan on push starts)
     5. report   poll ECR's scan result and print severity counts
     6. bump     checkout main with the DEPLOY_KEY, set image.tag in values.yaml, commit, push
 └─ Argo CD (polls Git every 60 s): booking-api Application is out of sync → helm upgrade
     → rolling update: new pods pull the image from ECR, readiness probe /healthz passes
     → old pods removed (maxUnavailable 0, so there's never zero capacity)
```

**Image tag = git SHA, and tags are immutable.** Every image is named after the commit it was built
from, and ECR refuses to overwrite a tag. So `7da4f848acb9` always means exactly one image (one
digest), and rolling back means pointing the chart at an older SHA. Because tags can't be reused,
the pipeline checks first whether the tag already exists and skips build and push on a re-run.

**Two scanners.** Trivy runs *before* the push and is a gate: CRITICAL with a fix available fails the
build, so a bad image never reaches ECR. ECR's basic scan runs *after* the push and is a record
kept with the image. Day 10 adds stricter gates.

**Three identities, each with one job:**

| Identity | Can do | Can't do |
| --- | --- | --- |
| `surgegate-gha-ecr-push` (OIDC, `main` only) | Log in to ECR; push, read and read scan results for `surgegate/booking-api` | Any other repo, delete images or the repo, read state, touch EKS |
| Deploy key (`DEPLOY_KEY`) | Push to `main`, bypassing the ruleset; the job only changes `image.tag` | Nothing in AWS |
| Argo CD (in the cluster) | Apply what's in Git | — CI never gets cluster credentials to deploy apps |

**Why a deploy key with a ruleset bypass.** `main` requires a PR and the `infra-plan` check. A bot
commit can't open a PR that triggers checks with the default `GITHUB_TOKEN`, so the tag bump would
be stuck. A repository *ruleset* (unlike classic branch protection) can name **deploy keys** as a
bypass actor. Only the holder of that one key, stored as an Actions secret, can push straight to
`main`. The bump commit only touches `values.yaml`, which isn't in the workflow's `paths`, so it
doesn't trigger another build (no loop).

**Hardened pod.** Runs as UID 10001, non-root, read-only root filesystem, all Linux capabilities
dropped, no privilege escalation, seccomp `RuntimeDefault`, no service-account token mounted. Probes
on `/healthz`, and pods spread across AZs.

## 4. Errors I hit and how I fixed them

| # | Error (exact message) | Cause | Fix |
| --- | --- | --- | --- |
| 1 | `failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine; … The system cannot find the file specified.` | Docker Desktop isn't running on the laptop. | Didn't start it; the image is built in CI. The chart and Dockerfile were checked by lint/dry-run and by the real CI build. |
| 2 | `Error: Could not retrieve providers for locking` and `lookup sts.ap-south-1.amazonaws.com: no such host` | Short DNS failure on the laptop's network. | Retried a minute later; both worked. |
| 3 | `I001 [*] Import block is un-sorted or un-formatted --> tests\test_health.py:1:1` | ruff didn't know `app` is our own package, so it sorted it as third-party. | Added `[lint.isort] known-first-party = ["app"]` to `ruff.toml`. |
| 4 | `StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated; install httpx2 instead.` | Deprecation warning from the test client. | Tried to switch to `httpx2`; the sandbox blocked installing a package whose name came only from a warning (typosquat risk). Kept `httpx`; tests pass. |
| 5 | `Error from server (NotFound): error when creating "STDIN": namespaces "booking" not found` | Server dry-run into a namespace that doesn't exist yet (Argo CD creates it with `CreateNamespace=true`). | Re-ran the dry-run into `default`: Deployment and Service valid. |
| 6 | (Caught before push) `infra/envs/dev/.helm/cache/*.tgz` staged in the commit | This branch came from `main`, which didn't yet have the `.helm/` ignore line from PR #7. | `git rm -r --cached`, added the same ignore line, amended the **local** commit. Nothing was pushed. |
| 7 | `Post "https://api.github.com/graphql": unexpected EOF` (you, `gh repo deploy-key add`) | Network drop to GitHub's GraphQL endpoint. | Checked through the REST API that no key had been added; you retried successfully. |
| 8 | `"message": "key is already in use"` (HTTP 422) | The REST fallback command added the same key a second time after the retry had worked. | Expected; nothing to do. Verified: one read-write key matching the local key. |
| 9 | `mergeable: CONFLICTING` on PR #8 after #7's squash-merge | Same squash/stack situation as PR #3. | Checked `main` == PR #7 tip, then `git merge -X ours origin/main` on the branch (no force push). Diff stayed Task 2 only. |
| 10 | `aws: [ERROR]: Waiter ImageScanComplete failed: An error occurred (ScanNotFoundException): Image scan does not exist for the image with '{imageDigest:'null', imageTag:'7620d5b71b1e'}'` | Basic scan-on-push creates the scan record a few seconds after the push, and the waiter fails at once on `ScanNotFoundException` instead of retrying. The image had been built, Trivy-scanned and pushed. | PR #10: poll `describe-image-scan-findings` (up to about 3 min), and skip build/push if the immutable tag already exists so re-runs are safe. |

## 5. How I verified it works

**The trust and permissions of the ECR push role** (IAM policy simulator):

| Action | Resource | Result |
| --- | --- | --- |
| `ecr:PutImage`, `CompleteLayerUpload`, `DescribeImageScanFindings` | `surgegate/booking-api` | allowed |
| `ecr:GetAuthorizationToken` | `*` | allowed |
| `ecr:PutImage` | `surgegate/other-repo` | implicitDeny |
| `ecr:DeleteRepository`, `BatchDeleteImage`, `PutLifecyclePolicy` | `surgegate/booking-api` | implicitDeny |
| `s3:GetObject` (state), `eks:DescribeCluster` | — | implicitDeny |
| apply role → `iam:UpdateAssumeRolePolicy` on the push role | — | **explicitDeny** |

The trust is `sub = repo:sheshagiri-62@144677187/surgegate@1463328699:ref:refs/heads/main`,
`aud = sts.amazonaws.com`.

**The full loop, once, from merge to running pod** (PR #10 merge `7da4f848acb9`, run 44761340742,
all three jobs `success`):

1. **Test:** pytest and ruff pass.
2. **Build + Trivy:** report summary shows `0` vulnerabilities for `booking-api:7da4f848acb9
   (debian 13.7)` and the Python packages with the CRITICAL / fixable filter. Gate passed.
3. **Push:** `7da4f848acb9: digest: sha256:4133a71a6c5604ed751e29e6eefc3dfd4d326d6cb68b5f63b64515ba155ee31b`.
   ECR now holds `7620d5b71b1e` (first run) and `7da4f848acb9`.
4. **ECR scan:** `attempt 3: scan status COMPLETE`, then HIGH 3, MEDIUM 15, LOW 4 (no CRITICAL).
5. **Tag bump with the deploy key:** commit `ca93405 ci: deploy booking-api 7da4f848acb9` by
   `surgegate-build-deploy`, changing only `deploy/helm/booking-api/values.yaml`. It landed
   **directly on `main`** without a PR, which only the deploy-key bypass allows.
6. **Argo CD:** Application `booking-api` → `Synced/Healthy @ ca934056852e…` (the bump commit).
   Before this, the same app was correctly `Progressing` with `ImagePullBackOff` on the placeholder
   tag `none`.
7. **Pods:** 2 × `booking-api-77dcb8f685-*` Ready, image `…/booking-api:7da4f848acb9`, imageID
   `…@sha256:4133a71a…`, **the same digest the pipeline pushed**, on nodes `ip-10-20-32-71` (1b)
   and `ip-10-20-20-8` (1a).
8. **The app answers inside the cluster:** `GET /healthz` → `{"status":"ok"}`, `GET /` →
   `{"service":"booking-api","version":"7da4f848acb9"}`.

## 6. Cost impact

- **ECR:** about 49 MB per image × 2 images ≈ 0.1 GB × $0.10/GB-month ≈ **$0.01/month**.
  Basic scanning is free. Kept across `make down`; the lifecycle rule caps it at 10 images.
- **IAM role, deploy key, ruleset, GitHub Actions** (public repo): free.
- **Pods:** run on the existing nodes, so no change to the ≈ $0.256/h while the cluster is up.

## 7. Interview notes

- **Q:** Walk me through what happens when you merge to `main`.
  **A:** `build-deploy` tests, builds an image tagged with the commit SHA, blocks it if Trivy finds a
  fixable CRITICAL, pushes it to ECR through an OIDC role that can only push to that one repo, and
  commits the new tag to the Helm values with a deploy key. Argo CD sees the commit and does a
  rolling update. CI never touches the cluster, and the running pods' digest matches the pushed
  digest.

- **Q:** `main` requires a PR. How does your bot commit the tag?
  **A:** A repository ruleset with a deploy key as the only bypass actor. The private key is an
  Actions secret, and the job changes one line in one file. The bump doesn't match the workflow's
  path filter, so it doesn't trigger a loop. The alternatives were a personal token that opens and
  auto-merges PRs (tied to a person, slower) or Argo CD Image Updater (state lives outside Git).

- **Q:** Your first pipeline run failed after pushing. What happened and how did you make it safe?
  **A:** ECR's basic scan creates its scan record a few seconds after the push, and `aws ecr wait
  image-scan-complete` fails immediately on `ScanNotFoundException`. I replaced the waiter with a
  polling loop. Since tags are immutable, a re-run would also have failed on push, so the job now
  checks whether the tag exists and skips build/push. The pipeline is idempotent.

## 8. Next task

Day 2 · Task 4 — `edge` module (first part). Per your decision: the CloudFront default
`*.cloudfront.net` domain in front of the ALB (ALB security group limited to CloudFront's
origin-facing prefix list, plus a secret origin header from Secrets Manager); Route 53 and ACM kept
behind `var.domain_name`; ADR 003. Plan and costs shown before applying.
