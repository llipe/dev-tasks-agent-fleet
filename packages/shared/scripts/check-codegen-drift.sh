#!/usr/bin/env bash
# CI drift check: fails if codegen produces a diff against committed output.
set -euo pipefail

echo "Running codegen..."
pnpm --filter @fleet/shared run codegen

echo "Checking for drift..."
if git diff --exit-code packages/shared/generated/; then
  echo "No drift detected — generated files are up to date."
else
  echo ""
  echo "ERROR: Generated files are out of date!"
  echo "Run 'pnpm --filter shared run codegen' and commit the result."
  exit 1
fi
