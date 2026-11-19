# Week 1 · Task 02 — `infra/bootstrap`: state bucket, GitHub OIDC provider, plan and apply roles

- **Date:** 2026-11-19
- **Phase / milestone:** Phase 1 (Foundations) → M1
- **Status:** Done (applied and verified)
- **Commit / PR:** commits `c6997de` (infra), `8ff4acd` (docs), `a49fc88` (ADR 001 scope) · [PR #2](https://github.com/sheshagiri-62/surgegate/pull/2)

## 1. What the task was

Plan text: *"`infra/bootstrap`: S3 state bucket with versioning and native lock file; GitHub OIDC
provider; `plan` (read-only) and `apply` roles."*

Every later Terraform root (`envs/dev`, `envs/demo`) needs somewhere safe to keep its state, and the
CI pipelines need a way into AWS without stored keys. Bootstrap creates both, once, by hand.

The same session also covered your decisions: re-running the service checks after the plan upgrade,
renaming the two docs, adding `Env=shared` to CLAUDE.md, and writing ADR 002 (EventBridge + Kinesis).

## 2. What I did, step by step

1. **Read-only check: Kinesis.** Blocked (`SubscriptionRequiredException`); EventBridge buses and
   Pipes worked. Reported it; no docs changed until you decided.
2. **Wrote the Terraform** in `infra/bootstrap` (`versions`, `providers`, `variables`, `state`,
   `oidc`, `iam`, `outputs`). Pinned AWS provider `~> 6.73` (latest release, found with `gh api`).
3. **fmt → init → validate → tflint → plan -out.** Showed you the plan (14 resources, no hourly
   cost) and waited for your "yes".
4. **Re-ran service checks after your Paid-plan upgrade.** Account still reports `FREE`; Kinesis
   and MSK still blocked; EKS fine.
5. **Applied the saved plan file** (`terraform apply bootstrap.tfplan`) → 14 added.
6. **Migrated state into the bucket.** Added `backend.tf` and ran `terraform init -migrate-state`.
7. **Removed the hard-coded AWS profile** from the backend and provider. GitHub Actions has no
   `surgegate` profile, so CI would fail. Credentials now come from `AWS_PROFILE` locally and OIDC in
   CI. Re-initialised with `-reconfigure`.
8. **Verified:** a plan with no changes, the lock file appearing and disappearing during that plan,
   every bucket setting, both trust policies, and nine IAM policy simulations.
9. **Docs:** renamed `docs/*.md.md` → `docs/*.md` (your latest content), added `shared` to the Env
   tag rule in CLAUDE.md, wrote ADR 002, updated the checklist (Day 8 events task, decision lines).
10. **Committed** on `infra/bootstrap`. After PR #1 was squash-merged, rebased onto `main` and opened PR #2.

### Commands I ran

```bash
# 1. Kinesis / EventBridge read-only check
export AWS_PROFILE=surgegate AWS_REGION=ap-south-1
aws kinesis list-streams
aws kinesis describe-limits
aws kinesis describe-account-settings
aws events list-event-buses
aws pipes list-pipes

# 2–3. Write, check and plan (PowerShell, in infra/bootstrap)
gh api repos/hashicorp/terraform-provider-aws/releases/latest --jq .tag_name      # v6.73.0
terraform fmt -check -diff
terraform init -input=false
terraform validate
terraform providers lock -platform=windows_amd64 -platform=linux_amd64
tflint --init --config=../../.tflint.hcl
tflint --config=../../.tflint.hcl
terraform plan -input=false '-out=bootstrap.tfplan'

# 4. After the Paid-plan upgrade
aws freetier get-account-plan-state --region us-east-1
aws kinesis list-streams; aws kinesis describe-limits
aws kafka list-clusters-v2 --cluster-type-filter SERVERLESS
aws eks list-clusters
aws service-quotas get-service-quota --service-code ec2 --quota-code L-1216C47A

# 5–7. Apply and migrate state
terraform apply -input=false bootstrap.tfplan
terraform init -migrate-state -force-copy -input=false
terraform init -reconfigure -input=false        # after removing profile from backend.tf

# 8. Verify
terraform plan -input=false -detailed-exitcode   # while polling the bucket for *.tflock
aws s3api list-objects-v2 --bucket surgegate-tfstate-968077439619 --query 'Contents[].Key'
aws s3api get-bucket-versioning --bucket surgegate-tfstate-968077439619
aws s3api get-bucket-encryption --bucket surgegate-tfstate-968077439619
aws s3api get-public-access-block --bucket surgegate-tfstate-968077439619
aws s3api get-bucket-ownership-controls --bucket surgegate-tfstate-968077439619
aws s3api get-bucket-lifecycle-configuration --bucket surgegate-tfstate-968077439619
aws s3api get-bucket-tagging --bucket surgegate-tfstate-968077439619
aws s3api list-object-versions --bucket surgegate-tfstate-968077439619 --prefix bootstrap/
curl -s -o /dev/null -w "%{http_code}\n" http://surgegate-tfstate-968077439619.s3.ap-south-1.amazonaws.com/bootstrap/terraform.tfstate
aws iam get-role --role-name surgegate-gha-plan  --query 'Role.AssumeRolePolicyDocument.Statement[0].Condition'
aws iam get-role --role-name surgegate-gha-apply --query 'Role.AssumeRolePolicyDocument.Statement[0].Condition'
aws iam simulate-principal-policy --policy-source-arn arn:aws:iam::968077439619:role/surgegate-gha-apply \
  --action-names organizations:CreateOrganization --resource-arns '*'     # + 8 more, see section 5

# 9–10. Docs and commit
mv docs/blueprint.md.md docs/blueprint.md
mv docs/implementation-plan.md.md docs/implementation-plan.md
git switch -C infra/bootstrap feat/repo-skeleton
git add infra/bootstrap && git commit -m "infra: add bootstrap (state bucket, GitHub OIDC provider, plan and apply roles)"
gh pr merge 1 --squash
git fetch origin
git rebase --onto origin/main feat/repo-skeleton infra/bootstrap
git push --force-with-lease=infra/bootstrap:c9ada76 origin infra/bootstrap
gh pr create --base main --head infra/bootstrap --title "infra: bootstrap (state bucket, GitHub OIDC provider, plan and apply roles)"
```

### Files created or changed

| File | What it does |
| --- | --- |
| `infra/bootstrap/versions.tf` | Terraform ≥ 1.10 (needed for the native lock file), AWS provider `~> 6.73` |
| `infra/bootstrap/providers.tf` | Region + `default_tags` (`Project=surgegate`, `Env=shared`, `Component=bootstrap`); no profile in code |
| `infra/bootstrap/variables.tf` | Project, region, GitHub repo, allowed apply subjects, state version retention |
| `infra/bootstrap/state.tf` | State bucket + versioning, encryption, public access block, ownership, lifecycle, TLS-only policy |
| `infra/bootstrap/oidc.tf` | GitHub Actions OIDC identity provider |
| `infra/bootstrap/iam.tf` | `surgegate-gha-plan` and `surgegate-gha-apply` roles, trust policies, guardrail denies |
| `infra/bootstrap/outputs.tf` | Bucket name, OIDC provider ARN, both role ARNs |
| `infra/bootstrap/backend.tf` | S3 backend for bootstrap's own state, `use_lockfile = true` |
| `infra/bootstrap/.terraform.lock.hcl` | Provider checksums for Windows and Linux (so CI accepts them) |
| `infra/bootstrap/README.md` | How to use the backend, re-apply and tear down |
| `docs/blueprint.md`, `docs/implementation-plan.md` | Renamed from `.md.md`; your EventBridge + Kinesis edits |
| `docs/adr/002-eventbridge-kinesis-instead-of-msk.md` | ADR 002 |
| `CLAUDE.md` | Env tag values now `dev|demo|shared` |
| `docs/progress/CHECKLIST.md` | Task 2 ticked; stream decision; Day 8 events task text; ADR 001 scope |
| `docs/implementation-plan.md` (Day 1 Task 5) | ADR 001 now covers "SQS for jobs + EventBridge/Kinesis for events" |

## 3. How it works

**Terraform state and why it lives in S3.** Terraform keeps a file (the *state*) that maps your code to
real resources ("this `aws_s3_bucket.state` is bucket X"). If the state sits on one laptop, CI can't use
it and a lost disk means Terraform forgets what it built. Putting it in S3 with **versioning** means
every change keeps the old copy, so a bad apply or corrupted file can be rolled back.

**Locking with the native lock file.** Two runs at once (you and CI) could corrupt state. Terraform
1.10+ can lock by writing a small `<key>.tflock` object next to the state with an S3 conditional
write: whoever creates it first holds the lock, and the second run waits or fails. I watched this
happen: `bootstrap/terraform.tfstate.tflock` appeared during a plan and was deleted after it. Older
setups needed a DynamoDB table for this; now it's one setting, `use_lockfile = true`.

**The chicken-and-egg problem.** Bootstrap creates the bucket that will hold its own state, so its
first apply has to use local state. Then `terraform init -migrate-state` copies the state into the
bucket.

**GitHub OIDC: CI without stored keys.** When a GitHub Actions job runs, GitHub can give it a
short-lived signed token (a JWT) that says "I am repo `sheshagiri-62/surgegate`, running for a pull
request" (the `sub` claim). AWS trusts GitHub as an identity provider, checks the signature, and
compares the claims with the role's trust policy. If they match, STS returns credentials that last
up to one hour. No AWS keys are ever stored in GitHub, so there's nothing to leak or rotate.

**Two roles: least privilege by trigger.**
- `surgegate-gha-plan`: any pull request can run `terraform plan`, including PRs with untrusted
  changes, so this role is read-only. It may only write the `.tflock` files, because plan takes the
  lock.
- `surgegate-gha-apply`: only code on `main`, or a job in the protected `dev`/`demo` GitHub
  environments, can assume it. It needs broad rights (EKS, RDS, IAM roles for pods), so it has
  AdministratorAccess **plus explicit Deny statements**. In IAM an explicit Deny always beats an
  Allow, so even a bad pipeline can't create an Organization (which would end the Free-plan
  credits), create users or access keys, change the CI roles themselves, or delete or loosen the
  state bucket.

