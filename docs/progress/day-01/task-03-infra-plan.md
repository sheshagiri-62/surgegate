# Week 1 · Task 03 — `infra-plan.yml`: fmt, validate, tflint and plan comment on every PR

- **Date:** 2026-11-19
- **Phase / milestone:** Phase 1 (Foundations) → M1
- **Status:** Done
- **Commit / PR:** `ci: add infra-plan workflow …`, `fix: trust GitHub immutable OIDC subject …` · [PR #3](https://github.com/sheshagiri-62/surgegate/pull/3) (stacked on [PR #2](https://github.com/sheshagiri-62/surgegate/pull/2)) · passing run [44465135684](https://github.com/sheshagiri-62/surgegate/actions/runs/44465135684)

## 1. What the task was

Plan text: *"`infra-plan.yml`: on every pull request, run `terraform fmt`, `validate`, `tflint` and post
the plan as a comment."*

Every infrastructure change should be reviewed as a plan ("what will Terraform create, change or
destroy?") before it is merged. Running this automatically on each PR is the first half of
"infrastructure only through the pipeline". It's also the first real test of the read-only OIDC
role from Task 2.

The same session also merged PR #1, rebased `infra/bootstrap` onto `main`, opened PR #2, and updated
the ADR 001 line in the plan (see the Task 2 report).

## 2. What I did, step by step

1. **Branch `ci/infra-plan` from `infra/bootstrap`.** PR #2 wasn't merged yet, and the workflow needs
   a real Terraform root to plan, so PR #3 targets `infra/bootstrap`.
2. **Looked up the latest release of each action** and **pinned each one to its commit SHA**.
3. **Wrote `.github/workflows/infra-plan.yml`** with three jobs: `detect` (find roots), `fmt`, and a
   `plan` matrix (one job per root).
4. **Tried to lint the workflow locally.** Docker Desktop wasn't running, and downloading the
   actionlint binary was blocked by the sandbox. I relied on the `check-yaml` hook and the real run.
5. **Set the repo variable** `AWS_PLAN_ROLE_ARN` (an ARN is not a secret).
6. **Opened PR #3.** The first run **failed** at the AWS login step (error 3 below).
7. **Found the cause:** this repo uses GitHub's *immutable* OIDC subject format, so the token's `sub`
   didn't match the trust policy. Fixed `infra/bootstrap` (new variable
   `github_oidc_subject_prefix`), ran fmt/validate/tflint/plan (0 add, **2 change**, 0 destroy, IAM
   only, free) and applied the saved plan.
8. **Pushed the fix.** The second run **passed**: the job assumed `surgegate-gha-plan`, and the bot
   posted the plan comment "✅ No changes".

### Commands I ran

```bash
git switch -c ci/infra-plan
for r in actions/checkout hashicorp/setup-terraform aws-actions/configure-aws-credentials \
         terraform-linters/setup-tflint actions/github-script rhysd/actionlint; do
  gh api repos/$r/releases/latest --jq .tag_name; done
gh api repos/actions/checkout/commits/v7.0.1 --jq .sha        # same for every action
git rm .github/workflows/.gitkeep
docker run --rm -v "$(pwd -W):/repo" -w /repo rhysd/actionlint:1.7.12     # failed: Docker not running
gh variable set AWS_PLAN_ROLE_ARN --body "arn:aws:iam::968077439619:role/surgegate-gha-plan"
git commit -m "ci: add infra-plan workflow (fmt, validate, tflint, plan comment on PRs)"
git push -u origin ci/infra-plan
gh pr create --base infra/bootstrap --head ci/infra-plan --title "ci: infra-plan workflow (fmt, validate, tflint, plan comment)"
gh pr checks 3 --watch --interval 10
gh run view 44464799538 --log-failed

# Diagnose and fix the OIDC trust
gh api repos/sheshagiri-62/surgegate/actions/oidc/customization/sub
aws cloudtrail lookup-events --region ap-south-1 --lookup-attributes AttributeKey=EventName,AttributeValue=AssumeRoleWithWebIdentity
cd infra/bootstrap
terraform fmt -check && terraform validate && tflint --config=../../.tflint.hcl
terraform plan -input=false '-out=trust-fix.tfplan'
terraform apply -input=false trust-fix.tfplan
git commit -m "fix: trust GitHub immutable OIDC subject in bootstrap CI roles" && git push

# Verify
gh pr checks 3 --watch --interval 10
gh run view 44465135684 --log
gh api repos/sheshagiri-62/surgegate/issues/3/comments
```

### Files created or changed

| File | What it does |
| --- | --- |
| `.github/workflows/infra-plan.yml` | The workflow: detect roots → fmt → per-root init/validate/tflint/plan → sticky PR comment |
| `infra/bootstrap/variables.tf` | `github_repo` replaced by `github_oidc_subject_prefix` (immutable format) |
| `infra/bootstrap/iam.tf` | Both trust policies use the immutable subject prefix |
| GitHub repo variable `AWS_PLAN_ROLE_ARN` | ARN of the read-only plan role |

## 3. How it works

**What the workflow does, in order:**

1. **Trigger:** any pull request that changes `infra/**`, `.tflint.hcl` or the workflow itself.
2. **`detect`:** lists the Terraform *roots*, the folders you run `terraform plan` in
   (`infra/bootstrap`, and `infra/envs/dev` and `demo` once they have code), and outputs them as a
   JSON list. Modules aren't planned on their own; they get checked through the roots that use them.
3. **`fmt`:** `terraform fmt -check -recursive infra` fails if any file isn't formatted.
4. **`plan` (one job per root, in parallel):**
   - Logs into AWS with **OIDC**. The job asks GitHub for a signed token, and
     `configure-aws-credentials` swaps it with AWS STS for one-hour credentials for
     `surgegate-gha-plan`. No AWS keys are stored in GitHub.
   - `terraform init -lockfile=readonly` (CI may not change provider versions), then `validate`,
     then `tflint` (AWS rules, e.g. invalid instance types), then
     `plan -detailed-exitcode -lock-timeout=2m` (0 = no changes, 2 = changes, 1 = error).
   - Posts the plan as a **sticky comment**: one comment per root, found by a hidden marker
     `<!-- infra-plan:infra/bootstrap -->` and updated on every push, not duplicated.

**Security choices:**
- The workflow's default permission is `contents: read`. Only the plan job gets `id-token: write`
  (for OIDC) and `pull-requests: write` (for the comment).
- Pull requests from **forks** are refused. Fork PRs get no OIDC token anyway, and the role trusts
  only this repo.
- Every action is **pinned to a commit SHA**, not a tag. A tag can be moved to malicious code, but a
  commit SHA can't change.
- The plan role is read-only. A PR that changes Terraform can *show* a plan but never *apply* it.

**GitHub's immutable OIDC subject (the bug I hit).** The OIDC token has a `sub` claim that the AWS
trust policy checks. The classic format is `repo:owner/name:pull_request`. This repo uses the newer
immutable format, which adds the numeric owner and repo IDs:
`repo:sheshagiri-62@144677187/surgegate@1463328699:pull_request`. IDs never change, so if the repo
were renamed or deleted and someone re-created one with the same name, their workflows still
couldn't assume our roles. The trust policies now match this format.

**How it fits SurgeGate.** From now on every infrastructure PR (network, eks, data …) shows its plan
right in the PR, made with real AWS reads but no write access. `infra-apply.yml` later applies only
what was reviewed and merged, using the apply role.

## 4. Errors I hit and how I fixed them

| # | Error (exact message) | Cause | Fix |
| --- | --- | --- | --- |
| 1 | `failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine; check if the path is correct and if the daemon is running` | Docker Desktop wasn't running, so the actionlint container couldn't start. | Skipped local actionlint; relied on the `check-yaml` hook and the real GitHub run. |
| 2 | `Permission for this action was denied by the Claude Code auto mode classifier. Reason: [Unauthorized Access]` | Downloading and running the actionlint release binary was blocked by the local sandbox. | Didn't work around it. Same fallback as error 1. |
| 3 | `##[error]Could not assume role with OIDC: Not authorized to perform sts:AssumeRoleWithWebIdentity` | The repo uses GitHub's immutable OIDC subject (`gh api …/actions/oidc/customization/sub` → `"use_immutable_subject":true,"sub_claim_prefix":"repo:sheshagiri-62@144677187/surgegate@1463328699"`), but the trust policies expected `repo:sheshagiri-62/surgegate:…`. | Added `github_oidc_subject_prefix` to bootstrap and used it in both trust policies. Ran plan (2 in-place changes) and applied. The next run passed. |
| 4 | `no checks reported on the 'ci/infra-plan' branch` | `gh pr checks --watch` ran a few seconds after the push, before GitHub had registered the new run. | Ran the watch again. |
| 5 | CloudTrail `lookup-events` for `AssumeRoleWithWebIdentity` returned nothing | Failed STS calls take several minutes to show up in CloudTrail event history. | Not needed: the GitHub API showed the `sub` format directly. |

## 5. How I verified it works

- Run [44465135684](https://github.com/sheshagiri-62/surgegate/actions/runs/44465135684): `Find
  Terraform roots` pass, `terraform fmt` pass, `plan (infra/bootstrap)` pass.
- The "Who am I" step printed
  `arn:aws:sts::968077439619:assumed-role/surgegate-gha-plan/infra-plan-pr3`, which proves OIDC
  login to the read-only role works.
- PR #3 has a bot comment: **"Terraform plan — `infra/bootstrap` — ✅ No changes"** with the plan in
  a collapsible block. That also confirms that local state, S3 state and AWS all agree after the
  trust fix.
- The earlier failed run 44464799538 shows the trust check working: a token that doesn't match is
  refused.
- **Not exercised in CI yet:** a badly formatted file (the `fmt` failure path), a plan with changes
  (status "📝 Changes"), and the sticky comment being *updated* rather than created. These happen
  naturally with Task 4's `network` module PR.

## 6. Cost impact

None. GitHub Actions minutes are free for public repos. The IAM trust change is free, and nothing
billable was created.

## 7. Interview notes

- **Q:** How does your pipeline run `terraform plan` against AWS without storing credentials?
  **A:** GitHub OIDC. The job requests a signed token, and AWS STS checks it against the OIDC
  provider and the role's trust policy (audience `sts.amazonaws.com`, subject = this repo's PRs).
  It then returns one-hour credentials for a read-only role, so there's nothing to leak or rotate.

- **Q:** Your first run failed with `Not authorized to perform sts:AssumeRoleWithWebIdentity`. How did
  you debug it?
  **A:** That error nearly always means the token's claims don't match the trust policy. I checked
  the repo's OIDC subject settings with the GitHub API and found it uses the immutable format with
  owner and repo IDs. I updated the trust policies to that format through Terraform, with a
  reviewed plan showing only the two trust policies changing, and the next run passed.

- **Q:** Why pin GitHub Actions to commit SHAs?
  **A:** Tags are mutable. If an action's repo were compromised, the attacker could move `v4` to
  malicious code that runs with my AWS role. A full commit SHA can't be changed, so I get exactly
  the code I reviewed.

## 8. Next task

Day 1 · Task 4 — `network` module: VPC, two AZs, public/private/data subnets, one NAT, S3 and
DynamoDB gateway endpoints. (The NAT gateway bills by the hour, so I will show the plan and cost and
wait for your "yes".)
