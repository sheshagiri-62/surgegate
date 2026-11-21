#!/usr/bin/env bash
# Kubernetes exec credential plugin for the Terraform helm provider: `aws eks get-token`, retried.
#
# Why: locally the `aws login` credentials last 15 minutes. A long `make up` crosses a refresh,
# and while the Terraform AWS provider and the AWS CLI refresh the same login session, a
# get-token call can fail ("getting credentials: exec: executable aws failed with exit code 1").
# A few seconds later it works. Retrying covers that window; the real CLI error is kept in a log
# file (Terraform hides the plugin's stderr) so a different cause would be visible.
#
# Usage: eks-token.sh <cluster-name> <region>    (prints the ExecCredential JSON on stdout only)
set -u
cluster="$1"
region="$2"
log="${TMPDIR:-/tmp}/surgegate-eks-token.log"
for attempt in 1 2 3 4; do
  if out=$(aws eks get-token --cluster-name "$cluster" --region "$region" --output json 2>>"$log"); then
    printf '%s\n' "$out"
    exit 0
  fi
  echo "$(date -u +%FT%TZ) get-token attempt $attempt failed (stderr above)" >>"$log"
  [ "$attempt" -lt 4 ] && sleep $((2 ** attempt))
done
echo "aws eks get-token failed 4 times; see $log" >&2
tail -n 20 "$log" >&2
exit 1
