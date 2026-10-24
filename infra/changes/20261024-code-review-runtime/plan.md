# Change plan — 20261024-code-review-runtime

- **ChangeId:** `infra/changes/20261024-code-review-runtime/`
- **Issue:** #416 (S-214, Wave B of `prd-code-review-agent`; ACs 3–6 and 8 are verified here)
- **Environment:** `prod` (`production: true`)
- **Resolved identity:** _to fill at execution_ — `aws sts get-caller-identity` (expected account `755641879575`, `us-east-1`); `agentcore --version`; Supabase project `hegxeycmbmjfgzqpdiik`; target `default`
- **Source ref to deploy:** _to fill_ — the commit of `integration/code-review-agent-wave-b` (or `main`) that carries `agents/code-review/agentcore/` (S-214) on top of the Wave A agent (S-204–S-213)
- **Revert ref:** none for the first deploy (new runtime; rollback is disable + delete, see each step)
- **Cost summary:** one new AgentCore runtime (billed per active session), one ECR repository plus a KMS key (~$1/month for the key, ~$0.10/GB-month for the image), one CodeBuild ARM build per deploy, and Bedrock tokens per review (Sol prices are spec §17 Q3, recorded at Step 9). Listed for awareness.
- **Approval status:** NOT YET APPROVED. Every step below is `planned` and needs its own explicit approval from @llipe through `infra-engineer`.
- **Runbook:** [`docs/runbooks/code-review-deployment.md`](../../../docs/runbooks/code-review-deployment.md)

## Preconditions

