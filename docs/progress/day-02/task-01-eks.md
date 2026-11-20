# Week 1 · Day 2 · Task 01 — `eks` module: cluster, managed node group, Pod Identity, AWS Load Balancer Controller

- **Date:** 2026-11-20 (prepared 19 Nov, applied 20 Nov)
- **Phase / milestone:** Phase 1 (Foundations) → M1
- **Status:** Done (cluster kept running for Day 2 Tasks 2–5; `make down` at the end of the session)
- **Commit / PR:** [PR #7](https://github.com/sheshagiri-62/surgegate/pull/7) · CI run [44745015045](https://github.com/sheshagiri-62/surgegate/actions/runs/44745015045)

## 1. What the task was

Plan text: *"`eks` module: cluster, managed node group, Pod Identity, AWS Load Balancer Controller."*

The booking API and the organiser dashboard run on EKS (ADR 001). This task builds the cluster they
run on: the Kubernetes control plane, worker nodes in the private subnets, the Pod Identity agent
(how pods get AWS permissions), and the AWS Load Balancer Controller (turns a Kubernetes Ingress into
an AWS ALB, used for `api.<domain>` in Task 4).

The same session also created the `surgegate-monthly` AWS Budget and re-checked Kinesis/MSK and the
vCPU quota.

## 2. What I did, step by step

1. **Budget.** Showed the command, created `surgegate-monthly` ($45 monthly COST; email on ACTUAL
   > 33 / 66 / 100 % and FORECASTED > 100 %), verified with `describe-budgets`.
2. **Re-checks.** Kinesis and MSK still `SubscriptionRequiredException` on 19 and 20 Nov; vCPU quota
   8 (request for 16 `CASE_OPENED`). Drafted the AWS Support case text.
3. **Looked up current versions:** EKS module v21.30.2, eks-pod-identity v2.11.0, helm provider
   v3.3.0, Load Balancer Controller chart 3.6.3, EKS 1.37 (standard support until Dec 2027).
4. **Checked the community module's v21 input names** in its source before writing code, including
   how to turn off the customer KMS key (`encryption_config = null`).
5. **Wrote `infra/modules/eks`** (wrapper around the community module + Pod Identity role + Helm
   release) and wired it into `infra/envs/dev` behind `enable_eks`, with a validation that EKS needs
   the NAT gateway.
6. **Updated `make up` / `make down`** to switch EKS and NAT together and to list everything still
   billing afterwards.
7. **fmt → init → lock → validate → tflint → plan -out** (fixed two problems on the way, see errors),
   priced every hourly item with the AWS Pricing API, and waited for "yes".
8. **Applied** the saved plan after re-login: 46 added (cluster 9 min, node group 2 min, LB
   controller 38 s).
9. **Verified** nodes, pods, add-ons, Pod Identity, access entries and tags. Found that the node EC2
   instances lacked `Project`/`Env` tags, fixed it (plan: 2 add, 18 in-place, 0 destroy; node group
   rolled to new nodes in 8.5 min), and re-verified. Drift check: no changes.
10. **Pushed and opened PR #7.** CI failed on missing Linux provider checksums; re-locked, pushed,
    CI green, and the dev plan showed "No changes" through the CI plan role.

### Commands I ran

```bash
# Budget (JSON files in the scratchpad, not in the repo)
aws budgets create-budget --account-id 968077439619 \
  --budget file://budget.json --notifications-with-subscribers file://notifications.json
aws budgets describe-budgets --account-id 968077439619
aws budgets describe-notifications-for-budget --account-id 968077439619 --budget-name surgegate-monthly
aws budgets describe-subscribers-for-notification --account-id 968077439619 --budget-name surgegate-monthly \
  --notification NotificationType=ACTUAL,ComparisonOperator=GREATER_THAN,Threshold=33,ThresholdType=PERCENTAGE

# Re-checks (read-only)
aws freetier get-account-plan-state --region us-east-1
aws kinesis list-streams; aws kafka list-clusters-v2
aws service-quotas get-service-quota --service-code ec2 --quota-code L-1216C47A
aws service-quotas list-requested-service-quota-change-history-by-quota --service-code ec2 --quota-code L-1216C47A

# Versions and module inputs
git switch -c infra/eks
gh api repos/terraform-aws-modules/terraform-aws-eks/releases/latest --jq .tag_name
gh api repos/hashicorp/terraform-provider-helm/releases/latest --jq .tag_name
gh api repos/kubernetes-sigs/aws-load-balancer-controller/releases/latest --jq .tag_name
aws eks describe-cluster-versions --region ap-south-1
helm repo add eks https://aws.github.io/eks-charts && helm repo update eks
helm search repo eks/aws-load-balancer-controller --versions
gh api repos/terraform-aws-modules/terraform-aws-eks-pod-identity/releases/latest --jq .tag_name
gh api 'repos/terraform-aws-modules/terraform-aws-eks/contents/variables.tf?ref=v21.30.2' --jq .content | base64 -d | grep '^variable'
gh api 'repos/terraform-aws-modules/terraform-aws-eks/contents/main.tf?ref=v21.30.2' --jq .content | base64 -d | grep enable_encryption_config

# Check and plan (PowerShell, AWS_PROFILE=surgegate)
terraform fmt -recursive                    # in infra/
cd infra/envs/dev
terraform init -input=false -upgrade
terraform providers lock -platform=windows_amd64 -platform=linux_amd64
terraform validate
tflint --config=../../../.tflint.hcl --call-module-type=local
terraform plan -input=false '-out=up.tfplan'                               # failed: Error locating chart
terraform plan -input=false '-out=up.tfplan'                               # after the fix: 46 to add
terraform plan -var=enable_eks=true -var=enable_nat_gateway=false          # guard test: rejected
aws pricing get-products --region us-east-1 --service-code AmazonEKS ...   # + EC2, EBS, CloudWatch

# Apply
terraform apply -input=false up.tfplan     # 1st try: session expired, nothing created
aws login --profile surgegate              # (you)
terraform apply -input=false up.tfplan

# Verify
aws eks update-kubeconfig --name surgegate-dev --region ap-south-1 --alias surgegate-dev
kubectl get nodes -L topology.kubernetes.io/zone -L node.kubernetes.io/instance-type
kubectl get pods -n kube-system
kubectl get deploy -n kube-system aws-load-balancer-controller
kubectl logs -n kube-system deploy/aws-load-balancer-controller
kubectl get pod -n kube-system -l app.kubernetes.io/name=aws-load-balancer-controller -o jsonpath='{...env[*].name}'
aws eks describe-addon --cluster-name surgegate-dev --addon-name vpc-cni    # + the other 3
aws eks list-pod-identity-associations --cluster-name surgegate-dev
aws eks list-access-entries --cluster-name surgegate-dev
aws eks describe-cluster --name surgegate-dev --query cluster.tags
aws ec2 describe-instances --filters Name=tag:eks:cluster-name,Values=surgegate-dev ...
aws ec2 describe-volumes --filters Name=tag:eks:cluster-name,Values=surgegate-dev ...
aws resourcegroupstaggingapi get-resources --tag-filters Key=Env,Values=dev

# Tag fix (default_tags don't reach node instances)
terraform plan -input=false '-out=tagfix.tfplan'      # 2 add, 18 change, 0 destroy
terraform apply -input=false tagfix.tfplan
terraform plan -input=false -detailed-exitcode        # no changes

# PR
git push -u origin infra/eks
gh pr create --base main --head infra/eks --title "infra: eks module (...)"
gh pr checks 7 --watch                                # failed: lock file checksums
gh run view 44744414904 --log-failed
terraform providers lock -platform=windows_amd64 -platform=linux_amd64
git commit -m "fix: add linux_amd64 provider checksums to dev lock file" && git push
gh pr checks 7 --watch                                # green
```

### Files created or changed

| File | What it does |
| --- | --- |
| `infra/modules/eks/main.tf` | Community EKS module (cluster, access entries, add-ons, node group), Pod Identity role for the LB controller, Helm release of the controller |
| `infra/modules/eks/variables.tf` | Name, version, subnets, node sizes, admin/viewer principals, log retention, chart version, replicas |
| `infra/modules/eks/outputs.tf` | Cluster name, endpoint, CA data, version, security groups, LB controller role ARN |
| `infra/modules/eks/versions.tf` | aws `~> 6.73`, helm `~> 3.3` |
| `infra/envs/dev/main.tf` | `helm` provider (exec auth, private repo config), `module "eks"` with `count = var.enable_eks ? 1 : 0` |
| `infra/envs/dev/variables.tf` | `enable_eks` with validation "needs NAT" |
| `infra/envs/dev/outputs.tf` | Cluster name and the `update-kubeconfig` command |
| `infra/envs/dev/versions.tf`, `.terraform.lock.hcl` | helm provider declared; checksums for Windows and Linux |
| `Makefile` | `up`/`down` switch EKS + NAT; `up` writes kubeconfig; `down` lists clusters, nodes, LBs, NAT, EIPs |
| `.gitignore` | Ignores the Helm provider's private `.helm/` cache |

## 3. How it works

**EKS in one paragraph.** Kubernetes runs containers on a group of machines. It has a *control
plane* (the API server and scheduler that decide what runs where) and *worker nodes* (the machines
that run the containers). With EKS, AWS runs the control plane for you ($0.10/h) and you provide the
nodes. Here that's a *managed node group*: AWS launches EC2 instances from a launch template, joins
them to the cluster, and replaces them when the template changes. That's exactly what happened
during the tag fix: new nodes came up, pods moved over, and the old nodes were drained and
terminated.

**What this cluster is made of:**

| Piece | What it does |
| --- | --- |
| Control plane `surgegate-dev` (1.37) | Kubernetes API, reachable publicly but every request needs AWS IAM authentication |
| Nodes: 2 × t3.medium, private subnets 1a + 1b | Run the pods; no public IPs; outbound through the NAT |
| `vpc-cni` add-on | Gives every pod a real VPC IP address (why the private subnets are /20) |
| `kube-proxy`, `coredns` | Service networking and in-cluster DNS |
| `eks-pod-identity-agent` | Hands out AWS credentials to pods that have a Pod Identity association |
| AWS Load Balancer Controller | Watches Kubernetes Ingress objects and creates/updates AWS ALBs for them (Task 4) |

**Access entries (who may use the cluster).** EKS maps IAM principals to Kubernetes permissions:
- `sheshagiri-admin` and the CI apply role are cluster admins.
- The CI plan role has *AdminView* (read everything). Terraform's helm provider has to read the
  release to plan, which is why the PR's CI plan could say "No changes" with read-only rights.
- These are listed explicitly instead of "whoever created the cluster", so a local apply and a CI
  apply never fight over the admin entry.

**Pod Identity (how a pod gets AWS permissions).** The Load Balancer Controller must call AWS (create
ALBs, target groups, security groups). Instead of giving the nodes those rights, which every pod
would then share, a *Pod Identity association* links one Kubernetes service account
(`kube-system/aws-load-balancer-controller`) to one IAM role. The agent on each node injects
`AWS_CONTAINER_CREDENTIALS_FULL_URI` into that pod only, and the AWS SDK picks up short-lived
credentials from it. It's the newer, simpler replacement for IRSA: no per-cluster OIDC provider and
no annotations.

**Cost choices.** No customer KMS key: EKS already envelope-encrypts secrets with an AWS-owned key,
and a KMS key would cost $1/month plus a 7–30 day deletion wait after every `make down`. Only audit
and authenticator logs, kept 14 days. Two small on-demand nodes (3 max = 6 vCPU, within the
8-vCPU quota).

**The `enable_eks` switch.** `module "eks"` has `count = var.enable_eks ? 1 : 0`. `make down` plans
with `enable_eks=false enable_nat_gateway=false`, so Terraform destroys everything in the module (the
Helm release first, because it depends on the cluster) plus the NAT, and keeps the free VPC. A
validation refuses `enable_eks=true` without the NAT, because the nodes could never pull images or
join the cluster.

**How it fits SurgeGate.** The booking API (FastAPI) and organiser dashboard will run here as pods.
Argo CD (Task 2) deploys them, the LB controller exposes them as `api.<domain>` through an ALB
(Task 4), and later RDS/Redis security groups will allow the node security group (an output of this
module).

## 4. Errors I hit and how I fixed them

| # | Error (exact message) | Cause | Fix |
| --- | --- | --- | --- |
| 1 | `level=WARN msg="repo is corrupt or missing" repo=prometheus-community error="open C:\Users\shesh\AppData\Local\Temp\helm\repository\prometheus-community-index.yaml: The system cannot find the file specified."` (also kyverno, falcosecurity) | Old Helm repos on the laptop with missing index files. | Harmless for `helm search`, but see error 3. |
| 2 | `Warning: Missing version constraint for provider "helm" in required_providers (terraform_required_providers)` | The dev root configured `provider "helm"` without declaring it. | Added `helm = { source = "hashicorp/helm", version = "~> 3.3" }` to `infra/envs/dev/versions.tf`. |
| 3 | `Error: Error locating chart … Unable to locate chart aws-load-balancer-controller: no cached repo found. (try 'helm repo update'): open C:\Users\shesh\AppData\Local\Temp\helm\repository\prometheus-community-index.yaml: The system cannot find the file specified.` | The helm provider reads the user's personal Helm repo list, and a stale entry there breaks chart lookup even though the release gives its repository URL. | Gave the provider its own `repository_config_path` and `repository_cache` under `infra/envs/dev/.helm/` (gitignored). Local and CI now behave the same. |
| 4 | `Error: Invalid value for variable … variable "enable_eks"` | Deliberate test: EKS on with NAT off. | Expected. The validation stops a cluster whose nodes could never join. |
| 5 | `Error: No valid credential sources found` … `login session has expired, please reauthenticate` | The short-term `aws login` session expired overnight, before the apply started. Nothing was created. | You ran `aws login --profile surgegate`; I re-ran the same saved plan. |
| 6 | `kubectl get nodes -o custom-columns=…ZONE:.metadata.labels.topology\\.kubernetes\\.io/zone` printed `<none>` | Wrong escaping of the dots in the label key inside the column spec. | Used `kubectl get nodes -L topology.kubernetes.io/zone -L node.kubernetes.io/instance-type`. |
| 7 | (Found in verification) node EC2 instances tagged only `Component=eks`, with no `Project`/`Env` | Provider `default_tags` don't propagate to instances and volumes launched by an EKS node group's launch template; the module only copies its own `tags` input. | Passed `tags = { Project, Env }` into the eks module. Plan: 2 add (EC2 tags), 18 in-place, 0 destroy. The node group rolled to new nodes, now fully tagged. |
| 8 | `Error: missing or corrupted provider plugins: - registry.terraform.io/hashicorp/helm: the cached package … does not match any of the checksums recorded in the dependency lock file` (CI) | The lock file had only Windows checksums for helm, cloudinit, null, time and tls. My first `providers lock` ran before the dev root declared helm, and I only printed its last output line, so I missed it. CI uses `-lockfile=readonly` on Linux. | `terraform providers lock -platform=windows_amd64 -platform=linux_amd64`, committed, CI green. |

## 5. How I verified it works

- **Apply:** `Apply complete! Resources: 46 added, 0 changed, 0 destroyed.`
- **Nodes:** `ip-10-20-20-8` (ap-south-1a) and `ip-10-20-32-71` (ap-south-1b), both `Ready`,
  `t3.medium`, kubelet `v1.37.1`, no public IP.
- **Pods:** all 9 kube-system pods Running (aws-node × 2, kube-proxy × 2, pod-identity-agent × 2,
  coredns × 2, aws-load-balancer-controller × 1).
- **Add-ons:** vpc-cni `v1.23.3-eksbuild.2`, eks-pod-identity-agent `v1.5.0-eksbuild.3`, kube-proxy
  `v1.37.0-eksbuild.39`, coredns `v1.14.7-eksbuild.35`, all `ACTIVE`.
- **Pod Identity:** association `kube-system / aws-load-balancer-controller`. The controller pod has
  `AWS_CONTAINER_CREDENTIALS_FULL_URI` and `AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE`, and its log has
  **0** error/AccessDenied lines. (It creates its first ALB in Task 4, which is the end-to-end proof.)
- **Access entries:** `sheshagiri-admin`, `surgegate-gha-apply`, `surgegate-gha-plan` (plus
  AWS-managed ones for the node role and the EKS service role).
- **Tags:** cluster `Project/Env/Component`. After the fix, both instances and both 20 GiB encrypted
  gp3 volumes have `Project=surgegate Env=dev Component=eks`. 31 resources tagged `Env=dev` before
  the fix, none missing Project/Component.
- **Drift:** local `terraform plan -detailed-exitcode` → no changes.
- **CI:** PR #7 all green. Comments: `infra/bootstrap` ✅ No changes, `infra/envs/dev` ✅ No changes
  (the CI plan role reached the cluster for the Helm release).
- **`make down`:** runs at the end of today's session (kept up for Tasks 2–5, as you asked). The
  result goes in the Day 2 summary and the Task 5 report.

## 6. Cost impact

| Item | Price (AWS Pricing API, ap-south-1) | Per hour |
| --- | --- | --- |
| EKS control plane | $0.10 / h | $0.100 |
| 2 × t3.medium on-demand | $0.0448 / h each | $0.090 |
| 2 × 20 GiB gp3 | $0.0912 / GB-month | $0.005 |
| NAT gateway + public IPv4 | $0.056 + $0.005 / h | $0.061 |
| **Total while up** | | **≈ $0.256 / h** |

Possible extras: a 3rd node during scale-up or rollouts (+$0.045/h), t3 surplus CPU credits
($0.05/vCPU-h above baseline), NAT data ($0.056/GB), control-plane logs ($0.67/GB ingested).
**Teardown:** `make down` destroys all 46 resources (module + NAT), keeping the free VPC.

## 7. Interview notes

- **Q:** How do pods in your cluster get AWS permissions?
  **A:** EKS Pod Identity. A Pod Identity association maps one Kubernetes service account to one IAM
  role. The pod-identity agent on each node gives only that pod short-lived credentials through a
  local endpoint. The nodes' own role stays minimal, so a compromised pod can't use another pod's
  permissions. It replaces IRSA without needing an OIDC provider per cluster.

- **Q:** How do you keep EKS affordable on a $50 budget?
  **A:** Everything hourly is behind Terraform switches. `make up` creates the cluster, nodes and
  NAT for a work session (about $0.26/h), and `make down` destroys them while keeping the free VPC
  and state. I also skipped the customer KMS key (EKS encrypts secrets by default), kept logs to
  audit and authenticator for 14 days, and used two small on-demand nodes.

- **Q:** How does your CI plan Kubernetes resources with a read-only role?
  **A:** The CI plan role has an EKS access entry with the AdminView access policy, which lets it
  read every object, including the Helm release secret. The helm provider authenticates with
  `aws eks get-token` using the OIDC credentials. The apply role has cluster-admin, and neither has
  long-term keys.

## 8. Next task

Day 2 · Task 2 — Install Argo CD on the cluster; point it at `deploy/argocd`.
