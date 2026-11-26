# Runbook: demo load-test window (10k, then 50k fans)

Day 10 Task 4. One window, about 3 hours, everything torn down after. **Start only on
"go demo".** Every command runs from the repo root with `AWS_PROFILE=surgegate`.

## 0. Before the window

- vCPU quotas: On-Demand 32 and Spot 32 (raised 25 Nov; check `L-1216C47A` / `L-34B43A08`).
- `infra/envs/shared` applied once, so the EC2 Spot service-linked role exists.
- `infra/envs/demo/alerts.auto.tfvars` holds `alert_email` and `ses_sender` (uncommitted).

## 1. Open the window

```bash
make down                                   # dev: frees its vCPU and its hourly cost
terraform -chdir=infra/envs/demo plan -out=win.tfplan \
  -var=enable_nat_gateway=true -var=enable_eks=true -var=enable_data=true \
  -var=enable_kinesis=true -var=enable_waf=true -var=enable_loadtest=true
terraform -chdir=infra/envs/demo apply win.tfplan       # ~25 min (EKS, Multi-AZ RDS)
terraform -chdir=infra/envs/demo output -json > tests/load/.demo-out.json
python infra/scripts/demo_values.py tests/load/.demo-out.json   # values-demo.yaml x 3
# branch + PR + merge -> Argo CD syncs booking-api, mock-pay, organiser (1-minute poll)
aws eks update-kubeconfig --name surgegate-demo --region ap-south-1
python tests/load/demo_loadtest.py keygen   # issuer key: private -> Secrets Manager, public -> SSM
```

The buyer site goes to the demo bucket through `build-deploy-buyer` (`site_deploy_envs`).
The load test doesn't need it: k6 calls the APIs.

## 2. Each run (10k first, then 50k)

```bash
python tests/load/demo_loadtest.py headroom --fans 50000   # limits vs planned peak: STOP if short
python tests/load/demo_loadtest.py setup --fans 10000      # organiser, event, 2,000 seats, queue
python tests/load/demo_loadtest.py start                   # k6 Job: 5,000 VUs per shard, Spot pool
python tests/load/demo_loadtest.py watch                   # pauses the queue once all seats are sold
python tests/load/demo_loadtest.py collect                 # real VU count + metrics -> docs/progress/day-10/
python tests/load/demo_loadtest.py check                   # SQL oversold check: must all PASS
python tests/load/demo_loadtest.py cleanup
```

- Real VU count: `collect` adds up each shard's `vus_max` and says "full: 1 VU = 1 fan" or
  "FALLBACK". Use `setup --fallback` only for the smaller-50k profile, so it is labelled.
- Re-measure k6 memory in the 10k run (`kubectl top pod -n loadtest`), then pass
  `start --mb-per-vu <measured>` for the 50k run.
- Ticket emails go only to `success@simulator.amazonses.com`, 1 per second, so 2,000 paid
  orders take about 35 minutes. Emails can still be sending while the next run starts.

## 3. Close the window (same day)

```bash
terraform -chdir=infra/envs/demo plan -out=off.tfplan -var=enable_loadtest=false \
  -var=enable_nat_gateway=true -var=enable_eks=true -var=enable_data=true -var=enable_kinesis=true
terraform -chdir=infra/envs/demo apply off.tfplan    # issuer, key, k6 role, allow rule, Spot pool: GONE
python infra/scripts/demo_values.py tests/load/.demo-out.json   # (fresh outputs) loadtestIssuer empty
# PR + merge: the demo booking API trusts Cognito only again
terraform -chdir=infra/envs/demo plan -out=down.tfplan          # all enable_* false (defaults)
terraform -chdir=infra/envs/demo apply down.tfplan   # hourly parts off; RDS final snapshot kept
```

With the database off, the ticket consumer is off too. Unsent ticket emails wait in SQS for 4
days and then expire: no DLQ flood. Persistent leftovers (no hourly cost) are listed in the
Day 10 Task 4 report; `terraform destroy` of demo needs a separate OK.
