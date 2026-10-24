# Change plan — 20261024-code-review-runtime

- **ChangeId:** `infra/changes/20261024-code-review-runtime/`
- **Issue:** #416 (S-214, Wave B of `prd-code-review-agent`; ACs 3–6 and 8 are verified here)
- **Environment:** `prod` (`production: true`)
- **Resolved identity:** _to fill at execution_ — `aws sts get-caller-identity` (expected account `755641879575`, `us-east-1`); `agentcore --version`; Supabase project `hegxeycmbmjfgzqpdiik`; target `default`
- **Source ref to deploy:** _to fill_ — the commit of `integration/code-review-agent-wave-b` (or `main`) that carries `agents/code-review/agentcore/` (S-214) on top of the Wave A agent (S-204–S-213)
- **Revert ref:** none for the first deploy (new runtime; rollback is disable + delete, see each step)
- **Cost summary:** one new AgentCore runtime (billed per active session), one ECR repository plus a KMS key (~$1/month for the key, ~$0.10/GB-month for the image), one CodeBuild ARM build per deploy, and Bedrock tokens per review (Sol prices are spec §17 Q3, recorded at Step 2). Listed for awareness.
- **Approval status:** NOT YET APPROVED. Every step below is `planned` and needs its own explicit approval from @llipe through `infra-engineer`.
- **Runbook:** [`docs/runbooks/code-review-deployment.md`](../../../docs/runbooks/code-review-deployment.md)

## Preconditions

