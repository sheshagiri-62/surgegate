# Week 1 · Task 01 — Create the repo structure, Makefile, pre-commit hooks and a README stub

- **Date:** 2026-11-19
- **Phase / milestone:** Phase 1 (Foundations) → M1
- **Status:** Done
- **Commit / PR:** commit `5f37957` · [PR #1](https://github.com/sheshagiri-62/surgegate/pull/1)

## 1. What the task was

Set up the empty monorepo the rest of the plan builds on: the folder layout from the plan, a
`Makefile` for everyday commands, pre-commit hooks that check code before every commit, and a short
README. SurgeGate needs this first so every later task has a fixed home and every commit is checked
the same way (formatting, lint, no secrets).

Before the task I also ran the Day 1 read-only Free-plan check (section 2, step 0).

## 2. What I did, step by step

0. **Free-plan check (read-only, nothing created).** Confirmed my identity and the account plan, then
   called list/describe APIs for EKS, MSK and WAF. EKS and WAF answered normally; **MSK refused with
   `SubscriptionRequiredException`**, which means the Free plan blocks it.
1. **Checked local tools.** Terraform, AWS CLI, kubectl, Helm, Docker, Node, k6 and gh were already
   installed. Missing: `make`, `pre-commit`, `ruff`, `tflint`, Argo CD CLI. Python 3.12 is installed
   (via the `py` launcher), but the `python` on PATH is msys2's 3.14.
2. **Created branch** `feat/repo-skeleton`.
3. **Installed tools.** `pre-commit` and `ruff` into Python 3.12 with pip; `tflint` with winget.
   GNU make was already on disk inside msys2 (`C:\msys64\usr\bin\make.exe`), just not on PATH.
4. **Created the folder layout** from the plan, with an empty `.gitkeep` in each folder (Git does
   not track empty folders).
5. **Wrote config files:** `.gitignore`, `.gitattributes`, `.pre-commit-config.yaml`, `.tflint.hcl`,
   `ruff.toml`, `Makefile`, `README.md`. Hook and plugin versions pinned to the latest releases
   (looked up with `gh api`).
6. **Tested the Makefile**, found and fixed a bug in `make load` (see errors).
7. **Ran `make init` and `make lint`**, then a negative test (a bad Terraform file and a fake private
   key) to prove the hooks really catch problems.
8. **Wrote** `docs/progress/CHECKLIST.md` and `docs/progress/README.md`, committed, pushed, opened PR #1.

### Commands I ran

```bash
# Step 0 — Free-plan check (read-only)
export AWS_PROFILE=surgegate AWS_REGION=ap-south-1
aws sts get-caller-identity
aws freetier get-account-plan-state --region us-east-1
aws eks list-clusters
aws eks describe-cluster-versions --query 'clusterVersions[0:3].[clusterVersion,versionStatus]' --output text
aws service-quotas list-service-quotas --service-code eks --query 'Quotas[?contains(QuotaName,`Clusters`)].[QuotaName,Value]' --output text
aws kafka list-clusters-v2 --cluster-type-filter SERVERLESS
aws service-quotas list-service-quotas --service-code kafka --query 'Quotas[].[QuotaName,Value]' --output text
aws wafv2 list-web-acls --scope REGIONAL
aws wafv2 list-web-acls --scope CLOUDFRONT --region us-east-1
aws wafv2 list-available-managed-rule-groups --scope CLOUDFRONT --region us-east-1 --query 'ManagedRuleGroups[?contains(Name,`Bot`)].Name' --output text
aws service-quotas get-service-quota --service-code ec2 --quota-code L-1216C47A --query 'Quota.Value'

# Steps 1–3 — branch and tools
git switch -c feat/repo-skeleton
py -3.12 -m pip install --user --quiet pre-commit ruff
winget install --id ezwinports.make -e --silent          # failed (DNS), not needed: msys2 has make
winget install --id TerraformLinters.tflint -e --silent  # failed (ambiguous source)
winget install --id TerraformLinters.tflint -e --source winget --silent
gh api repos/terraform-linters/tflint-ruleset-aws/releases/latest --jq .tag_name   # v0.50.0
gh api repos/antonbabenko/pre-commit-terraform/releases/latest --jq .tag_name     # v1.109.5
gh api repos/astral-sh/ruff-pre-commit/releases/latest --jq .tag_name             # v0.17.5
gh api repos/pre-commit/pre-commit-hooks/releases/latest --jq .tag_name           # v6.0.0

# Step 4 — folders
for d in infra/bootstrap infra/modules/{network,eks,data,edge,queue,async,events,observability,security,cost} \
  infra/envs/{dev,demo} services/{booking-api,queue,workers,event-consumers} web/{buyer,organiser} \
  deploy/{helm,argocd} tests/load/k6 tests/chaos/fis .github/workflows; do mkdir -p $d && touch $d/.gitkeep; done

# Steps 6–7 — test (PowerShell, with make/pre-commit/tflint added to PATH for the session)
make help; make up; make down; make down ENV=prod; make test; make load
make init
make lint
pre-commit run --files infra/modules/zz_hooktest/main.tf infra/modules/zz_hooktest/fake.txt   # negative test, folder deleted after

# Step 8 — commit and PR
git add -A; git add --renormalize .
git commit -m "feat: create repo structure, Makefile, pre-commit hooks and README stub"
git push -u origin feat/repo-skeleton
gh pr create --base main --title "feat: repo structure, Makefile, pre-commit hooks and README stub"
```

### Files created or changed

| File | What it does |
| --- | --- |
| `infra/…`, `services/…`, `web/…`, `deploy/…`, `tests/…`, `.github/workflows/` | Folder layout from the plan (`.gitkeep` placeholders) |
| `Makefile` | `help`, `init`, `fmt`, `lint`, `test`, `up`, `down`, `load`; `ENV=dev\|demo` only |
| `.pre-commit-config.yaml` | Hooks run on every commit: whitespace/YAML checks, private-key and AWS-key detection, `terraform fmt`, `tflint`, `ruff` |
| `.tflint.hcl` | tflint rules: Terraform "recommended" preset + AWS ruleset 0.50.0 |
| `ruff.toml` | Python lint/format rules for all services (py312, line length 100, includes security rules `S`) |
| `.gitignore` | Keeps state files, `*.tfvars`, plans, `.env`, keys, kubeconfig, build output out of Git |
| `.gitattributes` | Forces LF line endings so Makefile and shell scripts work on Windows and Linux CI |
| `README.md` | Stub: what SurgeGate is, cost warning, layout, getting started, doc links |
| `docs/progress/CHECKLIST.md` | Every setup item and every task for all 12 days, plus M1–M6 |
| `docs/progress/README.md` | Progress log, one line per task |

## 3. How it works

**Monorepo.** One Git repository holds infrastructure, backend, frontends and tests. A single pull
request can change an API *and* the Terraform it needs, so the two never drift apart.

**Makefile.** A file of named shortcuts. `make lint` is easier to remember than
`pre-commit run --all-files`, and everyone (and CI) runs exactly the same command. In SurgeGate the
most important targets are `make up` and `make down`, which will create and destroy the dev
environment each session to keep the bill near zero. Until Day 2 they are deliberately "honest
stubs": if there is no Terraform they say "nothing to destroy"; if Terraform exists but the target is
not wired yet, they **fail** with a warning to check the console, so nobody believes a teardown
happened when it didn't.

**pre-commit hooks.** Git can run a script before each commit. The `pre-commit` tool manages these
scripts: it downloads each hook at a pinned version and runs it on the files you are committing. If a
hook fails, the commit is blocked. For SurgeGate that means:

- `terraform fmt` and `tflint` catch badly formatted or invalid Terraform (for example an EC2
  instance type that does not exist) before it reaches `terraform plan`.
- `ruff` keeps the Python services consistent and flags insecure code.
- `detect-private-key` and `detect-aws-credentials` enforce safety rule 2: no secrets in Git.

The same checks run again in CI (`infra-plan.yml`, Task 3), so skipping them locally does not help.

**.gitignore / .gitattributes.** `.gitignore` stops state files (which can contain passwords) and
`*.tfvars` from being committed. `.gitattributes` keeps LF line endings, because Windows would
otherwise convert files to CRLF, which breaks `make` recipes and shell scripts.

## 4. Errors I hit and how I fixed them

| # | Error (exact message) | Cause | Fix |
| --- | --- | --- | --- |
| 1 | `An error occurred (SubscriptionRequiredException) when calling the ListClustersV2 operation: The AWS Access Key Id needs a subscription for the service` | The Free plan blocks Amazon MSK. | **Not fixed, on purpose.** Per the rules: stopped and reported. Decision pending (upgrade to Paid plan, or the plan's own fallback of EventBridge first). Not needed until Day 8. |
| 2 | `InternetOpenUrl() failed. 0x80072ee7 : unknown error` … `WinHttpSendRequest: 12007: The server name or address could not be resolved` | winget could not resolve the sourceforge download for `ezwinports.make` (a temporary DNS failure; `nslookup` worked a moment later). | Not needed: GNU make 4.4.1 was already installed with msys2 at `C:\msys64\usr\bin\make.exe`. |
| 3 | `The following packages were found among the working sources. Please specify one of them using the --source option to proceed.` | winget could not search the msstore source (same DNS problem), so it would not choose. | Re-ran with `--source winget`. |
| 4 | `make: *** [Makefile:53: load] Error 127` (k6 ran even though the script was missing) | In a Makefile each recipe line runs in its own shell, so `exit 0` on line 1 did not stop line 2. | Merged the check and `k6 run` into one `if … else … fi` command. |
| 5 | `ModuleNotFoundError: No module named 'pre_commit'` (from `make init` in Git Bash) | msys2's `make` started from Git Bash got an empty `APPDATA`. The two tools use different copies of the msys runtime, which don't pass the variable on. Without `APPDATA`, Python can't find the user site-packages where pre-commit is installed. | Run `make` from PowerShell (the normal terminal), where `APPDATA` is passed correctly. `make init` and `make lint` both passed there. |
| 6 | `warning: in the working copy of 'Makefile', LF will be replaced by CRLF the next time Git touches it` | `core.autocrlf` on Windows converts line endings, and CRLF breaks Makefile recipes and shell scripts. | Added `.gitattributes` with `* text=auto eol=lf` and ran `git add --renormalize .`. |
| 7 | `make help` printed `Create the $(ENV) environment` literally | Help text is read with `grep`, so make variables are not expanded. | Changed the text to "the ENV environment". |

## 5. How I verified it works

- `make lint` → every hook `Passed` (Terraform and ruff-check `Skipped`: no files yet).
- Negative test with a throwaway file: tflint reported
  `Error: "t9.nano" is an invalid value as instance_type (aws_instance_invalid_type)` and
  `detect-private-key` reported `Private key found: infra/modules/zz_hooktest/fake.txt` → hooks
  exit 1, so a commit would be blocked. (`terraform_fmt` showed "Passed" there because it fixed the
  untracked file in place; on a real staged commit it fails with "files were modified by this hook".)
- `make up` / `make down` → `No Terraform in infra/envs/dev yet — nothing to create/destroy.`;
  `make down ENV=prod` → `ENV must be dev or demo (got 'prod')`, exit 2.
- `make test` → `No service tests yet.`; `make load` → `No k6 script … yet.`, exit 0.
- The real commit ran all hooks and passed; PR #1 is open.

## 6. Cost impact

None. No AWS resources were created; every AWS call was read-only (list/describe/get).

## 7. Interview notes

- **Q:** Why a monorepo instead of separate repos for infra and services?
  **A:** One pull request can change an API and the infrastructure it needs together, CI runs one set
  of checks, and for a one-person project there is no team boundary that separate repos would serve.

- **Q:** What do pre-commit hooks give you if CI runs the same checks anyway?
  **A:** Faster feedback. Problems are caught in seconds on the laptop instead of minutes later in CI.
  Most importantly, secrets are blocked *before* they enter Git history, where removing them is hard,
  and once pushed to a public repo they must be treated as leaked.

- **Q:** Why do `make up`/`make down` fail instead of doing nothing while unfinished?
  **A:** `make down` is the cost-safety habit. A stub that silently succeeded could make me think the
  NAT gateway or EKS cluster was gone when it wasn't. Failing loudly is the safe default.

## 8. Next task

Day 1 · Task 2 — `infra/bootstrap`: S3 state bucket with versioning and native lock file; GitHub OIDC
provider; `plan` (read-only) and `apply` roles. (Creates a few low-cost resources, so I will show the
plan and wait for your "yes" before applying.)