**How it fits SurgeGate.** From now on every environment uses this bucket (`envs/dev/…`,
`envs/demo/…`), `infra-plan.yml` (Task 3) uses the plan role, and `infra-apply.yml` and
`build-deploy.yml` use the apply side. That makes "Infrastructure only through Terraform" and
"never commit secrets" possible in practice.

## 4. Errors I hit and how I fixed them

| # | Error (exact message) | Cause | Fix |
| --- | --- | --- | --- |
| 1 | `An error occurred (SubscriptionRequiredException) when calling the ListStreams operation: The AWS Access Key Id needs a subscription for the service` | Kinesis Data Streams is blocked on the Free plan, like MSK. | Stopped and reported. You chose to upgrade to the Paid plan and keep EventBridge + Kinesis (ADR 002). |
| 2 | Account still `"accountPlanType": "FREE"` after the upgrade; Kinesis and MSK still give `SubscriptionRequiredException` | The upgrade hasn't taken effect yet (still propagating, or not completed). | Not fixable by me. Re-checked at the end of the task: still FREE. **Open item for you.** |
| 3 | `/usr/bin/bash: -c: line 174: unexpected EOF while looking for matching '` | A long multi-file heredoc script failed to parse in Git Bash, so nothing ran. | Wrote each `.tf` file separately with the editor tool. |
| 4 | `The term 'tflint' is not recognized as the name of a cmdlet, function, script file, or operable program.` | My PowerShell session started before PATH was fixed and kept the old PATH. | Reloaded PATH from the registry (`[Environment]::GetEnvironmentVariable('Path','User')`). |
| 5 | `Failed to initialize plugins; Plugin "aws" not found. Did you run "tflint --init"?` | `make init` ran under msys2 `make`, which sets `HOME=C:\msys64\home\shesh`, so the plugin was installed there. tflint run from PowerShell looks in `C:\Users\shesh\.tflint.d`. | Ran `tflint --init` from PowerShell too. Both homes now have the plugin. |
| 6 | `Error: Too many command line arguments` … `To specify a working directory for the plan, use the global -chdir flag.` | Windows PowerShell 5.1 splits `-out=bootstrap.tfplan` at the dot into two arguments. | Quoted it: `'-out=bootstrap.tfplan'`. |
| 7 | Command timed out after 300 s (moved to background) | `terraform providers lock` for two platforms plus the failing plan took longer than the tool's timeout. | Re-ran plan on its own (it takes a few seconds). |
| 8 | (Design bug, no error message) `profile = "surgegate"` hard-coded in `backend.tf` and the provider | That would break CI: GitHub runners have no such profile and use OIDC credentials instead. | Removed the profile from code; set `AWS_PROFILE` in the environment (the Makefile already exports it). `terraform init -reconfigure`, then plan showed no changes. |
| 9 | `gh pr view 1` → `{"mergedAt":null,"state":"OPEN"}`; `origin/main` still at `50cd1a6` | PR #1 isn't merged on GitHub, although the message said it was. Recreating the branch from `origin/main` removed the Task 1 files from the working tree. | Recreated `infra/bootstrap` on top of `feat/repo-skeleton` (nothing lost). Later: `gh pr merge 1 --squash`, then `git rebase --onto origin/main feat/repo-skeleton infra/bootstrap` (drops the pre-squash Task 1 commits), `git push --force-with-lease` on the feature branch only, and opened PR #2. |

