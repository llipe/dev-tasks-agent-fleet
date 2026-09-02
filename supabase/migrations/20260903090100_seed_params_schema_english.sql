-- =====================================================================
-- S-103 (issue #116) — English-only SQL surface: params_schema labels
--
-- Translates the operator-facing `title`/`description` of every property in
-- the `dependency-update` agent's params_schema from Spanish to English.
-- These labels feed the schema-driven invoke form (D2 / S-113), so they are
-- rendered verbatim to the operator.
--
-- Structure is unchanged: `type`, `additionalProperties: false`, `required`,
-- each property's `type`/`enum`/`default`/`minimum`/`maximum` are identical to
-- the seeded schema — only human-readable text changes. Idempotent: a plain
-- UPDATE keyed on the slug; re-applying is a no-op on an already-English row.
--
-- Reversible: re-apply the prior (Spanish) params_schema JSON (reproduced in
-- the PR description). The canonical seed (supabase/seed.sql) is updated to
-- match so a fresh `db reset` and the live project converge (task 2.7).
-- =====================================================================

update agents
   set params_schema = $json${
     "type": "object",
     "additionalProperties": false,
     "required": ["fix_mode"],
     "properties": {
       "fix_mode": {
         "type": "string",
         "title": "Fix mode",
         "description": "audit_only reports findings. llm_fix attempts a fix and opens a PR.",
         "enum": ["audit_only", "llm_fix"],
         "default": "audit_only"
       },
       "fail_on_findings": {
         "type": "boolean",
         "title": "Fail if findings exist",
         "description": "Only applies in audit_only mode.",
         "default": true
       },
       "max_fix_attempts": {
         "type": "integer",
         "title": "Max LLM agent attempts",
         "description": "Only applies in llm_fix mode. 0 disables the LLM agent. Range 0..5.",
         "minimum": 0,
         "maximum": 5,
         "default": 3
       },
       "base_branch": {
         "type": "string",
         "title": "PR base branch",
         "description": "Branch the PR is opened against. Defaults to the repo default branch (main).",
         "default": "main"
       }
     }
   }$json$::jsonb
 where slug = 'dependency-update';
