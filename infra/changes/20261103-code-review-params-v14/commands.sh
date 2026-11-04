#!/usr/bin/env bash
# 20261103-code-review-params-v14 — append-only. No secret values.
set -euo pipefail
D=infra/changes/20261103-code-review-params-v14/backup
supabase db query --linked "select slug, is_enabled, runtime_arn, version, default_params, params_schema->'properties' ? 'context_folders' as has_context_folders from agents where slug = 'code-review';" -o json > $D/agents-code-review.before.json
supabase db query --linked "select version, name from supabase_migrations.schema_migrations order by version desc limit 5;" -o json > $D/schema_migrations.before.json
supabase db push --dry-run --linked      # 2026-11-03 -> only 20261103120000_seed_code_review_agent.sql
supabase db push --linked --yes          # 2026-11-03T20:54Z Applying migration 20261103120000_seed_code_review_agent.sql... Finished
supabase db query --linked "select slug, is_enabled, runtime_arn, version, default_params, params_schema->'properties'->'context_selection' as context_selection, params_schema->'properties'->'context_folders'->>'default' as folders_default from agents where slug = 'code-review';" -o json > $D/agents-code-review.after.json
