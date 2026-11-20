# Week 1 · Day 2 · Task 04 — `edge` module (first part): CloudFront default domain in front of the ALB

- **Date:** 2026-11-20
- **Phase / milestone:** Phase 1 (Foundations) → M1
- **Status:** **Partly done, paused.** The ALB side is built and applied. The CloudFront distribution
  is blocked until AWS verifies the account (support case submitted by you, combined with Route 53
  domains and Kinesis/MSK). It's behind `enable_cloudfront = false` until then.
- **Commit / PR:** [PR #12](https://github.com/sheshagiri-62/surgegate/pull/12) · [ADR 003](../../adr/003-cloudfront-default-domain-in-front-of-alb.md)

## 1. What the task was

Plan text: *"`edge` module (first part): Route 53 zone, ACM certificate, ALB ingress for
`api.<domain>`."* There's no domain (registration failed), so you decided: use CloudFront's default
`*.cloudfront.net` domain in front of the ALB, with the ALB security group limited to CloudFront's
origin-facing prefix list plus a secret origin header from Secrets Manager. Route 53 and ACM stay
behind `var.domain_name`, and the decision is recorded in ADR 003. Later you asked for the
distribution to be **persistent**, with only the ALB side following `enable_eks`.

## 2. What I did, step by step

1. Checked the Load Balancer Controller supports `TargetGroupBinding.spec.targetGroupName`, found
   the CloudFront origin-facing prefix list (`pl-9aa247f3`) and the security-group rule quota (60;
   the prefix list counts as 55).
2. Chose a **Terraform-owned ALB** (not an Ingress) so the secret header value never goes into Git
   and `make down` always removes the ALB. The chart got a TargetGroupBinding that finds the target
   group by name.
3. Wrote `infra/modules/edge` (ALB, SG, listener, header rule, target group, CloudFront, optional
   Route 53 and ACM), the persistent secret in `infra/envs/dev`, and a bootstrap change so the plan
   role may read `surgegate/*/edge/*` secrets. Wrote ADR 003. Priced everything and showed the plan.
4. Per your change: made CloudFront persistent, put the ALB side behind `origin_enabled`, and added
   a CloudFront Function that answers **503** at the edge while dev is down (placeholder origin
   `example.com`, never contacted). Re-planned (up: 13 add) and dry-ran down.
5. Applied bootstrap (1 add) and dev. Everything was created **except the distribution**:
   `AccessDenied: Your account must be verified before you can add new CloudFront resources.`
   Stopped, drafted the support case, and added the ADR 003 follow-ups and the Day 10 tasks you
   asked for.
6. Added `enable_cloudfront` (default `false`) so `make up` / `make down` work until verification.
   Plan: no changes.

### Commands I ran

```bash
kubectl explain targetgroupbinding.spec
aws ec2 describe-managed-prefix-lists --filters Name=prefix-list-name,Values=com.amazonaws.global.cloudfront.origin-facing
aws cloudfront list-cache-policies --type managed ; aws cloudfront list-origin-request-policies --type managed
aws service-quotas get-service-quota --service-code vpc --quota-code L-0EA8095F
gh api repos/hashicorp/terraform-provider-random/releases/latest --jq .tag_name
git switch -c infra/edge origin/main
helm lint deploy/helm/booking-api
terraform fmt -recursive ; terraform init ; terraform providers lock -platform=windows_amd64 -platform=linux_amd64
terraform validate ; tflint --config=../../../.tflint.hcl --call-module-type=local
terraform plan -lock-timeout=3m '-out=edge.tfplan'                    # 12 add (first design)
terraform plan -lock-timeout=3m '-out=plan-secrets.tfplan'            # bootstrap: 1 add
aws pricing get-products --service-code AWSELB ... / AWSSecretsManager / AmazonCloudFront
terraform plan -lock-timeout=3m '-out=edge.tfplan'                    # 13 add (persistent CloudFront)
terraform plan -var=enable_eks=false -var=enable_nat_gateway=false    # down dry run
terraform apply plan-secrets.tfplan                                   # bootstrap: 1 added
terraform apply edge.tfplan                                           # ALB side created; CloudFront AccessDenied
terraform state list ; aws cloudfront list-distributions ; aws cloudfront list-functions
terraform plan -detailed-exitcode                                     # after enable_cloudfront=false: no changes
```

### Files created or changed

| File | What it does |
| --- | --- |
| `infra/modules/edge/*` | ALB + SG (CloudFront prefix list only) + listener (default 403) + secret-header rule + target group; CloudFront (switch), 503 function; Route 53 + ACM behind `domain_name` |
| `infra/envs/dev/*` | Secret (`random_password` → Secrets Manager), `module "edge"`, `enable_cloudfront`, `domain_name`, us-east-1 provider alias, `random` provider |
| `infra/bootstrap/iam.tf` | Plan role: `GetSecretValue` on `surgegate/*/edge/*` |
| `deploy/helm/booking-api/templates/targetgroupbinding.yaml`, `values.yaml` | Registers pod IPs in `surgegate-dev-booking-api` |
| `docs/adr/003-…md` | Decision, trade-offs, follow-ups |
| `docs/implementation-plan.md`, `CHECKLIST.md` | Day 10: base image upgrade (3 HIGH) + gate on HIGH |

## 3. How it works

```text
viewer ──HTTPS──▶ CloudFront (*.cloudfront.net, persistent)      ← blocked until account verification
                    │ adds X-Origin-Verify: <secret from Secrets Manager>
                    ▼ HTTP (no domain → no cert on ALB; ADR 003 follow-up before Day 7)
ALB SG: port 80 only from CloudFront origin-facing prefix list
ALB listener: default 403 · rule "header matches secret" → target group surgegate-dev-booking-api
                    ▼
TargetGroupBinding (Helm chart, by name) registers booking-api pod IPs ──▶ pods :8000
```

- **Two locks on the ALB.** The security group drops anything not coming from CloudFront's IP
  ranges. Because every CloudFront customer shares those ranges, the listener also requires a
  secret header only *our* distribution sends. Without it, the request gets 403.
- **Why Terraform owns the ALB.** An Ingress would put the header condition, and so the secret,
  into a Git annotation, and the controller-created ALB would outlive `make down` unless every
  Ingress were deleted first. With Terraform owning it, `make down` destroys the ALB in the same
  apply as the cluster, and pods join through a TargetGroupBinding that only knows the target
  group's name.
- **Persistent CloudFront, switchable origin.** CloudFront has no hourly price, so it stays and its
  URL is stable. While dev is down there's no ALB, so the origin is a reserved placeholder and a
  CloudFront Function answers 503 JSON before any origin request is made.

## 4. Errors I hit and how I fixed them

| # | Error (exact message) | Cause | Fix |
| --- | --- | --- | --- |
| 1 | Pricing lookup: `json.decoder.JSONDecodeError: Expecting value: line 2 column 1 (char 1)` | The filter value `Load Balancer-Application` contained a space, which split the shell argument, so the CLI printed an error instead of JSON. | Filtered by `usagetype` only: ALB $0.0239/h. |
| 2 | `Error: creating CloudFront Distribution: operation error CloudFront: CreateDistributionWithTags, https response error StatusCode: 403, RequestID: 78e55e8f-2521-4ae0-adfa-4d3a775c1ae5, AccessDenied: Your account must be verified before you can add new CloudFront resources. To verify your account, please contact AWS Support … and include this error message.` | Account-level restriction on new or recently upgraded accounts. | **Not worked around** (rule). Stopped, drafted the support case; you submitted a combined case. Added `enable_cloudfront = false` so the rest keeps working. |
| 3 | `terraform state list -lock-timeout=3m` printed nothing | `state list` doesn't accept `-lock-timeout`; the error went to stderr, which I had hidden. | Re-ran without the flag. |

## 5. How I verified it works

- **Bootstrap:** `aws_iam_role_policy.plan_read_edge_secrets` created.
- **State after the failed apply:** the secret, version, `random_password`, CloudFront function, ALB,
  listener, rule, target group, ALB SG and its 3 rules are all tracked, so nothing is orphaned. No
  distribution exists (`list-distributions` → `None`).
- **With `enable_cloudfront = false`:** `terraform plan -detailed-exitcode` → no changes.
- **Not verifiable until CloudFront works:** `https://<cf>/healthz` 200 and the "no header → 403"
  check through CloudFront. The ALB side (targets healthy, direct access refused) is verified in
  Task 5's `make up` run, after the TargetGroupBinding is on `main`.

## 6. Cost impact

- **ALB:** $0.0239/h + LCU $0.008/LCU-h (≈ 0 idle) + 2 public IPv4 × $0.005/h ≈ **$0.034/h** while up;
  removed by `make down`.
- **Secrets Manager:** $0.40/month (persistent). CloudFront Function: free tier; it only runs while
  attached and invoked.
- **CloudFront distribution:** none yet. When created: no hourly charge, and requests and data are
  within the always-free tier at our volumes.

## 7. Interview notes

- **Q:** How do you stop people from bypassing CloudFront and hitting your ALB directly?
  **A:** Two layers. The ALB security group only allows CloudFront's origin-facing prefix list, and
  the listener's default action is 403, forwarding only when a secret header is present. Our
  distribution adds that header from a value kept in Secrets Manager. The prefix list alone isn't
  enough, because every CloudFront customer shares it.

- **Q:** Why didn't you use a Kubernetes Ingress for the ALB?
  **A:** The header check would have put the secret in a Git-tracked annotation, and
  controller-created ALBs can survive cluster teardown and keep billing. Terraform owns the ALB, and
  a TargetGroupBinding attaches pods by target-group name, so Git stays secret-free and `make down`
  removes the ALB.

- **Q:** What would you change before handling payments?
  **A:** Encrypt the CloudFront → ALB hop: an ACM certificate on an HTTPS listener once there's a
  domain, or CloudFront VPC origins with an internal ALB so nothing is public. It's an ADR 003
  follow-up due before Day 7.

## 8. Next task

Day 2 · Task 5 — `make up` / `make down` working for dev (end to end). Task 4 resumes once AWS
verifies the account: set `enable_cloudfront = true`, plan, apply, and run the CloudFront checks.
