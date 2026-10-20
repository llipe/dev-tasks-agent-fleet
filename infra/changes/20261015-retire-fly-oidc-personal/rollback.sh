#!/usr/bin/env bash
# Rollback for ChangeId 20261015-retire-fly-oidc-personal.
set -euo pipefail
# --- revert step 1 ---
aws iam create-open-id-connect-provider --url https://oidc.fly.io/personal \
  --client-id-list sts.amazonaws.com --thumbprint-list 3c34e356c7fc17f5acf04824bc587c6c623951a2
