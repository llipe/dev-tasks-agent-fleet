---
name: runbook-code-review-deployment
trigger: Deploying or redeploying the code-review AgentCore runtime, changing its MODEL_ID or IAM, rotating its secrets, or rolling it back
owner: operator (repository owner), through infra-engineer with per-step approval
last_verified: never (not yet deployed)
related:
  [
    "agents/code-review/agentcore/agentcore.json",
    "agents/code-review/agentcore/cdk/lib/runtime-policy.ts",
    "agents/code-review/agentcore/cdk/test/code-review-runtime.test.ts",
    "infra/agentcore-invoke-policy.json",
    "infra/changes/2026-10-24-code-review-runtime/plan.md",
    "supabase/migrations/20261022120000_seed_code_review_agent.sql",
  ]
---

# Runbook — code-review runtime deployment

Deploys the `code-review` agent (`agents/code-review/`) as the AgentCore runtime
`codereview_code_review`, gives it Bedrock access to the Sol model only, lets the
panel invoke it, and enables its `agents` row. Companion to
[`prd-code-review-agent`](../requirements/prd-code-review-agent.md) and spec §7.2,
§9 and §15 (`workstream/specification-prd-code-review-agent.md`). The `/review`
webhook rule and the 5-PR smoke are S-215, not this runbook.

Every step runs through `infra-engineer`, one approved step at a time, recorded
in [`infra/changes/2026-10-24-code-review-runtime/`](../../infra/changes/2026-10-24-code-review-runtime/plan.md).
The change record has no separate IAM step: this runbook's step 3 is checked as
part of its step 1, so its steps 3–7 are this runbook's steps 4–8.

**Blast radius:** step 1 creates a new stack (no existing resource changes).
Step 3 edits the panel role's invoke policy, so a bad document can break invokes
of every agent. Steps 5–6 write to the prod `agents` table. Once the row is
enabled, any panel user can post a review comment on a PR in a registered
repository.

## Preconditions

- Wave A merged into the branch being deployed;
  `make -C agents/code-review/app/codeReview validate` is green.
- `cd agents/code-review/agentcore/cdk && npm ci && npm test` is green. The CDK
  test pins the runtime role to exactly the statements in `lib/runtime-policy.ts`.
- AWS credentials for account `755641879575`, `us-east-1`
  (`aws sts get-caller-identity`). The AgentCore CLI is installed (`agentcore --version`).
- `agents/code-review/agentcore/aws-targets.json` exists. It is gitignored because
  it holds the account ID. The CLI writes it on first deploy, or copy a sibling's.
- The two secrets exist: `agent-fleet/prod/SUPABASE_SERVICE_ROLE_KEY` and
  `agent-fleet/prod/GITHUB_APP_PRIVATE_KEY`. The PEM's full ARN is
  `github_installations.private_key_secret_arn`.
- Explicit user approval for each step. The prod seed apply (step 5) and the
  enable update (step 6) each need a separately recorded confirmation.

## Configuration this runbook deploys

| Setting                                                      | Value                                                                     | Source                                                                                         |
| ------------------------------------------------------------ | ------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| Runtime                                                      | `code_review`, Container (ARM64 CodeBuild), `PUBLIC`, HTTP, `PYTHON_3_14` | `agentcore.json`                                                                               |
| Lifecycle                                                    | `idleRuntimeSessionTimeout` 900, `maxLifetime` 1800                       | must equal `config.IDLE_SESSION_TIMEOUT` / `MAX_LIFETIME` and the seed's `max_runtime_seconds` |
| `SUPABASE_URL`                                               | `https://hegxeycmbmjfgzqpdiik.supabase.co`                                | sibling value                                                                                  |
| `SUPABASE_KEY_SECRET_ID`                                     | `agent-fleet/prod/SUPABASE_SERVICE_ROLE_KEY`                              | sibling value                                                                                  |
| `MODEL_ID`                                                   | `us.openai.gpt-5-6-sol-v1:0`, **a candidate: confirm at step 2**          | spec §9, §17 Q1                                                                                |
| `PANEL_BASE_URL`                                             | `https://dt-agent-fleet-panel.fly.dev`                                    | run links (D-29)                                                                               |
| `AWS_REGION`                                                 | `us-east-1`                                                               | spec §9                                                                                        |
| `HEARTBEAT_INTERVAL`, `IDLE_SESSION_TIMEOUT`, `MAX_LIFETIME` | 120, 900, 1800                                                            | `config.py` defaults                                                                           |
| `PRICE_INPUT_PER_MTOK`, `PRICE_OUTPUT_PER_MTOK`              | not set, so `cost_usd` is null                                            | add after step 2 records the prices (§17 Q3)                                                   |

