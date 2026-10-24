#!/usr/bin/env bash
# Append-only record of commands run for 20261024-bug-fix-agent-seed. No secrets.
set -euo pipefail

# Discovery — 2026-10-24T18:11:40Z (read-only)
supabase db push --dry-run   # -> only 20261024130000_seed_bug_fix_agent.sql
supabase db query --linked "select slug, name, version, is_enabled, requires_repository, runtime_arn, max_runtime_seconds, grace_seconds, start_timeout_seconds from agents order by slug;" > backup/agents.before.json
supabase db query --linked "select version, name from supabase_migrations.schema_migrations order by version desc limit 3;" > backup/schema_migrations.before.json

# Step 1 attempt — 2026-10-24T18:14:41Z — REFUSED by the CLI before any change (DbPushMissingLocalError):
# the live project had recorded 20261022120000_seed_code_review_agent.sql (from main, the code-review line,
# applied by another session between 18:11 and 18:14), which this branch didn't have.
supabase db push --linked --yes
# Remediation (repo only): copy that migration file, byte-identical, from origin/main into the story branch.
git checkout origin/main -- supabase/migrations/20261022120000_seed_code_review_agent.sql
supabase db push --dry-run --linked   # 18:17:28Z -> only 20261024130000_seed_bug_fix_agent.sql
# Step 1 — apply — 2026-10-24T18:17:38Z..18:17:44Z
supabase db push --linked --yes       # Applying migration 20261024130000_seed_bug_fix_agent.sql... Finished
supabase db query --linked "select slug, requires_repository, params_schema->'required' as required, runtime_arn, max_runtime_seconds, grace_seconds, start_timeout_seconds, is_enabled ... from agents where slug = 'bug-fix';" > backup/agents.after-step1.json
