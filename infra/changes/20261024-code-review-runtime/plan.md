# Change plan: 20261024-code-review-runtime

- **ChangeId:** `infra/changes/20261024-code-review-runtime/`
- **Story / issue:** S-214 (#416), PRD `prd-code-review-agent` Wave B. Branch `llipe/S-214-deployment` → draft PR into `main` (user merges).
- **Environment:** `prod` (`production: true`). AWS account `755641879575`, `us-east-1`; Supabase `hegxeycmbmjfgzqpdiik`; Fly `dt-agent-fleet-panel`.
- **Identity (discover, 2026-10-24):**
  - AWS: `arn:aws:iam::755641879575:root`. Account matches. **Root accepted explicitly by @llipe on 2026-10-24 for this change.** Recommended against; recorded here by name.
  - Supabase CLI: **wrong-identity.** `supabase projects list` shows only the `riel-*` org; `hegxeycmbmjfgzqpdiik` is not visible. Steps 7–8 are blocked until the operator logs in to the right account (`! supabase login`).
  - gh: `llipe` (repo, workflow). Fly: authenticated.
- **Tools:** aws-cli 2.38.5, agentcore 0.28.0, supabase 2.122.0, gh 2.103.2, yq 4.54.1, docker 29.8.2. All `ok`.
- **Approval status:** plan and costs **APPROVED by @llipe on 2026-10-24T12:12-03:00**, with one change: the model is **GPT-6.1 Sol** (`us.openai.gpt-6.1-sol`), not GPT-5.6 Sol ("avoid old versions since they carry additional costs"), recorded as D-58. Step 9 (negative invoke) kept. Each step still needs its own approval.

## Discover findings

| Finding | Evidence | Effect on plan |
| ------- | -------- | -------------- |
| The CDK L3 role grants `bedrock:InvokeModel*` on `foundation-model/*` and `inference-profile/*` | live `security-analyst` role default policy | Use a dedicated role via `executionRoleArn` (bug-fix precedent, `20261023-bug-fix-runtime`); the construct then attaches nothing |
| GPT-6.1 Sol (D-58, supersedes D-17's GPT-5.6 Sol): `authorizationStatus: AUTHORIZED`, `regionAvailability: AVAILABLE`, `agreementAvailability: NOT_AVAILABLE` | `GetFoundationModelAvailability openai.gpt-6.1-sol` | Inference (unverified): a marketplace agreement may be required before the first call. Step 9 tests it; step 10 accepts it if needed |
| System inference profile `us.openai.gpt-6.1-sol` → us-east-1, us-east-2, us-west-2 | `ListInferenceProfiles` | `MODEL_ID=us.openai.gpt-6.1-sol` (spec §9, DR-8); IAM covers the profile plus the three foundation-model ARNs |
| DeepSeek V4 Pro (D-18 fallback) is not on Bedrock in us-east-1 (only V3.2, R1) | `ListFoundationModels` | The fallback statement is documented in the runbook only, not in the policy |
| GitHub App has `issues: write` (includes read) on its only installation `156226839` | bug-fix change step 10b, 2026-10-24T00:46Z | AC-5 confirmed by reference; re-probed in step 11 |
| Panel role `panel-agentcore-invoke` / `invoke-runtime` lists 6 ARNs (adds bug-fix); the committed `infra/agentcore-invoke-policy.json` on `main` lists 4 | live IAM vs. file | Step 6 starts from the **live** policy, not the file, so bug-fix's grant is not dropped |
| `bugfix_bug_fix` runtime is live but not in `infra/environments.yaml` on `main` | `ListAgentRuntimes` | Out of scope here (bug-fix's integration branch adds it); only `code-review` is added |

## Cost (threshold $0: any new recurring cost is approved by name)

| Item | Estimate / month | Source | Status |
| ---- | ---------------- | ------ | ------ |
| New ECR repository `codereview/code_review`, one image ~200 MB (Python slim + deps) | ~$0.02 ($0.10/GB) | https://aws.amazon.com/ecr/pricing/ | **APPROVAL REQUIRED** |
| KMS customer-managed key for the ECR repository (the construct creates one, as for bug-fix) | ~$1.00 | https://aws.amazon.com/kms/pricing/ | **APPROVAL REQUIRED** |
| AgentCore runtime `code_review` | $0 idle; per-invocation CPU/memory seconds | https://aws.amazon.com/bedrock/agentcore/pricing/ | **APPROVAL REQUIRED** (usage-based) |
| CloudWatch Logs for the runtime log group | a few cents at low volume | https://aws.amazon.com/cloudwatch/pricing/ | **APPROVAL REQUIRED** (usage-based) |
| CodeBuild ARM build per deploy | a few cents per deploy | https://aws.amazon.com/codebuild/pricing/ | **APPROVAL REQUIRED** (per deploy) |
| Bedrock GPT-6.1 Sol tokens, ≤ 5 calls per review | per-token; price to be read from the Bedrock console during step 10 and recorded (spec §17 Q3) | https://aws.amazon.com/bedrock/pricing/ | **APPROVAL REQUIRED** (usage-based) |

## Steps

### Step 1: AgentCore project, CDK, and assertion test (repo only)
- **Kind:** pipeline change · **Tool:** git · **Touches state:** no
- **Forward (test-first):**
  1. Copy `agents/security-analyst/agentcore/` (minus `.cli/deployed-state.json`) to `agents/code-review/agentcore/`. Rename the project `codereview` and the runtime `code_review` (`codeLocation: app/codeReview/`, Container, ARM64 by build, `PUBLIC`, HTTP, `PYTHON_3_14`).
  2. `lifecycleConfiguration`: `idleRuntimeSessionTimeout: 900`, `maxLifetime: 1800` (D-32).
  3. `envVars`: `SUPABASE_URL`, `SUPABASE_KEY_SECRET_ID=agent-fleet/prod/SUPABASE_SERVICE_ROLE_KEY`, `MODEL_ID=us.openai.gpt-6.1-sol`, `PANEL_BASE_URL=https://dt-agent-fleet-panel.fly.dev`. `PRICE_*` stay unset until step 10 records prices.
  4. `executionRoleArn: arn:aws:iam::755641879575:role/agent-fleet-code-review-runtime`.
  5. CDK jest tests (`cdk/test/cdk.test.ts`): the synthesized stack creates **no** `AWS::IAM::Role` / `AWS::IAM::Policy` for the runtime and contains no `bedrock:` action; `agentcore.json` asserts lifecycle 900/1800 and the four required env vars (carries S-204 D2). A second test pins `infra/changes/20261024-code-review-runtime/role-policy.json`: exactly the expected actions, Bedrock resources equal to the four Sol ARNs (no `*` in any Bedrock ARN), and Secrets Manager on exactly two ARNs.
  6. Add the `cdk` test to CI next to the siblings' if they run there; otherwise record that it runs locally only.
- **Verify:** `pnpm --dir agents/code-review/agentcore/cdk test` (or `npm` if the sibling uses its `package-lock.json`) passes; `make validate` unchanged.
- **Revert:** `git revert <commit>`.

### Step 2: create IAM role `agent-fleet-code-review-runtime`
- **Kind:** create IAM policy + attach · **Tool:** aws · **Touches state:** yes (new)
- **Backup:** none needed (new). Pre-check: `GetRole` → NoSuchEntity.
- **Forward:** `CreateRole` with `role-trust.json` (bedrock-agentcore.amazonaws.com, `aws:SourceAccount` + `aws:SourceArn` conditions; same as bug-fix), tags `environment=prod owner=llipe ChangeId=20261024-code-review-runtime agent=code-review`; `PutRolePolicy code-review-runtime` with `role-policy.json`:
  - Logs on `/aws/bedrock-agentcore/runtimes/*`, `logs:DescribeLogGroups`, X-Ray, configuration-bundle reads, `ecr:GetAuthorizationToken`, ECR pull on `repository/codereview/*`;
  - `kms:Decrypt` on `key/*` **conditioned on** `kms:ViaService=ecr.us-east-1.amazonaws.com` (narrowed in step 5);
  - `secretsmanager:GetSecretValue` on exactly `…:secret:agent-fleet/prod/SUPABASE_SERVICE_ROLE_KEY-wS5xrJ` and `…:secret:agent-fleet/prod/GITHUB_APP_PRIVATE_KEY-t4sXT2`;
  - `bedrock:InvokeModel` on `arn:aws:bedrock:us-east-1:755641879575:inference-profile/us.openai.gpt-6.1-sol` and `arn:aws:bedrock:{us-east-1,us-east-2,us-west-2}::foundation-model/openai.gpt-6.1-sol`.
- **Verify:** `GetRolePolicy` equals the file.
- **Revert:** `DeleteRolePolicy` then `DeleteRole`.

### Step 3: simulate the role (read-only)
- **Kind:** discover · **Tool:** aws (`SimulatePrincipalPolicy`) · **Touches state:** no
- **Forward:** allow `bedrock:InvokeModel` on the profile and the us-east-2 model ARN; deny it on `openai.gpt-5.6-sol` (the older Sol, D-58) and a Sonnet model; allow `GetSecretValue` on the two secrets; deny it on `ANTHROPIC_API_KEY`; deny `bedrock:InvokeModelWithResponseStream`, `s3:PutObject`.
- **Verify / Revert:** results recorded; n/a.

### Step 4: deploy the runtime (CDK)
- **Kind:** build image + deploy app · **Tool:** agentcore (CDK) · **Touches state:** yes (new stack, ECR repository, KMS key, image, runtime)
- **Preconditions:** Docker running; local gitignored `agents/code-review/agentcore/aws-targets.json` (`default` → `755641879575`/`us-east-1`); the code at `main` @ `5a056b8` (contains S-213).
- **Backup:** none needed (new). Pre-check: no `codereview_code_review` runtime (confirmed).
- **Forward:** `cd agents/code-review && agentcore deploy -y`
- **Verify:** `agentcore status` READY; `GetAgentRuntime` → `roleArn` = `agent-fleet-code-review-runtime`, lifecycle 900/1800, env vars as step 1; image ARM64, digest recorded; runtime ID/ARN recorded; `.cli/deployed-state.json` committed.
- **Revert:** `aws cloudformation delete-stack --stack-name AgentCore-codereview-default`, then `ecr delete-repository --repository-name codereview/code_review --force` if retained.

### Step 5: narrow `kms:Decrypt` to the deployed key
- **Kind:** attach IAM policy · **Tool:** aws · **Touches state:** yes
- **Backup:** `backup/role-policy.step2.json`
- **Forward:** replace `key/*` with the ECR repository's key ARN (from `DescribeRepositories`), keep the `ViaService` condition; `PutRolePolicy`.
- **Verify:** live policy equals the file; step 1's policy test still passes.
- **Revert:** `PutRolePolicy` with the backup.

### Step 6: panel invoke policy
- **Kind:** attach IAM policy · **Tool:** aws · **Touches state:** yes
- **Backup:** `GetRolePolicy panel-agentcore-invoke/invoke-runtime` → `backup/panel-invoke-policy.before.json` (6 ARNs today)
- **Forward:** add the runtime ARN and `…/runtime-endpoint/DEFAULT` to the **live** document (8 ARNs); write it to `infra/agentcore-invoke-policy.json` (which also brings the file up to date with bug-fix's live grant); `PutRolePolicy`.
- **Verify:** `GetRolePolicy` lists 8 resources; simulation allows `InvokeAgentRuntime` on the new ARN and endpoint.
- **Revert:** `PutRolePolicy` with the backup.

### Step 7: apply the seed migration to prod (**explicit confirmation**)
- **Kind:** database migration · **Tool:** supabase · **Touches state:** yes · **Blocked until** the Supabase CLI identity sees `hegxeycmbmjfgzqpdiik`
- **Backup:** `supabase migration list --linked` (record what is pending) and `select * from agents where slug = 'code-review'` → `backup/agents-code-review.before.json` (expected: no row)
- **Forward:** `supabase db push --linked` **only if** the pending list is exactly `20261022120000_seed_code_review_agent.sql` (any other pending migration stops the step and comes back to you).
- **Verify:** `select slug, is_enabled, runtime_arn, params_schema from agents where slug = 'code-review'` → spec §5.1 schema, `is_enabled = false`, placeholder ARN.
- **Revert:** `delete from agents where slug = 'code-review'` (no `runs` reference it yet) and `delete from supabase_migrations.schema_migrations where version = '20261022120000'`.

### Step 8: set `runtime_arn` and enable the row (one update, D-39)
- **Kind:** database migration (data) · **Tool:** supabase (`db query --linked`) · **Touches state:** yes
- **Backup:** step 7's post-state row → `backup/agents-code-review.step7.json`
- **Forward:** `update agents set runtime_arn = '<step 4 ARN>', is_enabled = true where slug = 'code-review'`
- **Verify:** the row has the deployed ARN and `is_enabled = true`; the panel invoke form for `code-review` renders six params.
- **Revert:** `update agents set is_enabled = false, runtime_arn = '<placeholder>' where slug = 'code-review'`

### Step 9: negative panel invoke: model access not yet confirmed (edge case)
- **Kind:** verification invocation · **Tool:** panel (operator) · **Touches state:** one `runs` row + one PR comment
- **Forward:** panel invoke `code-review` on a scratch PR (a small throwaway PR in `llipe/dev-tasks-agent-fleet`, or one you name).
- **Verify (one of):**
  - (a) `failed`/`BEDROCK_ACCESS_DENIED` with a failure comment → the edge case is reproduced; step 10 is needed.
  - (b) a review comment → no agreement is needed; this becomes AC-8 evidence, step 10 is `skipped(not required)`, and the edge case is recorded as not reproducible.
- **Revert:** delete the scratch comment if wanted.

### Step 10: accept the Bedrock model agreement for GPT-6.1 Sol (only if step 9 = a)
- **Kind:** model access (account-level, application tier: one model, revertible) · **Tool:** aws (`ListFoundationModelAgreementOffers` → `CreateFoundationModelAgreement`) · **Touches state:** yes
- **Backup:** `GetFoundationModelAvailability` before → `backup/model-availability.before.json`
- **Forward:** accept the public offer for `openai.gpt-6.1-sol`; read and record per-token prices (§17 Q3).
- **Verify:** `agreementAvailability.status = AVAILABLE`.
- **Revert:** `DeleteFoundationModelAgreement --model-id openai.gpt-6.1-sol`.

### Step 11: positive panel invoke (AC-8) + App re-probe
- **Kind:** verification invocation · **Tool:** panel (operator) · **Touches state:** one `runs` row + one PR comment
- **Forward:** repeat step 9's invoke.
- **Verify:** run `succeeded`; the run detail shows steps and the `audit_report` artifact; the PR has the review comment; run ID recorded in the runbook verification log.
- **Revert:** none needed (one comment on a scratch PR).

### Step 12: records, runbook, draft PR
- **Kind:** repo and PR operation · **Tool:** git / gh (`github-ops`) · **Touches state:** no
- **Forward:** add `code-review` to `infra/environments.yaml`; write `docs/runbooks/code-review-deployment.md` (deploy, model access, IAM, rotation, rollback = disable rule → disable agent → redeploy previous image, verification log) and index it in `docs/runbooks/README.md` and `EXPECTED_RUNBOOKS`; `commands.sh`, `rollback.sh`, `result.md`; update `docs/roadmap.md` Wave B row; tick #416; draft PR into `main`.
- **Revert:** close the PR, revert commits.

Order: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → (10) → 11 → 12.
