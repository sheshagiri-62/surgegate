# Week 2 · Day 9 Task 1 — Build the `demo` environment

- **Date:** 2026-11-25
- **Phase / milestone:** Phase 5 → M5
- **Status:** Partly done by decision: code, validate and plan are done; **the apply is on Day 10**
  (your choice: demo runs only for the load tests, then comes down)
- **Commit / PR:** [#61](https://github.com/sheshagiri-62/surgegate/pull/61)

## 1. What the task was

Plan, Day 9 Task 1: *"Build the `demo` environment: two NAT gateways, Multi-AZ RDS, Redis replica,
Karpenter, 2+ nodes."* The 10,000- and 50,000-user tests (Day 10) and the final demo need a
production-shaped environment: no single points of failure, and room to add nodes fast.

## 2. What I did, step by step

1. **`infra/envs/demo`**, the same modules as dev with demo settings:

   | | dev | demo |
   | --- | --- | --- |
   | VPC | 10.20.0.0/16 | 10.30.0.0/16 (no overlap) |
   | NAT gateways | 1 | **2** (one per AZ) |
   | EKS nodes | 1–3 × t3.medium | **2–3 × t3.medium + Karpenter (up to 6 vCPU more)** |
   | Load Balancer Controller | 1 replica | 2 |
   | RDS | db.t4g.micro single-AZ | db.t4g.micro **Multi-AZ** |
   | Redis | 1 node | **primary + replica** |
   | Kinesis | 1 provisioned shard | **ON_DEMAND** (the Day 8 50k note) |
   | Hourly switches | on (`make up`) | **off by default** |

   State key `envs/demo/terraform.tfstate`, same lock file as dev (same provider versions).
   Argo CD in demo will read `deploy/argocd-demo/` (a README for now; the Applications and
   demo values are written at the Day 10 apply, once the demo CloudFront domain exists).
2. **Karpenter** in the EKS module, behind `enable_karpenter` (dev: off):
   - the community `karpenter` submodule (same pinned version as the cluster module): controller
     role via Pod Identity, node role + EKS access entry, an SQS interruption queue fed by 5
     EventBridge rules (Spot interruption, rebalance, state change, health, capacity
     reservation);
   - chart `1.15.3` from Karpenter's public OCI registry, running on the managed nodes
     (`karpenter.sh/controller=true`);
   - a small local chart with the `EC2NodeClass` (AL2023, IMDSv2 only, hop limit 1, encrypted
     gp3) and the `NodePool` (t3/t3a medium/large, Spot preferred, CPU limit 6, consolidation
     after 2 minutes).
3. **Events module:** a `stream_mode` variable (`PROVISIONED` or `ON_DEMAND`).
4. **Edge module fix:** `queue_api_enabled`, a plain boolean (see error 3).
5. Plans: demo with hourly parts off **223 to add**; demo all on **334 to add**; dev **No changes**.
   CI planned all four roots green.

### Commands I ran

```bash
cp infra/envs/dev/{booking_api,mock_pay,order_worker,outputs,variables,versions,main}.tf infra/envs/demo/
cp infra/envs/dev/.terraform.lock.hcl infra/envs/demo/      # same provider versions as dev
cp infra/envs/dev/alerts.auto.tfvars infra/envs/demo/       # uncommitted (*.tfvars ignored)
terraform fmt -recursive infra
terraform -chdir=infra/envs/demo init -input=false
terraform -chdir=infra/envs/demo validate
terraform -chdir=infra/envs/demo plan -input=false -out=demo-off.tfplan            # 223 to add
terraform -chdir=infra/envs/demo plan -input=false -var=enable_nat_gateway=true \
  -var=enable_eks=true -var=enable_data=true -var=enable_kinesis=true              # 334 to add
terraform -chdir=infra/envs/dev init -input=false                                  # new submodule
terraform -chdir=infra/envs/dev plan <up vars>                                     # No changes
rm infra/envs/demo/demo-off.tfplan                                                 # not applied
```

### Files created or changed

| File | What it does |
| --- | --- |
| `infra/envs/demo/*.tf` | The demo root module (from dev, demo settings, hourly switches off) |
| `infra/modules/eks/karpenter.tf`, `charts/karpenter-nodes/**` | Karpenter + NodePool/EC2NodeClass |
| `infra/modules/eks/main.tf`, `variables.tf`, `outputs.tf` | Karpenter switch, SG discovery tag, controller label (demo only) |
| `infra/modules/events/main.tf`, `variables.tf` | `stream_mode` |
| `infra/modules/edge/main.tf`, `variables.tf`; `infra/envs/dev/main.tf` | `queue_api_enabled` |
| `deploy/argocd-demo/README.md` | Where the demo Argo CD apps go (Day 10) |
| `.pre-commit-config.yaml` | `check-yaml` also skips Helm templates under `infra/modules/*/charts` |

## 3. How it works

**High availability in one region:** a region has several data centres ("availability zones").
Demo spreads everything over two:
- each AZ has its own NAT gateway, so losing one AZ doesn't cut the other off from the internet;
- RDS Multi-AZ keeps a synchronous standby copy in the other AZ and fails over by itself in about
  a minute;
- Redis has a replica in the other AZ;
- there's one node per AZ at minimum.

**Karpenter** watches for pods that can't be scheduled, because there isn't enough CPU or memory.
It then launches the cheapest instance that fits them, straight through the EC2 API, in about a
minute, and removes nodes again once they're empty or under-used. For SurgeGate that means the
pre-scaling job (Day 10) can just scale the booking API's pods up 15 minutes before a sale, and
Karpenter brings the nodes. The managed node group stays as the always-on baseline. It also runs
Karpenter itself, so Karpenter never manages the node it runs on.

**Why all hourly switches default to off:** a plain `terraform apply` in demo can then only
create the pay-per-use parts. The expensive parts need explicit `-var=enable_…=true` for a test
window.

## 4. Errors I hit and how I fixed them

| # | Error (exact message) | Cause | Fix |
| --- | --- | --- | --- |
| 1 | `Error while installing hashicorp/aws v6.74.0: releases.hashicorp.com: read` (and `could not query provider` for 6 more) | A network read error during `init`; it also picked a newer AWS provider than dev | Copied dev's `.terraform.lock.hcl` (pins 6.73.0 etc.), re-ran init: OK |
| 2 | `Plan: 220 to add` then `Error: Invalid count argument … modules\edge\main.tf line 276 … count = var.cloudfront_enabled && var.queue_api_domain != "" ? 1 : 0` | In a brand-new environment the queue API doesn't exist yet, so its domain is unknown at plan time and can't decide a `count` (dev never hit it because its API already existed) | New boolean `queue_api_enabled` for the count/for_each; the domain is only used as a value |
| 3 | `Error: Module not installed` (dev plan) | The EKS module now references the Karpenter submodule | `terraform init` in dev (no upgrade); then dev plan: No changes |
| 4 | Pre-commit `check yaml … Failed` | Helm template `{{ }}` isn't plain YAML; the hook only skipped `deploy/helm/*/templates` | Extended the exclude to `infra/modules/*/charts/*/templates` |
| 5 | `pull request create failed: GraphQL: No commits between main and infra/demo-env` | Follow-on of 4: the commit hadn't been made | Committed after the fix, then opened #61 |

## 5. How I verified it works

- `terraform validate`: valid. Plans: demo off **223 to add, 0 to change, 0 to destroy**; demo on
  **334 to add**; dev **No changes** (the module changes are inert there).
- The demo-on plan contains: 2 × `aws_nat_gateway`; `multi_az = true`; Redis
  `num_cache_clusters = 2`; Kinesis `stream_mode = "ON_DEMAND"`; node group `min_size = 2`; and the
  whole Karpenter set (controller and node roles, Pod Identity association, access entry, SQS
  queue + policy, 5 EventBridge rules + targets, both Helm releases).
- CI (#61): `plan (infra/envs/demo)`, `plan (infra/envs/dev)`, bootstrap, shared and fmt all
  green.

**Still to do at the Day 10 apply:**
- the Argo CD Applications + demo Helm values (demo CloudFront domain, target groups, secret IDs,
  client IDs);
- add `demo` to `site_deploy_envs` in bootstrap;
- the k6 buyer accounts;
- check the Karpenter chart against Kubernetes 1.37 at startup (it logs and refuses an
  unsupported version).

## 6. Cost impact

**Nothing created yet, so $0.** When applied (Day 10), these bill by the hour:
- EKS control plane;
- 2 NAT gateways (+ their public IPv4 addresses);
- 2 t3.medium baseline nodes, plus Karpenter nodes during the tests (Spot preferred);
- Multi-AZ db.t4g.micro;
- 2 × cache.t4g.micro;
- the internal ALB;
- the Kinesis on-demand stream.

That's about **$0.45/h** before burst nodes. Teardown: apply with the `enable_*` switches back to
`false` (keeps the free parts), or `terraform destroy` on demo, only with your OK.

## 7. Interview notes

- **Q:** Why both a managed node group and Karpenter?
  **A:** The node group is a small, always-on baseline that also runs cluster add-ons and
  Karpenter itself, so Karpenter never manages the node it runs on. Karpenter handles bursts: it
  picks the cheapest instance that fits the pending pods in about a minute and consolidates nodes
  away afterwards. Cluster Autoscaler can only grow fixed-shape node groups.
- **Q:** What does Multi-AZ RDS give you, and what doesn't it?
  **A:** A synchronous standby in another AZ with automatic failover (DNS flips in about 60–120 s)
  for AZ or instance failure. It's not a read replica: you can't read from the standby, and it
  doesn't help with read scaling. That's what Redis (seat-map cache) and the CloudFront-cached
  counter do here.
- **Q:** How do you stop a load-test environment from running up a bill?
  **A:** Every hourly resource sits behind a boolean that defaults to off, so an accidental
  apply creates only pay-per-use parts. The test window is an explicit apply with the switches
  on, and it ends with an apply that switches them off. There are budget alerts at $15/$30/$45.

## 8. Next task

Day 9 Task 2: WAF on CloudFront (rate rules, managed common + IP reputation, Bot Control scoped to
`/queue/*`, challenge before join, `/webhooks/*` excluded) + the queue origin's secret header,
because WAF can't attach to an API Gateway HTTP API. The web ACL has a monthly fee charged pro
rata, so I'll show it to you before the apply.
