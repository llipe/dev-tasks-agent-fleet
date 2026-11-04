#!/usr/bin/env bash
# 20261103-code-review-params-v14 — reverse order. Usage: rollback.sh --from N
# First remove webhook rules that set context_folders/context_selection: they would fail validation.
set -euo pipefail
FROM="${2:-3}"
if [ "$FROM" -ge 3 ]; then
  # Restore the v1.0 params_schema/default_params by re-running the original upsert
  # (runtime_arn and is_enabled are not in its update list, so they stay as live).
  supabase db query --linked -f supabase/migrations/20261022120000_seed_code_review_agent.sql
  supabase migration repair --linked --status reverted 20261103120000
fi