- Wave A merged into the branch being deployed; `make -C agents/code-review/app/codeReview validate` green.
- `agents/code-review/agentcore/cdk`: `npm ci && npm test` green (the least-privilege role assertions; synth also fails on an unknown construct grant).
- `agents/code-review/agentcore/aws-targets.json` present (gitignored; the CLI writes it from ambient credentials on first deploy, or copy a sibling's).
- Valid AWS credentials for account `755641879575` (not available in the container that wrote this plan).
- An admin principal for Step 9 that can manage Bedrock model access and, if Sol is a Marketplace product, holds `aws-marketplace:Subscribe`/`ViewSubscriptions`. The runtime role deliberately has neither.

## Ordering rule

Steps run in number order, and every check runs only after the steps it depends on. The runbook uses the same numbers.

| Step                              | Depends on                    |
| --------------------------------- | ----------------------------- |
| 1 confirm Sol IDs                 | —                             |
| 2 deploy + IAM check              | 1                             |
| 3 panel invoke policy             | 2                             |
| 4 App Issues read                 | —                             |
| 5 migration preview               | —                             |
| 6 seed apply                      | 5 (confirmed list)            |
| 7 enable row                      | 2, 6                          |
| 8 access-denied check (TC-214-12) | 3, 7, and Step 9 not yet done |
| 9 model access                    | 1                             |
| 10 panel invoke (TC-214-11)       | 3, 4, 7, 9                    |
| 11 record and close               | all                           |

## Backup (pre-change state, recorded as the restore point)

| Item                                                                | Pre-change state                                             | Where captured                                                     |
| ------------------------------------------------------------------- | ------------------------------------------------------------ | ------------------------------------------------------------------ |
| `codereview` runtime                                                | does not exist                                               | `aws bedrock-agentcore-control list-agent-runtimes`                |
| Panel role `panel-agentcore-invoke`, inline policy `invoke-runtime` | two runtimes (dependency-update, security-analyst)           | `backup/runtime-invoke-policy.before.json` (Step 3)                |
| GitHub App installation permissions                                 | _to capture_                                                 | `backup/app-permissions.before.json` (Step 4)                      |
| Pending prod migrations                                             | _to capture_                                                 | `backup/migration-list.before.txt` (Step 5)                        |
| `agents` row `code-review` (prod)                                   | absent, or seeded disabled with `pending-deploy:code-review` | `backup/agents-row.before.json` (Step 6)                           |
| Bedrock model access / Marketplace subscriptions                    | Sol not enabled (assumed)                                    | console screenshot or `get-foundation-model-availability` (Step 9) |

## Steps

### Step 1 — Confirm the Sol profile ID, foundation-model ID and Regions

- **Status:** planned
- **Kind:** read-only discovery, plus a repo commit if the IDs differ · **Tool:** aws, git · **Touches state:** no (AWS)
- **Forward:** `aws bedrock list-inference-profiles --region us-east-1` and `aws bedrock get-inference-profile --inference-profile-identifier <id> --query 'models[].modelArn'`. Compare with the candidates: profile `us.openai.gpt-5-6-sol-v1:0`, foundation model `openai.gpt-5-6-sol-v1:0`, Regions us-east-1/us-east-2/us-west-2. If any differs, update `agentcore.json` (`MODEL_ID`), `cdk/lib/runtime-policy.ts` (`SOL_*`) and `cdk/test/code-review-runtime.test.ts` together in one commit.
- **Verify:** the confirmed IDs are a model ID or a system-defined profile ID (never an application-profile ARN); `npm test` green after any edit; IDs recorded in result.md and the runbook log
- **Revert:** revert the commit

### Step 2 — Deploy the runtime and check its IAM

- **Status:** planned
- **Kind:** build image + create stack · **Tool:** agentcore (CDK) · **Touches state:** yes (new stack `AgentCore-codereview-default`)
- **Forward:** `cd agents/code-review && agentcore deploy -y`
- **Verify:** `agentcore status` → READY; record the runtime ARN and id from `agentcore/.cli/deployed-state.json`; `aws bedrock-agentcore-control get-agent-runtime --agent-runtime-id <id> --region us-east-1` shows `lifecycleConfiguration` 900/1800 and the env vars; `aws iam get-role-policy` on the runtime role shows exactly the 8 statements of `cdk/lib/runtime-policy.ts` (no `foundation-model/*`, no `aws-marketplace:*`)
- **Revert:** `aws cloudformation delete-stack --stack-name AgentCore-codereview-default --region us-east-1` (check whether the ECR repository and KMS key are retained, and delete them if so)

### Step 3 — Panel invoke policy

- **Status:** planned
- **Kind:** IAM inline-policy update · **Tool:** aws · **Touches state:** yes
- **Forward:** back up the current policy, add the runtime ARN and `<runtime ARN>/runtime-endpoint/DEFAULT` to `infra/agentcore-invoke-policy.json` (issue #280 pattern), then `aws iam put-role-policy --role-name panel-agentcore-invoke --policy-name invoke-runtime --policy-document file://infra/agentcore-invoke-policy.json`
- **Verify:** `aws iam get-role-policy --role-name panel-agentcore-invoke --policy-name invoke-runtime` matches the file; `aws iam simulate-principal-policy` allows `bedrock-agentcore:InvokeAgentRuntime` on both ARNs (TC-214-07)
- **Revert:** `aws iam put-role-policy … --policy-document file://infra/changes/20261024-code-review-runtime/backup/runtime-invoke-policy.before.json`

### Step 4 — GitHub App Issues read

- **Status:** planned
- **Kind:** GitHub App permission check (and grant if missing) · **Tool:** GitHub App settings, gh · **Touches state:** only if the grant is missing
- **Forward:** check that the installation's permissions include `issues: read` (the `bug-fix` Wave A change, task 2.6, requests read and write). If missing, request it in the App settings and accept it on every installation in `github_installations`
- **Verify:** the installation permissions list `issues`; a `GET /repos/{owner}/{repo}/issues/{n}` with an installation token returns 200 (TC-214-08)
- **Revert:** remove the permission in the App settings (only if this step added it)

### Step 5 — Preview the prod migrations

- **Status:** planned
- **Kind:** read-only preview · **Tool:** supabase · **Touches state:** no
- **Forward:** `supabase migration list --linked > backup/migration-list.before.txt` and `supabase db push --dry-run`. `db push` applies every unrecorded migration, not only the seed. Put the exact pending list in the confirmation request for Step 6.
- **Verify:** the list contains `20261022120000_seed_code_review_agent.sql`; any other pending migration is named. The user confirms **that exact list**, or it is reduced first.
- **Revert:** n/a

### Step 6 — Apply the seed migration to prod (confirmed list)

- **Status:** planned
- **Kind:** data migration · **Tool:** supabase · **Touches state:** yes (inserts the disabled `code-review` row, plus anything else on the confirmed list)
- **Forward:** re-run `supabase db push --dry-run`. If the list differs from the one confirmed in Step 5, stop and go back to Step 5. Otherwise run `supabase db push`.
- **Verify:** `supabase migration list --linked` shows the confirmed migrations under Remote; `select slug, is_enabled, runtime_arn, max_runtime_seconds, grace_seconds from agents where slug = 'code-review';` returns `false`, `pending-deploy:code-review`, 1800, 120 (TC-214-09, first half)
- **Revert:** `delete from agents where slug = 'code-review';` (only while no `runs` row references it; otherwise leave it disabled)

### Step 7 — Enable the row (D-39, one update)

- **Status:** planned
- **Kind:** data update · **Tool:** SQL against prod · **Touches state:** yes · needs its own explicit confirmation
- **Forward:** `update agents set runtime_arn = '<runtime ARN>', is_enabled = true where slug = 'code-review' and runtime_arn = 'pending-deploy:code-review' returning slug, runtime_arn, is_enabled;`
- **Verify:** the `returning` row shows the deployed ARN and `true` (TC-214-09, second half)
- **Revert:** `update agents set is_enabled = false where slug = 'code-review';`

### Step 8 — Access-denied check before model access (TC-214-12, once)

- **Status:** planned
- **Kind:** verification invocation · **Tool:** panel · **Touches state:** one `runs` row and one failure comment
- **Forward:** with Steps 3 and 7 done and Sol access **not** enabled, invoke `code-review` from the panel on a scratch PR
- **Verify:** the run ends `failed`/`BEDROCK_ACCESS_DENIED` with one failure comment; record the run ID. If access is already enabled in the account, record `SKIPPED(access already enabled)`
- **Revert:** none (delete the comment if unwanted)

### Step 9 — Bedrock model access for Sol (admin principal)

- **Status:** planned
- **Kind:** account-level model access, and a Marketplace subscription if Sol is a Marketplace product · **Tool:** Bedrock console, aws (admin credentials) · **Touches state:** yes (account)
- **Forward:** an admin principal enables Sol access in `us-east-1` and every Region from Step 1. If access goes through an AWS Marketplace subscription, the admin completes it **before the runtime's first successful invocation**, with one small `aws bedrock-runtime converse` call using the admin credentials. The runtime role deliberately has no `aws-marketplace` permissions, so it cannot subscribe itself.
- **Verify:** `aws bedrock get-foundation-model-availability --model-id <foundation model id>` (where the CLI supports it) shows access authorized; the Marketplace subscription is active, if one applies; `MODEL_ID` in the deployed env equals the ID confirmed in Step 1 (TC-214-06); Sol per-token prices recorded (§17 Q3)
- **Revert:** remove model access; cancel the Marketplace subscription if this step created one

### Step 10 — Panel invoke verification (TC-214-11)

- **Status:** planned
- **Kind:** verification invocation · **Tool:** panel · **Touches state:** one `runs` row and one PR comment
- **Forward:** from https://dt-agent-fleet-panel.fly.dev, invoke `code-review` with the `pr_number` of a scratch PR in a registered, enabled repository
- **Verify:** one review comment on that PR; the run detail shows the steps and the `audit_report` artifact; the run ID and model ID are recorded in the runbook verification log
- **Revert:** none (delete the comment if unwanted); on failure, Step 7's revert

### Step 11 — Record and close

- **Status:** planned
- **Forward:** fill in `result.md`, `commands.sh` and `rollback.sh`; commit `agentcore/.cli/deployed-state.json` and the `infra/agentcore-invoke-policy.json` edit; update the runbook verification log and `last_verified`
- **Revert:** n/a (records only)
