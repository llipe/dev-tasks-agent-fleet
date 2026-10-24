#!/usr/bin/env bash
# commands.sh: 20261024-code-review-runtime (S-214, #416). Append-only.
# Each block is the exact forward command of an applied step. Secrets are
# referenced by name or ARN only; no value is ever written here.
# AWS calls ran through the AWS MCP server (boto3); each block gives the
# equivalent AWS CLI command.
set -euo pipefail
