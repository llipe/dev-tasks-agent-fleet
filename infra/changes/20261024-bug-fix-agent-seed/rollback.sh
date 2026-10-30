#!/usr/bin/env bash
# Regenerated after each applied step; reverts in reverse order. Usage: rollback.sh [--from N]
set -euo pipefail
FROM=99; [ "${1:-}" = "--from" ] && FROM="${2:?step number}"

# Step 1 — remove the bug-fix row, then its migration record (so a later push re-applies it).
# Fails once any runs row references the agent (ON DELETE RESTRICT); export webhook_rules/schedules first (cascade).
if [ "$FROM" -ge 1 ]; then
  supabase db query --linked "delete from agents where slug = 'bug-fix';"
  supabase db query --linked "delete from supabase_migrations.schema_migrations where version = '20261024130000';"
fi