The GitHub App ID, installation ID, and PEM ARN are not environment variables.
The agent reads them from `github_installations` for the run's organization.

## Steps

### 1. Deploy the runtime

```bash
cd agents/code-review
agentcore deploy -y      # non-interactive build (CodeBuild, ARM64) + CloudFormation deploy
agentcore status         # expect READY; note the runtime ARN
cat agentcore/.cli/deployed-state.json   # runtimeArn, runtimeId, roleArn
```

On a **redeploy**, check that the runtime's `lastUpdatedAt` and version have
changed before testing. A run created seconds before the change runs on the
previous image (security-analyst S-141):

```bash
aws bedrock-agentcore-control get-agent-runtime \
  --agent-runtime-id <runtimeId> --region us-east-1 \
  --query '{version:agentRuntimeVersion,updated:lastUpdatedAt,status:status,life:lifecycleConfiguration}'
```

Then check the IAM role (see "IAM" below). `agentcore` drives the vended CDK
project in `agentcore/cdk/`. If a CLI upgrade ever re-vends `lib/cdk-stack.ts`,
the `restrictRuntimeRole` call is lost and the role gets the construct's
wildcard Bedrock grant back. The IAM check is how you catch that.

Startup failures (for example, a missing required environment variable) end the
process before any run update. The run row is left to the reaper. Read them in
CloudWatch under `/aws/bedrock-agentcore/runtimes/<runtimeId>-DEFAULT`.

Reversible: yes, by deleting the stack (see Rollback).

### 2. Bedrock model access and `MODEL_ID`

1. Before enabling access, invoke once (panel or `agentcore invoke`) on a scratch
   PR. Expect the run to end `failed`/`BEDROCK_ACCESS_DENIED` with a failure comment
   on the PR (TC-214-12). Record the run ID below. This needs steps 4, 6 and 7 done
   first, so in practice run it right after step 7, before enabling access.
2. Enable OpenAI GPT-5.6 Sol in the Bedrock console, in `us-east-1` and in every
   Region its `us.` inference profile routes to.
3. Confirm the IDs:

   ```bash
   aws bedrock list-inference-profiles --region us-east-1 \
     --query "inferenceProfileSummaries[?contains(inferenceProfileId,'openai')].[inferenceProfileId,status]"
   aws bedrock get-inference-profile --region us-east-1 \
     --inference-profile-identifier us.openai.gpt-5-6-sol-v1:0 \
     --query 'models[].modelArn'
   ```

   `MODEL_ID` must be a model ID or a **system-defined** profile ID (`us.openai.…`
   or `global.openai.…`). Never use an application-inference-profile ARN: the
   adapter would not recognize it as OpenAI and would silently drop the reasoning
   field (spec §6.3, S-210 DR-8).

4. If the confirmed profile ID, foundation-model ID, or Region list differs from
   the candidates, change all three of these in one commit. Run `npm test`, then
   repeat step 1:
   - `agentcore.json` → `MODEL_ID`;
   - `agentcore/cdk/lib/runtime-policy.ts` → `SOL_INFERENCE_PROFILE_ID`,
     `SOL_FOUNDATION_MODEL_ID`, `SOL_PROFILE_REGIONS`;
   - `agentcore/cdk/test/code-review-runtime.test.ts` → the expected ARNs.
5. Record Sol's per-token prices (§17 Q3). If you set the `PRICE_*` variables,
   add them to `agentcore.json` and to the test's expected environment.

Reversible: yes. Disable model access in the console.

### 3. IAM

The runtime role is created by the stack. Its only policy is the one in
`agentcore/cdk/lib/runtime-policy.ts`:

| Sid                  | Actions                                                                                                                                | Resource                                                                                              |
| -------------------- | -------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `EcrAuth`            | `ecr:GetAuthorizationToken`                                                                                                            | `*` (no resource-level support)                                                                       |
| `EcrPull`            | `ecr:BatchGetImage`, `GetDownloadUrlForLayer`, `BatchCheckLayerAvailability`                                                           | the stack's ECR repository                                                                            |
| `EcrImageKey`        | `kms:Decrypt`                                                                                                                          | the ECR repository's KMS key                                                                          |
| `XRay`               | `xray:PutTraceSegments`, `PutTelemetryRecords`                                                                                         | `*`                                                                                                   |
| `LogsDescribe`       | `logs:DescribeLogGroups`                                                                                                               | `*` (AWS limitation)                                                                                  |
| `RuntimeLogs`        | `logs:CreateLogGroup`, `CreateLogStream`, `DescribeLogStreams`, `PutLogEvents`, `GetLogEvents`, `FilterLogEvents`, `PutResourcePolicy` | `/aws/bedrock-agentcore/runtimes/*`                                                                   |
| `InvokeSolModel`     | `bedrock:InvokeModel`                                                                                                                  | the Sol inference profile and the Sol foundation model in each profile Region                         |
| `ReadRuntimeSecrets` | `secretsmanager:GetSecretValue`                                                                                                        | `agent-fleet/prod/SUPABASE_SERVICE_ROLE_KEY-??????`, `agent-fleet/prod/GITHUB_APP_PRIVATE_KEY-??????` |

