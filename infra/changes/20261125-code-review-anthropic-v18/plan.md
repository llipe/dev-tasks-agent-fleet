# Plan — 20261125-code-review-anthropic-v18

- **ChangeId:** `20261125-code-review-anthropic-v18`
- **Story:** S-218, issue #482 (task list `workstream/tasks-prd-code-review-agent-v1.7-plan.md`, task 3.0)
- **Environment:** prod (`production: true`). AWS account `755641879575`, `us-east-1`; Supabase project `hegxeycmbmjfgzqpdiik`.
- **Identity:** AWS `aws sts get-caller-identity` must show account `755641879575`. Supabase `supabase projects list` must list `hegxeycmbmjfgzqpdiik`. gh: `llipe` (ok).
- **Goal:** move the code-review runtime from version 5 (Bedrock, `deepseek.v3.2`) to version 6 (Claude Sonnet 5.5 on the Anthropic API), in the D-89 order: runtime, then seed migration, then riel `/review` rule.
- **Deploy source:** branch `infra/482-code-review-v18` at `main` f35e5bd (PR #486 merged). Its `agents/code-review/` is `main`, so no cherry-pick is needed (unlike v15).
- **Approval:** step 2 approved by Llipe on 2026-11-26 ("Create the empty/dummy secret so I can update it"). The name changed to `agent-fleet/prod/CODE_REVIEW_ANTHROPIC_API_KEY` because `agent-fleet/prod/ANTHROPIC_API_KEY` is the bug-fix agent's key (Llipe: "Dedicated secret"). Plan and cost approved by Llipe (Felipe Mallea) on 2026-11-26 ("Plan and cost approved"). Each later step still needs its own approval.

## Pre-flight (operator; not steps)

1. `! aws login`. Then `aws sts get-caller-identity` must show account `755641879575`. **Status: ok** (2026-11-26, `aws login --remote`; `arn:aws:iam::755641879575:root`).
2. `! supabase login` with the account that owns `hegxeycmbmjfgzqpdiik`. **Status: ok** (2026-11-26, `supabase login --no-browser`; lists `hegxeycmbmjfgzqpdiik` "dev-tasks-agent-fleet", linked, ACTIVE_HEALTHY). It replaced the riel token. `supabase/.temp/project-ref` already holds `hegxeycmbmjfgzqpdiik`.
3. Local, gitignored `agents/code-review/agentcore/aws-targets.json`. **Status: done.**
4. Docker running. **Status: ok (29.8.2).**

## Cost (`cost_approval_threshold_usd: 0`). APPROVAL REQUIRED

| Item | Monthly estimate | Source |
| --- | --- | --- |
| Secrets Manager secret `agent-fleet/prod/ANTHROPIC_API_KEY` | $0.40 + $0.05 per 10k calls | AWS Secrets Manager pricing |
| Anthropic API, Claude Sonnet 5.5, $2 / $10 per MTok in/out (`config.MODEL_PRICES`, D-87) | typical review ≈ 50k in / 4k out ≈ $0.14; worst case at the 900k budget ≈ $1.80 in + up to $0.64 out ≈ $2.45. At 30 reviews a month: ≈ $5–$75 | price table; spec budget B = 900,000 |
| Bedrock `deepseek.v3.2` | goes to $0 after pass 2 | — |
| One-off verification (steps 11–13) | ≈ 10 reviews + probes ≈ $2–$10 | same table |

Approved by: Llipe (Felipe Mallea), 2026-11-26.

## Gates

- **Hard gate G-A, tier (D-78, R-01).** Step 4 reads the ITPM limit from the `anthropic-ratelimit-input-tokens-limit` response header. If it is **≥ 900,000**, go on. If it is **< 900,000**, the outcome is `blocked`. Lowering the default through a seed migration does **not** fix this: for webhook runs, the runtime's `main.apply_defaults` fills `max_context_tokens` from `config.DEFAULT_PARAMS` (R-01). The fix is a `config.py` change through `developer`, merged before step 7. Then resume.
- **Hard gate G-B, structured output (Q9) and context-length message (Q12).** Step 4 sends the runtime's own `sent_schema` with the runtime's request shape. If `maxItems` is rejected, or the live 400 message does not contain `prompt is too long` (the `model_adapter` matcher), the outcome is `blocked`. The fix is app code, routed to `developer`, never patched here.
- **Migration guard G-C.** Step 14's `db push --dry-run` must list **exactly** `20261125120000_seed_code_review_agent.sql`. Anything else: stop and ask. No unrelated push happens before v6 is live.
- **Order.** The fixture verification (step 10) runs before the migration. It works because the panel fills 150,000 from the old row, and v6 accepts any value up to 900,000.

## Steps

| Step | Kind | Tool | Touches state | Backup | Forward | Verify | Revert |
| ---- | ---- | ---- | ------------- | ------ | ------- | ------ | ------ |
| 1 | backup (read) | aws, supabase | no | n/a | `get-agent-runtime` → `backup/runtime.before.json`; `get-role-policy` → `backup/role-policy.before.json`; `agents` row, `schema_migrations` head, the riel `/review` `webhook_rules` row → `backup/*.before.json`; `describe-secret ANTHROPIC_API_KEY` (expect not found) | READY v5, `MODEL_ID=deepseek.v3.2`; the policy holds `bedrock:InvokeModel`; the row is enabled on the live ARN with max 400000 / default 150000; history head `20261103120000`; the rule row is captured | n/a |
| 2 | set secret | aws (operator, console or own terminal) | yes | n/a (new resource) | the operator creates the key in the Anthropic Console (name `agent-fleet-code-review`) and stores it as `agent-fleet/prod/ANTHROPIC_API_KEY`, Plaintext, default key. The value never enters this session | `describe-secret`: the ARN and its suffix are recorded; no `KmsKeyId` (the default `aws/secretsmanager` key; a CMK would need a `kms:Decrypt` grant the policy lacks); no value read | revoke the key in the Console; `delete-secret --recovery-window-in-days 7` |
| 3 | rename + pin (repo) | git | no (repo file) | git | CDK test first: secret ID `agent-fleet/prod/CODE_REVIEW_ANTHROPIC_API_KEY`, ARN pinned to `-K0guwA`, no wildcard (it fails). Then `agentcore.json` `ANTHROPIC_API_KEY_SECRET_ID` and `iam/runtime-role-policy.json` to match; runbook names. `npm test` | CDK tests pass; no `?` in any secret ARN | `git revert` |
| 4 | probe (read, billed < $0.05) | python (anthropic 2.14.0, boto3) | no | n/a | scratchpad script: key from `get_secret_value` straight into `Anthropic(api_key=…)`, never env, argv or print. (a) a 1-token call `.with_raw_response` → ITPM, tier headers; (b) `sent_schema()` with the runtime's `output_config` + `betas` + `fallbacks`, a tiny fixture prompt → accepted?; (c) an over-window prompt → the 400 message text (rejected requests are not billed) | G-A and G-B outcomes recorded verbatim in `result.md` (headers and messages only) | n/a |
| 5 | backup + interim IAM policy, pass 1 | aws | yes | step 1 `role-policy.before.json` | `jq` builds `role-policy.interim.json` = the pinned policy + the `bedrock:InvokeModel` statement from the backup; `put-role-policy` | simulate: `GetSecretValue` on the full secret ARN → `allowed`; `bedrock:InvokeModel` on `deepseek.v3.2` → `allowed` (v5 still works) | `put-role-policy … file://backup/role-policy.before.json` |
| 6 | deploy check (read) | npm, agentcore | no | n/a | CDK `npm ci && npm test`; `agentcore deploy --diff --json` → `backup/deploy-diff.json` | tests pass; the diff is one `[~] AWS::BedrockAgentCore::Runtime` (env `MODEL_ID`, `+ANTHROPIC_API_KEY_SECRET_ID`) plus the image hash. Any `AWS::IAM::Role` or `bedrock:` → stop | n/a |
| 7 | deploy app | agentcore (CDK) | yes | step 1 (v5 image in ECR, `runtime.before.json`) | `agentcore deploy -y --json` | `backup/runtime.after.json`: READY, v5 → v6, new image, 6 env vars as in `agentcore.json`, role unchanged | `rollback.sh --from 7` (worktree: app code `f4443bd`, `agents/code-review/agentcore` from `f4c66c2`) |
| 8 | record (repo) | git | no | git | commit `.cli/deployed-state.json` | the file names the same runtime and role | `git revert` |
| 9 | (reserved) | — | — | — | merged into step 10 | — | — |
| 10 | verify run (billed, 1 review) | panel (operator) + supabase read | no | n/a | Panel → Invoke → Code Review, `llipe/security-analyst-fixture` PR #5 | run `succeeded` / `needs_review`; 2 blocking findings in `app/pagination.py`; `metrics.answered_by_model` set; footer names the model; the key prefix is absent from the run's CloudWatch events (bounded window, prefix read from a 0600 file) | n/a (no state) |
| 11 | final IAM policy, pass 2 | aws | yes | `backup/role-policy.interim.json` | `put-role-policy … file://agents/code-review/agentcore/iam/runtime-role-policy.json` | simulate: `bedrock:InvokeModel` → `implicitDeny`; `GetSecretValue` on the key → `allowed`; one more fixture run succeeds | `put-role-policy … file://…/role-policy.interim.json` |
| 12 | backup (read) | supabase | no | n/a | `agents` row and `schema_migrations` again → `backup/*.pre-push.json` | unchanged from step 1 | n/a |
| 13 | migration dry run (read) | supabase | no | n/a | `supabase db push --dry-run --linked` → `backup/dry-run.txt` | G-C: exactly `20261125120000` | n/a |
| 14 | database migration (**typed confirmation**) | supabase | yes | step 12 | `supabase db push --linked --yes` → `backup/push.txt` | header verify query → `backup/agents-code-review.after.json`: max 900000 / default 900000, `max_diff_lines` max 20000, enabled, the live ARN unchanged. Operator: the panel form accepts 900,000 and rejects 900,001 | `rollback.sh --from 14`: `db query -f …20261103120000_seed_code_review_agent.sql` + `migration repair --status reverted 20261125120000` |
| 15 | update rule | panel (operator) or `supabase db query` | yes | step 1 `webhook-rule-review.before.json` | the riel rule **"Auto Code Review"** (`15a63a22…`; step 1 found no `/review` rule): `static.max_diff_lines` 10000 → 20000 **and** `static.max_context_tokens` 150000 → 900000; `from_payload.pr_number` stays `pull_request.number`, no `pr_number` under `static` | read the row back → `backup/webhook-rule-review.after.json` | restore the `params` from the backup |
| 16 | live verification (billed, ≈ 8 reviews) | gh (draft PRs) + panel/`/review` | no (draft PRs only) | n/a | AC-12: seeded fixture → blocking; clean PR → clear; 5-PR smoke from `workstream/research-code-review-smoke-cases.md` as draft PRs (base/head branches `smoke/v18-case-N*`), closed afterwards. AC-14: one riel PR of 200k+ tokens. Edge cases: docs-only PR (no model call); a > 20,000-line PR (budget comment); a 429 only if the tier is low | each run's verdict, `answered_by_model`, tokens and `model_ms`; p95 `model_ms` (Q11) | close the draft PRs and delete the `smoke/v18-*` branches |
| 17 | record (repo) | git, gh | no | git | `result.md`; runbook (drop the "not live" banner, live table → v1.8, rollback 4.4 source fix, a v1.8 verification-log row, `last_verified`); `infra/environments.yaml` `model_id`/`change`; task list 3.x; roadmap v1.7/v1.6 rows. Draft PR via github-ops | the draft PR is open; never merged by an agent | close the PR |

## Rollback source (fixed here)

Runbook Rollback 4.4 names "`main` f4443bd's `agents/code-review/`", but `agentcore.json` did not exist on `main` at f4443bd. The v15 rollback's branch `chore/code-review-wave-b-to-main` is deleted. The pinned sources are:
- app code: `f4443bd` (runtime version 5's code);
- `agents/code-review/agentcore/`: `f4c66c2` (`MODEL_ID=deepseek.v3.2`, no `ANTHROPIC_API_KEY_SECRET_ID`; verified with `git show`).

The full v1.8 rollback order is runbook Rollback 4 (rule → seed → IAM → runtime), which `rollback.sh` follows newest-first.
