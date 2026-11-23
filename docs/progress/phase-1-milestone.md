# Phase 1 — Foundations → Milestone M1

- **Checked on:** 2026-11-23 (CloudFront approved by AWS Support, case 179519256900023; it had
  been blocked by account verification since Day 2)
- **"Done when"** (plan): *a merge to `main` deploys hello-world to EKS through Argo CD, it answers
  at `https://api.<domain>/healthz`, and `make down` leaves nothing billable.*
- **Result: met, with the CloudFront default domain** instead of `api.<domain>`. Route 53 domain
  registration is still under review (ADR 003: default domain until then).

## Evidence

| Condition | How it was checked | Result |
| --- | --- | --- |
| A merge to `main` deploys to EKS through Argo CD | Every merge since Day 2 (latest: #33 → image `1f916f5bbded`, #34 → `417baabd44f0`) | `build-deploy` builds, scans and pushes, bumps the Helm tag; Argo CD `booking-api` Synced/Healthy; migration Job completed |
| It answers on public HTTPS `/healthz` | `curl https://d1t9vww2xtyvsz.cloudfront.net/healthz` | **`HTTP/1.1 200 OK`**, `{"status":"ok"}`, `server: uvicorn`, `Via: … (CloudFront)` |
| HTTP is upgraded | `curl http://d1t9vww2xtyvsz.cloudfront.net/healthz` | `301 → https://…/healthz` |
| The ALB can't be used directly | `curl http://surgegate-dev-api-1855927574.ap-south-1.elb.amazonaws.com/healthz` | **no connection** (timeout, exit 28): the ALB security group admits only the CloudFront origin-facing prefix list |
| Requests without the secret header get 403 | ALB listener rules (`describe-rules`), **and live**: a temporary Terraform rule (`debug_ingress_cidr`) let one /32 reach the ALB directly, then it was removed | priority 10: `forward` if `X-Origin-Verify` matches; default `fixed-response 403`. **Live: no header → `HTTP/1.1 403 Forbidden`; wrong header value → `403`**. Rule removed (1 destroyed) → direct access back to no connection |
| `make down` leaves nothing billable | `make down` + `billing-check` (Day 6), and direct AWS CLI checks after the `make` environment fix (#36) | EKS, EC2, LB, NAT, EIP, public ENIs, RDS, ElastiCache all empty |

## How to demo it

1. `make up` (from PowerShell, or `cmd //c "make up"` in Git Bash).
2. Merge a small change to `services/booking-api`, then watch `build-deploy` and Argo CD.
3. `curl -i https://d1t9vww2xtyvsz.cloudfront.net/healthz` → 200 via CloudFront.
4. `curl -m 10 http://<alb-dns>/healthz` → times out (not reachable directly).
5. `make down` and `make billing-check` → nothing billable.

## Screenshots to take

1. `curl -i` of the CloudFront `/healthz` (200, `Via: … CloudFront`).
2. The timed-out direct ALB request.
3. EC2 → Load balancers → listener rules (forward on header, default 403).
4. Argo CD `booking-api` Synced/Healthy.
5. `make billing-check` after `make down`.

## Open

- **The CloudFront → ALB hop is plain HTTP** (no domain, so no certificate on the ALB). Fix it
  before payments (Day 7): proposal pending your choice (VPC origins + internal ALB, or wait for
  the domain).
- `api.<domain>` once the Route 53 registration is approved.