## 5. How I verified it works

- `terraform apply` → `Apply complete! Resources: 14 added, 0 changed, 0 destroyed.`
- After migrating state: `terraform plan -detailed-exitcode` → *"No changes"*, exit 0. Terraform
  reads the state from S3 and it matches AWS exactly.
- Lock file: polling the bucket during that plan showed `bootstrap/terraform.tfstate.tflock`, and
  after the plan only `bootstrap/terraform.tfstate` remained.
- Bucket: versioning `Enabled`, encryption `AES256`, public access block `True True True True`,
  ownership `BucketOwnerEnforced`, lifecycle `expire-old-state-versions 90`, tags
  `Project=surgegate Env=shared Component=bootstrap`. A plain HTTP request returns `403`.
- Trust policies: the plan role accepts only `repo:sheshagiri-62/surgegate:pull_request`; the apply
  role accepts only `…:ref:refs/heads/main`, `…:environment:dev`, `…:environment:demo`; both require
  `aud = sts.amazonaws.com`.
- IAM policy simulator:

  | Role | Action | Result |
  | --- | --- | --- |
  | apply | `organizations:CreateOrganization` | explicitDeny |
  | apply | `iam:CreateAccessKey` | explicitDeny |
  | apply | `s3:DeleteBucket` on the state bucket | explicitDeny |
  | apply | `iam:UpdateAssumeRolePolicy` on the plan role | explicitDeny |
  | apply | `eks:CreateCluster` | allowed |
  | plan | `ec2:DescribeVpcs` | allowed |
  | plan | `eks:CreateCluster` | implicitDeny |
  | plan | `s3:PutObject` on `envs/dev/terraform.tfstate.tflock` | allowed |
  | plan | `s3:PutObject` on `envs/dev/terraform.tfstate` | implicitDeny |