The ECR, KMS, X-Ray, and Logs grants are what the `@aws/agentcore-cdk` construct
gives every runtime. The construct also grants `bedrock:InvokeModel`,
`InvokeModelWithResponseStream`, and `CountTokens` on `foundation-model/*` and
`inference-profile/*`, plus Configuration Bundle create, update, and delete. The
stack removes all of these. Converse needs only `InvokeModel`, and the adapter
does not stream. The DeepSeek V4 Pro grant (D-18) is in `runtime-policy.ts` but
commented out.

Check the deployed role:

```bash
ROLE=$(jq -r '.targets.default.resources.runtimes.code_review.roleArn' agentcore/.cli/deployed-state.json | sed 's#.*/##')
aws iam list-role-policies --role-name "$ROLE"            # one inline policy
aws iam list-attached-role-policies --role-name "$ROLE"   # none
aws iam get-role-policy --role-name "$ROLE" \
  --policy-name "$(aws iam list-role-policies --role-name "$ROLE" --query 'PolicyNames[0]' --output text)"
```

Expect exactly the 8 statements in the table, with no `foundation-model/*` and
no `bedrock-agentcore:*ConfigurationBundle*`.

### 4. Panel invoke policy

`infra/agentcore-invoke-policy.json` is the `invoke-runtime` inline policy on the
panel role `panel-agentcore-invoke` (issue #280 pattern). Back up the current
policy, then add two ARNs to `Statement[0].Resource`, after the security-analyst
pair. Leave everything else unchanged:

```bash
aws iam get-role-policy --role-name panel-agentcore-invoke --policy-name invoke-runtime \
  --query PolicyDocument > infra/changes/2026-10-24-code-review-runtime/backup/runtime-invoke-policy.before.json
```

```json
"arn:aws:bedrock-agentcore:us-east-1:755641879575:runtime/<codereview runtimeId>",
"arn:aws:bedrock-agentcore:us-east-1:755641879575:runtime/<codereview runtimeId>/runtime-endpoint/DEFAULT"
```

```bash
aws iam put-role-policy --role-name panel-agentcore-invoke --policy-name invoke-runtime \
  --policy-document file://infra/agentcore-invoke-policy.json
aws iam get-role-policy --role-name panel-agentcore-invoke --policy-name invoke-runtime
aws iam simulate-principal-policy \
  --policy-source-arn arn:aws:iam::755641879575:role/panel-agentcore-invoke \
  --action-names bedrock-agentcore:InvokeAgentRuntime \
  --resource-arns <runtime ARN> "<runtime ARN>/runtime-endpoint/DEFAULT" \
  --query 'EvaluationResults[].EvalDecision'     # expect ["allowed","allowed"]
```

Commit the edited `infra/agentcore-invoke-policy.json` with the change record.
Reversible: yes. Put the backup document back.

### 5. GitHub App Issues read

The agent reads linked issues (spec §7.2). The App needs **Issues: read** on the
installation. The `bug-fix` Wave A change requests read and write (its task 2.6),
which covers this.

```bash
# App settings → Permissions & events → Issues; then accept on every installation.
# Check with an installation token (never print the token):
curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $INSTALLATION_TOKEN" \
  https://api.github.com/repos/<owner>/<repo>/issues/<n>     # expect 200
```

If the grant is missing, a review still completes, with "issues unavailable
(permission)" in the comment (TC-214-13). Reversible: yes, in the App settings.

### 6. Apply the seed migration to prod (explicit confirmation)

The migration `20261022120000_seed_code_review_agent.sql` inserts the row
**disabled**, with `runtime_arn = 'pending-deploy:code-review'` (D-39). Get the
user's explicit confirmation, record it in the change record, then:

```bash
supabase db push      # applies only migrations not yet recorded on the live project
```

```sql
select slug, is_enabled, runtime_arn, max_runtime_seconds, grace_seconds
  from agents where slug = 'code-review';
-- expect: code-review | false | pending-deploy:code-review | 1800 | 120
```

Not reversible in practice once runs reference the row (`runs.agent_id … on
delete restrict`); before then, `delete from agents where slug = 'code-review';`.

### 7. Enable the row (D-39, one update)

This single update sets the ARN and enables the row. It needs a separate
explicit confirmation:

```sql
update agents
   set runtime_arn = '<runtime ARN from step 1>', is_enabled = true
 where slug = 'code-review' and runtime_arn = 'pending-deploy:code-review'
returning slug, runtime_arn, is_enabled;
```

Expect one row with the deployed ARN and `true`. Zero rows means the row is not
in the seeded state; stop and investigate. Re-applying the seed later does not
undo this, because neither column is in the `on conflict` update list.

### 8. Panel invoke verification

From https://dt-agent-fleet-panel.fly.dev, invoke `code-review` with the
`pr_number` of a scratch PR in a registered, enabled repository. Expect exactly
one review comment on the PR. The run detail shows its steps and an
`audit_report` artifact. Record the run ID in the verification log.

## Secret rotation

- **Supabase service-role key:** `aws secretsmanager put-secret-value --secret-id
agent-fleet/prod/SUPABASE_SERVICE_ROLE_KEY --secret-string file://<new-key-file>
--region us-east-1`. The secret ARN does not change, so IAM needs no edit. Each run
  reads the secret at start, so the next run uses the new key. This secret is shared
  with the sibling agents.
- **GitHub App PEM:** generate a new key in the App settings, then
  `aws secretsmanager put-secret-value --secret-id agent-fleet/prod/GITHUB_APP_PRIVATE_KEY
--secret-string file://<new.pem> --region us-east-1`. Run one invoke, then delete
  the old key in GitHub. If the secret is ever **recreated**, its ARN suffix changes:
  update `github_installations.private_key_secret_arn`. The IAM grant matches the
  name with any suffix, so it needs no change.
- **A new secret name:** edit `SECRET_NAMES` in `runtime-policy.ts`, update the test,
  and redeploy (step 1).

## Verification

- `npm test` in `agents/code-review/agentcore/cdk`: 19 tests pass.
- Step 1: `agentcore status` READY; lifecycle 900/1800 in `get-agent-runtime`.
- Step 3: the deployed role policy matches the IAM table exactly.
- Step 4: `simulate-principal-policy` returns `allowed` for both ARNs.
- Step 7: the `returning` row shows the ARN and `true`.
- Step 8: one comment on the scratch PR; the run ID is in the log below.

### Verification log

| Date | Step                                        | Model ID | Run ID / evidence | Result  | Operator |
| ---- | ------------------------------------------- | -------- | ----------------- | ------- | -------- |
| —    | 2.1 access denied before enable (TC-214-12) | —        | —                 | not run | —        |
| —    | 3 role policy check                         | —        | —                 | not run | —        |
| —    | 4 panel policy simulation (TC-214-07)       | —        | —                 | not run | —        |
| —    | 5 Issues read (TC-214-08 / TC-214-13)       | —        | —                 | not run | —        |
| —    | 6–7 seed apply + enable (TC-214-09)         | —        | —                 | not run | —        |
| —    | 8 panel invoke on a scratch PR (TC-214-11)  | —        | —                 | not run | —        |

## Rollback

In this order, fastest containment first (spec §15):

1. **Disable the webhook rule:** in `/webhooks`, turn off the `/review` rule (S-215).
   This stops new runs at once.
2. **Disable the agent row:**
   `update agents set is_enabled = false where slug = 'code-review';`
   This stops panel invokes and webhook dispatch.
3. **Redeploy the previous image:** check out the previous good commit in a
   worktree, copy `aws-targets.json`, and deploy from it:

   ```bash
   git worktree add /tmp/revert-<sha> <sha>
   cp agents/code-review/agentcore/aws-targets.json /tmp/revert-<sha>/agents/code-review/agentcore/
   (cd /tmp/revert-<sha>/agents/code-review && agentcore deploy -y)
   ```

   To remove the runtime entirely, run
   `aws cloudformation delete-stack --stack-name AgentCore-codereview-default --region us-east-1`.
   Then remove its ARNs from `infra/agentcore-invoke-policy.json` and re-put the policy.

No data needs to be migrated back. Run rows and artifacts stay as history.

## Escalation

The repository owner. Collect the run ID, the runtime version
(`get-agent-runtime`), the CloudWatch log stream for the session, and the Bedrock
request ID from the run's error message (`BEDROCK_*` errors carry it).