- Wave A merged into the branch being deployed; `make -C agents/code-review/app/codeReview validate` green.
- `agents/code-review/agentcore/cdk`: `npm ci && npm test` green (the least-privilege role assertions).
- `agents/code-review/agentcore/aws-targets.json` present (gitignored; the CLI writes it from ambient credentials on first deploy, or copy a sibling's).
- Valid AWS credentials for account `755641879575` (not available in the container that wrote this plan).
- `MODEL_ID` confirmed (Step 2) **before** Step 1, or Step 1 is repeated after Step 2 changes it.

## Backup (pre-change state, recorded as the restore point)

| Item                                                                | Pre-change state                                             | Where captured                                                 |
| ------------------------------------------------------------------- | ------------------------------------------------------------ | -------------------------------------------------------------- |
| `codereview` runtime                                                | does not exist                                               | `aws bedrock-agentcore-control list-agent-runtimes`            |
| Panel role `panel-agentcore-invoke`, inline policy `invoke-runtime` | two runtimes (dependency-update, security-analyst)           | `backup/runtime-invoke-policy.before.json` (capture at Step 3) |
| GitHub App installation permissions                                 | _to capture_                                                 | `backup/app-permissions.before.json` (Step 4)                  |
| `agents` row `code-review` (prod)                                   | absent, or seeded disabled with `pending-deploy:code-review` | `backup/agents-row.before.json` (Step 5)                       |

## Steps

### Step 1 — Deploy the runtime

- **Status:** planned
- **Kind:** build image + create stack · **Tool:** agentcore (CDK) · **Touches state:** yes (new stack `AgentCore-codereview-default`)
- **Forward:** `cd agents/code-review && agentcore deploy -y`
- **Verify:** `agentcore status` → READY; record the runtime ARN and id from `agentcore/.cli/deployed-state.json`; `aws bedrock-agentcore-control get-agent-runtime --agent-runtime-id <id> --region us-east-1` shows `lifecycleConfiguration` 900/1800 and the env vars; `aws iam get-role-policy` on the runtime role shows exactly the 8 statements of `cdk/lib/runtime-policy.ts` (no `foundation-model/*`)
- **Revert:** `aws cloudformation delete-stack --stack-name AgentCore-codereview-default --region us-east-1` (the ECR repository and KMS key follow the stack's removal policy; check and delete if retained)

### Step 2 — Bedrock model access and `MODEL_ID` confirmation

- **Status:** planned
- **Kind:** Bedrock console/model-access grant + config confirmation · **Tool:** console, aws · **Touches state:** yes (model access)
- **Forward:** enable OpenAI GPT-5.6 Sol in `us-east-1` (and each Region of its `us.` profile). Confirm the IDs with `aws bedrock list-inference-profiles --region us-east-1` and `aws bedrock get-inference-profile --inference-profile-identifier <id>`. If they differ from the candidates (`us.openai.gpt-5-6-sol-v1:0`, `openai.gpt-5-6-sol-v1:0`, Regions us-east-1/us-east-2/us-west-2), edit `agentcore.json` `MODEL_ID`, `cdk/lib/runtime-policy.ts` and `cdk/test/code-review-runtime.test.ts` in one commit, then repeat Step 1.
- **Verify:** `MODEL_ID` in the deployed env equals the confirmed ID (TC-214-06); one invoke before access is enabled ends `failed`/`BEDROCK_ACCESS_DENIED` with a failure comment (TC-214-12, verify once); record Sol per-token prices (§17 Q3)
- **Revert:** disable model access in the console (no runtime change needed)

### Step 3 — Panel invoke policy

- **Status:** planned
- **Kind:** IAM inline-policy update · **Tool:** aws · **Touches state:** yes
- **Forward:** add the runtime ARN and `<runtime ARN>/runtime-endpoint/DEFAULT` to `infra/agentcore-invoke-policy.json` (issue #280 pattern), then `aws iam put-role-policy --role-name panel-agentcore-invoke --policy-name invoke-runtime --policy-document file://infra/agentcore-invoke-policy.json`
- **Verify:** `aws iam get-role-policy --role-name panel-agentcore-invoke --policy-name invoke-runtime` matches the file; `aws iam simulate-principal-policy` allows `bedrock-agentcore:InvokeAgentRuntime` on both ARNs (TC-214-07)
- **Revert:** `aws iam put-role-policy … --policy-document file://infra/changes/20261024-code-review-runtime/backup/runtime-invoke-policy.before.json`

### Step 4 — GitHub App Issues read

- **Status:** planned
- **Kind:** GitHub App permission check (and grant if missing) · **Tool:** GitHub App settings, gh · **Touches state:** only if the grant is missing
- **Forward:** check the installation's permissions include `issues: read` (the `bug-fix` Wave A change, task 2.6, requests read and write); if missing, request it in the App settings and accept it on every installation in `github_installations`
- **Verify:** installation permissions list `issues`; a `GET /repos/{owner}/{repo}/issues/{n}` with an installation token returns 200 (TC-214-08)
- **Revert:** remove the permission in the App settings (only if this step added it)

### Step 5 — Apply the seed migration to prod

- **Status:** planned
- **Kind:** data migration · **Tool:** supabase · **Touches state:** yes (inserts the disabled `code-review` row)
- **Forward:** after explicit user confirmation: `supabase db push` (applies `20261022120000_seed_code_review_agent.sql` if not yet recorded)
- **Verify:** `select slug, is_enabled, runtime_arn, max_runtime_seconds, grace_seconds from agents where slug = 'code-review';` → `false`, `pending-deploy:code-review`, 1800, 120 (TC-214-09, first half)
- **Revert:** `delete from agents where slug = 'code-review';` (only while no `runs` row references it; otherwise leave it disabled)

### Step 6 — Enable the row (D-39, one update)

- **Status:** planned
- **Kind:** data update · **Tool:** SQL against prod · **Touches state:** yes
- **Forward:** `update agents set runtime_arn = '<runtime ARN>', is_enabled = true where slug = 'code-review' and runtime_arn = 'pending-deploy:code-review' returning slug, runtime_arn, is_enabled;`
- **Verify:** the `returning` row shows the deployed ARN and `true` (TC-214-09, second half)
- **Revert:** `update agents set is_enabled = false where slug = 'code-review';`

### Step 7 — Panel invoke verification

- **Status:** planned
- **Kind:** verification invocation · **Tool:** panel · **Touches state:** one normal `runs` row and one PR comment
- **Forward:** from https://dt-agent-fleet-panel.fly.dev invoke `code-review` with `pr_number` of a scratch PR in a registered repository
- **Verify:** one comment on that PR; the run detail shows the steps and the `audit_report` artifact; record the run ID in the runbook verification log (TC-214-11)
- **Revert:** none (delete the comment if unwanted); on failure, Step 6's revert

### Step 8 — Record and close

- **Status:** planned
- **Forward:** fill `result.md`, `commands.sh`, `rollback.sh`; commit `agentcore/.cli/deployed-state.json` and the `infra/agentcore-invoke-policy.json` edit; update the runbook verification log and `last_verified`
- **Revert:** n/a (records only)
