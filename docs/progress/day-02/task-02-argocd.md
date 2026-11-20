# Week 1 · Day 2 · Task 02 — Install Argo CD on the cluster; point it at `deploy/argocd`

- **Date:** 2026-11-20
- **Phase / milestone:** Phase 1 (Foundations) → M1
- **Status:** Done
- **Commit / PR:** [PR #8](https://github.com/sheshagiri-62/surgegate/pull/8) (stacked on [PR #7](https://github.com/sheshagiri-62/surgegate/pull/7))

## 1. What the task was

Plan text: *"Install Argo CD on the cluster; point it at `deploy/argocd`."*

Argo CD is the GitOps tool that deploys SurgeGate's services to EKS. Instead of CI running
`kubectl apply`, CI only changes Git (bumps an image tag), and Argo CD, running inside the
cluster, notices and makes the cluster match Git. M1's "a merge to `main` deploys a hello-world API
to EKS through Argo CD" depends on this.

## 2. What I did, step by step

1. Branch `infra/argocd` from `infra/eks` (PR #7 not merged yet).
2. Looked up chart versions: `argo-cd` 10.18.2 (Argo CD v3.6.2), `argocd-apps` 2.0.8. Read their
   values to get the exact keys.
3. Added two `helm_release`s to `infra/modules/eks`: `argocd` (lean dev values) and
   `argocd_root_app` (the root Application). Passed the repo URL, path and branch from
   `infra/envs/dev`.
4. Replaced `deploy/argocd/.gitkeep` with a README explaining the app-of-apps convention.
5. fmt → validate → tflint → `plan -out` (hit a state lock held by CI, retried with
   `-lock-timeout`): **2 to add**, nothing new in AWS, so no extra cost.
6. Applied the saved plan, then verified pods, root Application status, the Git revision, API login
   and drift.

### Commands I ran

```bash
git switch -c infra/argocd
helm repo add argo https://argoproj.github.io/argo-helm && helm repo update argo
helm search repo argo/argo-cd --versions
helm search repo argo/argocd-apps --versions
gh api repos/argoproj/argo-cd/releases/latest --jq .tag_name
helm show values argo/argocd-apps --version 2.0.8
helm show values argo/argo-cd --version 10.18.2 | grep -nE '^(dex|notifications|server|configs):'
git rm deploy/argocd/.gitkeep

# PowerShell, AWS_PROFILE=surgegate
terraform fmt -recursive                                 # in infra/
cd infra/envs/dev
terraform validate
tflint --config=../../../.tflint.hcl --call-module-type=local
terraform plan -input=false '-out=argocd.tfplan'          # Error acquiring the state lock (CI run)
aws s3api list-objects-v2 --bucket surgegate-tfstate-968077439619
terraform plan -input=false -lock-timeout=3m '-out=argocd.tfplan'    # 2 to add
terraform apply -input=false -lock-timeout=3m argocd.tfplan

# Verify
kubectl get pods -n argocd
kubectl get application root -n argocd -o jsonpath='{.status.sync.status} / {.status.health.status} @ {.status.sync.revision}'
git ls-remote https://github.com/sheshagiri-62/surgegate.git refs/heads/main
kubectl -n argocd port-forward svc/argocd-server 18080:80 &
curl -X POST http://127.0.0.1:18080/api/v1/session -d '{"username":"admin","password":"…"}'   # token, not printed
curl http://127.0.0.1:18080/api/v1/applications -H "Authorization: Bearer …"
curl http://127.0.0.1:18080/api/version
terraform plan -input=false -lock-timeout=3m -detailed-exitcode     # no changes
```

### Files created or changed

| File | What it does |
| --- | --- |
| `infra/modules/eks/main.tf` | `helm_release.argocd` (Argo CD) and `helm_release.argocd_root_app` (root Application) |
| `infra/modules/eks/variables.tf` | Chart versions; `gitops_repo_url`, `gitops_path`, `gitops_revision` |
| `infra/envs/dev/main.tf` | Points Argo CD at `https://github.com/sheshagiri-62/surgegate.git`, `deploy/argocd`, `main` |
| `deploy/argocd/README.md` | The app-of-apps convention and how to open the UI (replaces `.gitkeep`) |

## 3. How it works

**GitOps, simply.** Git is the single source of truth for what runs in the cluster. A controller
inside the cluster (Argo CD) keeps comparing *desired state* (manifests in Git) with *live state*
(what's running). When they differ it *syncs*: it applies Git's version. So:

- To deploy, you merge a change to `main`. Nobody runs `kubectl apply` by hand, and CI never needs
  cluster-admin credentials to deploy apps.
- To roll back, you revert the commit.
- With **self-heal** on, a manual `kubectl edit` is reverted within about a minute. With **prune**
  on, deleting a manifest from Git deletes the resource.

**App of apps.** Terraform creates exactly one Argo CD `Application`, called `root`. It watches the
folder `deploy/argocd` on `main`, and every `*.yaml` in that folder is itself an `Application`
(one per service, each pointing at a Helm chart in `deploy/helm/<service>`). Adding a new service is
then just adding a file in Git. Terraform never needs to change, and Terraform stays responsible for
the platform (cluster, controllers, Argo CD) while Argo CD is responsible for the apps.

**Why Terraform installs Argo CD.** The cluster is created and destroyed every session (`make up` /
`make down`). Installing Argo CD in the same Terraform run means a fresh cluster comes back already
connected to Git and redeploys every app by itself.

**Dev settings.** Single replicas, no Dex (SSO) and no notifications, so fewer pods on two small
nodes. `server.insecure = true` because TLS will end at the ALB, and today the UI is reached by
`kubectl port-forward` only. Git is polled every 60 s (`timeout.reconciliation`). The repo is public,
so no Git credentials are stored in the cluster.

**How it fits SurgeGate.** Task 3 adds `deploy/helm/booking-api` and
`deploy/argocd/booking-api.yaml`. `build-deploy.yml` builds the image, pushes it to ECR and commits
the new tag, and Argo CD rolls it out. That's the M1 "merge to main deploys through Argo CD" flow.

## 4. Errors I hit and how I fixed them

| # | Error (exact message) | Cause | Fix |
| --- | --- | --- | --- |
| 1 | `Error: Error acquiring the state lock` … `StatusCode: 412` … `api error PreconditionFailed: At least one of the pre-conditions you specified did not hold` … `Who: runner@runnervm0hi8g` `Operation: OperationTypePlan` | The S3 native lock was working as designed. My docs push to PR #7 re-ran `infra-plan`, and the CI runner held the lock on `envs/dev/terraform.tfstate` while it planned. S3's conditional write ("create only if absent") returned 412 to my second writer. | Checked the bucket (the lock was already released) and retried with `-lock-timeout=3m`, so Terraform waits for the lock instead of failing. I'll use `-lock-timeout` for every local plan/apply from now on. |

## 5. How I verified it works

- **Apply:** `helm_release.argocd: Creation complete after 2m1s`,
  `helm_release.argocd_root_app: Creation complete after 4s`, `2 added, 0 changed, 0 destroyed`.
- **Pods (argocd namespace), all `1/1 Running`:** application-controller, applicationset-controller,
  redis, repo-server, server.
- **Root app:** `Synced / Healthy @ efa49ea86ba1340584269c25a585e54c23234dc6`, the same commit as
  `main` on GitHub (`git ls-remote`). Source `https://github.com/sheshagiri-62/surgegate.git`,
  `deploy/argocd`, `main`. No error conditions.
- **API login:** through `kubectl port-forward`, `POST /api/v1/session` as `admin` returned a token
  (neither the password nor the token was printed). `GET /api/v1/applications` → `root Synced
  Healthy`. `GET /api/version` → `Argo CD v3.6.2`.
- **Capacity:** 14 pods in the cluster across 2 nodes (about 17 pods per t3.medium).
- **Drift:** `terraform plan -detailed-exitcode` → no changes.
- **Not yet shown:** an app actually deployed from Git. The root app has nothing to deploy until
  Task 3 adds the hello-world API, and that's M1's end-to-end test.

## 6. Cost impact

No new AWS resources: Argo CD runs as 5 pods on the existing 2 nodes. Hourly cost is unchanged at
about $0.256/h (EKS + nodes + NAT). It's removed with the cluster by `make down`.

## 7. Interview notes

- **Q:** What is GitOps and why use Argo CD instead of `kubectl apply` in CI?
  **A:** Git holds the desired state, and a controller in the cluster pulls and applies it,
  continuously correcting drift. CI never needs cluster credentials to deploy apps, every deployment
  is a reviewed commit, rollback is `git revert`, and self-heal undoes manual changes.

- **Q:** What is the "app of apps" pattern?
  **A:** One root Argo CD Application whose source is a folder of other Application manifests.
  Terraform creates only the root, and each service adds its own Application file in Git. New
  services need no Terraform change, and the whole set of apps is versioned together.

- **Q:** Your plan failed with a 412 on the state lock. What happened?
  **A:** The S3 backend's native lock writes `<state>.tflock` with a conditional "only if it doesn't
  exist" request. A CI plan was holding it, so S3 rejected my write with 412 PreconditionFailed.
  That's the lock preventing two runs from using the same state at once. I retried with
  `-lock-timeout` so Terraform waits instead of failing.

## 8. Next task

Day 2 · Task 3 — ECR repository; `build-deploy.yml` builds a hello-world FastAPI image, scans it,
pushes it, bumps the Helm tag.
