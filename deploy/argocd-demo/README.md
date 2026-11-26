# Argo CD apps for the `demo` environment

Argo CD in the demo cluster syncs the `*.yaml` Application manifests in this folder (the root
app is installed by `infra/envs/demo`, `gitops_path = "deploy/argocd-demo"`).

They are the dev apps plus one more values file per chart, `values-demo.yaml`, which is
**generated** from `terraform output` by `infra/scripts/demo_values.py` (Day 10 Task 4): the
demo IDs (Cognito pool + clients, CloudFront domain, Redis endpoint, ALB dimensions, the
load-test issuer) exist only after the first demo apply. Until then the committed files hold
placeholders and the demo apps can't start, which is fine: demo has no cluster outside a
test window. Image tags come from each chart's `values.yaml`, bumped by CI, so demo runs the
same images as dev.

Window order: apply -> `terraform output -json > out.json` -> `python
infra/scripts/demo_values.py out.json` -> PR -> merge -> Argo syncs (1-minute poll). Steps:
`docs/runbooks/demo-loadtest.md`.
