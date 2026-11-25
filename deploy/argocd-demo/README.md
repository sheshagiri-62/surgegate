# Argo CD apps for the `demo` environment

Argo CD in the demo cluster syncs the `*.yaml` Application manifests in this folder (the root
app is installed by `infra/envs/demo`). They are written at the Day 10 apply, because the demo
values (CloudFront domain for the webhook and checkout URLs, target-group names, secret IDs,
Cognito client IDs) only exist once the demo environment has been created.