- The commit ran all pre-commit hooks, including `terraform_fmt` and `terraform_tflint`, and all passed.
- Not yet tested: actually assuming the roles from GitHub Actions. That happens in Task 3 (`infra-plan.yml`).

## 6. Cost impact

- **New billable resources:** one S3 bucket (a few KB of state, a handful of requests), effectively
  $0.00. IAM roles, policies and the OIDC provider are free.
- **Hourly items:** none.
- **Teardown:** not part of `make down`; this stays for the whole project. At the end: move state back
  to local, empty all object versions, remove `prevent_destroy`, `terraform destroy` (steps in
  `infra/bootstrap/README.md`).

## 7. Interview notes

- **Q:** How does GitHub Actions get into AWS without access keys?
  **A:** Through OIDC. GitHub signs a short-lived token describing the repo and trigger. AWS trusts
  GitHub as an identity provider, and a role's trust policy checks the `aud` and `sub` claims. If
  they match, STS returns temporary credentials that last up to an hour. Nothing long-lived is
  stored, so there's nothing to leak or rotate.

- **Q:** Why two CI roles instead of one?
  **A:** Least privilege by trigger. Pull requests can contain untrusted changes, so `plan` is
  read-only (plus the lock file). Only reviewed code on `main` or a protected environment can
  assume the `apply` role. Its admin rights are capped with explicit Denies: no Organizations, no
  access keys, no changes to its own trust, no deleting the state bucket.

- **Q:** How do you lock Terraform state without DynamoDB?
  **A:** Terraform 1.10+ supports `use_lockfile = true` on the S3 backend. It writes a
  `<key>.tflock` object with a conditional "create only if it doesn't exist" request, so only one
  run can hold it. I saw the lock file appear during a plan and disappear afterwards.

## 8. Next task

Day 1 · Task 3 — `infra-plan.yml`: on every pull request, run `terraform fmt`, `validate`, `tflint`
and post the plan as a comment (first real use of the `surgegate-gha-plan` role).
