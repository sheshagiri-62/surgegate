# deploy/argocd — Argo CD Applications (app of apps)

Argo CD is installed by Terraform (`infra/modules/eks`, `helm_release.argocd`). Terraform also
creates one **root Application** that watches this folder on `main`:

```text
root (Application, argocd namespace)
 └─ every *.yaml in deploy/argocd/  →  one Argo CD Application per service
       └─ each points at its Helm chart in deploy/helm/<service>
```

Rules:

- One `*.yaml` file per service, each containing one `argoproj.io/v1alpha1` `Application` in the
  `argocd` namespace. Only `*.yaml` files are read (this README is ignored).
- Automated sync with prune and self-heal: merging to `main` deploys, deleting a file removes the
  app, and manual `kubectl` changes are reverted.
- Image tags are bumped in `deploy/helm/<service>/values.yaml` by `build-deploy.yml`, never by hand.

Open the UI (dev, no ingress yet):

```bash
kubectl -n argocd port-forward svc/argocd-server 8080:80
# user: admin, password:
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d
```
