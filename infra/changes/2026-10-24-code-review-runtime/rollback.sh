#!/usr/bin/env bash
# Rollback for ChangeId 2026-10-24-code-review-runtime. Reverse order; supports --from N.
# Skeleton: fill each block with the exact command when its step is applied.
# Fastest containment, in order (spec §15): disable the /review webhook rule in
# /webhooks, then disable the agent row (step 6 revert), then delete or redeploy
# the runtime (step 1 revert).
set -euo pipefail
FROM="${2:-8}"
echo "rollback skeleton for 2026-10-24-code-review-runtime (from step ${FROM}); no step has been applied" >&2
exit 1
