# Fidelity Report — S-214 (#416) Runtime infrastructure, IAM, and runbook (code part)

**Fidelity: High** · **Highest drift impact: Minor** · 9 drift items (0 Critical, 0 Major, 9 Minor), all non-blocking
Scope: story S-214 / issue #416 · branch `story/S-214-runtime-infra` @ `c968338` · PR #445 into `integration/code-review-agent-wave-b` · delivered scope `git diff origin/integration/code-review-agent-wave-b...HEAD` (27 files, +7521/−4, 7 commits) · first story of Wave B
Audit status: **complete for the code part**, not blocked. AC1, AC2 and AC7 are delivered and tested. AC3–AC6 and AC8 are deploy steps that need approval, so they are out of scope here. For each one, this audit judges whether the code, runbook and change record make it executable and safe. **No missing IAM grant was found** that would stop the runtime from deploying or running (Judgment 1).

## Changelog

| Version | Date       | Change                                                  | Author   |
| ------- | ---------- | ------------------------------------------------------- | -------- |
| 1.0     | 2026-10-24 | Initial Audit Mode report for the S-214 code part, #416. | verifier |

## 1. Human-readable summary

This change prepares the review agent to go live, but it does not switch it on. It adds three things:

1. **A definition of the agent's server.** It sets how long a review may run, where the agent reads its settings, and which AI model it uses. The model name is a best guess until someone checks it in the AWS account.
2. **A narrow permission set for that server.** Out of the box, the deployment tooling would let the agent call any AI model and change some AWS settings. This change removes that. The agent can now call only the one approved model and read only its two passwords. It keeps the basic permissions every agent needs to start and write logs. An automated test fails if these permissions ever widen.
3. **A step-by-step operator guide and an empty change record.** These cover deploying, checking permissions, letting the control panel call the agent, switching on the database entry, rotating passwords, and undoing each step. Each live step still needs a person's approval. The production database steps need a separate, recorded confirmation.

What is still missing is the live work: deploying, enabling the model, updating the panel's permission, applying the database entry, and running one real review. All of this is planned and documented but not done. The smaller gaps are listed in section 3. None of them blocks this change.

## 2. Per-AC results

| AC-ID | Description | Codebase evidence | Workstream evidence | Test evidence | Result |
| ----- | ----------- | ----------------- | ------------------- | ------------- | ------ |
| AC1 | `agentcore.json` + CDK define runtime `code_review`: Container, ARM64, `PUBLIC`, idle 900, `maxLifetime` 1800, env per spec §9 | `agentcore.json`: Container, `main.py`, `app/codeReview/`, `PUBLIC`, HTTP, lifecycle 900/1800. Env: `SUPABASE_URL`, `SUPABASE_KEY_SECRET_ID`, `MODEL_ID=us.openai.gpt-5-6-sol-v1:0` (candidate, not an ARN), `PANEL_BASE_URL`, `AWS_REGION`, `HEARTBEAT_INTERVAL=120`, `IDLE_SESSION_TIMEOUT=900`, `MAX_LIFETIME=1800`. `PRICE_*` is unset (optional, §17 Q3). `cdk synth` (placeholder account 123456789012, no AWS call) produces stack `AgentCore-codereview-default`. The `AWS::BedrockAgentCore::Runtime` has those exact env vars and lifecycle, `NetworkMode: PUBLIC`, and a container artifact. CodeBuild is `ARM_CONTAINER` (`amazonlinux-aarch64-standard:3.0`). All four `config._REQUIRED_VARS` are set, and `load_settings` accepts the env. Clocks: 900 ≥ `RUN_TIMEOUT_MAX` 900; 120 ≤ 900/2; `maxLifetime` 1800 = seed `max_runtime_seconds`; reaper 1800 + 120. | Spec §9 env list, §8.9 clocks, §5.1 seed equality, S-213 §5 Wave B handoff: every item is met. Mirrors the sibling's `agentcore/` layout. `bin/cdk.ts`, `cdk.json` and `package.json` match the sibling. | TC-214-01 (`code-review-runtime.test.ts`: spec shape, lifecycle, network/protocol/artifact, ARM64, exact env). TC-214-02 (no secret material in `agentcore.json`, `bin/`, `lib/`, Dockerfile). TC-214-05 (`test_seed_contract.py`: lifecycle = config clocks; required vars present; `MODEL_ID` not an ARN; `load_settings` passes; the previously skipped `maxLifetime` = seed test now runs). | Pass |
| AC2 | Runtime role: `bedrock:InvokeModel` only on Sol model + profile (DeepSeek commented out); Secrets Manager read on PEM + Supabase key; no other actions (§7.2) | `lib/runtime-policy.ts` `restrictRuntimeRole` overrides the construct's `DefaultPolicy` statement list. Synthesized policy, 8 statements: `EcrAuth` (`ecr:GetAuthorizationToken` on `*`), `EcrPull` (stack repository), `EcrImageKey` (`kms:Decrypt` on the repository's own key), `XRay`, `LogsDescribe`, `RuntimeLogs` (`/aws/bedrock-agentcore/runtimes/*`), `InvokeSolModel` (`bedrock:InvokeModel` on `…:us-east-1:<acct>:inference-profile/us.openai.gpt-5-6-sol-v1:0` and `…::foundation-model/openai.gpt-5-6-sol-v1:0` in us-east-1/us-east-2/us-west-2), `ReadRuntimeSecrets` (`GetSecretValue` on the two `agent-fleet/prod/…-??????` names). The construct's `foundation-model/*`, `inference-profile/*`, `InvokeModelWithResponseStream`, `CountTokens` and Configuration Bundle CRUD are gone. The app calls only `bedrock-runtime.converse` and `secretsmanager.get_secret_value` (grep: no `converse_stream`, `count_tokens` or other client). The override throws at synth if the construct tree changes shape. | Spec §7.2. Business rule "no wildcard Bedrock model ARN". D-18 (DeepSeek block commented in `runtime-policy.ts`). The platform statements (ECR/KMS/X-Ray/Logs) are not in §7.2 (DR-1). | TC-214-03 (exactly one policy, exact statement set, unconditional Allow, no managed or inline role policies). TC-214-04 (no `*` Bedrock resource, only `InvokeModel`, no Anthropic/DeepSeek ARN, no `bedrock-agentcore:`/`iam`/`s3`/`sts`, no action ending in `*`). The PR reports that removing `restrictRuntimeRole` fails 3 tests. `npm ci && npm test`: **19/19 pass**. `tsc --noEmit` and prettier pass. | Pass (DR-1, DR-2) |
| AC3 | Sol model access enabled; `MODEL_ID` = confirmed ID | Out of scope (deploy). `MODEL_ID` and the three `SOL_*` constants are marked **CANDIDATE** in code. The test pins literal ARNs, so changing the ID forces an IAM review. | Change-record Step 2 and runbook step 2: confirm with `list-inference-profiles` / `get-inference-profile`; if anything differs, edit 3 files in one commit and redeploy. TC-214-06/12 are mapped. | Live (TC-214-06, TC-214-12) | Deferred — executable (DR-6, DR-7) |
| AC4 | Panel `invoke-runtime` lists the runtime ARN + `runtime-endpoint/DEFAULT` | Out of scope. `infra/agentcore-invoke-policy.json` is correctly left unedited, because the ARN does not exist yet. | Runbook step 4 gives a backup command, the exact two ARNs to append (issue #280 pattern), `put-role-policy`, `get-role-policy`, and `simulate-principal-policy` (expect two `allowed`). Revert puts the backup back. | Live (TC-214-07) | Deferred — executable |
| AC5 | GitHub App Issues read | Out of scope. With the grant missing, the agent degrades with a note (spec §16 R6). | Runbook step 5 / change-record Step 4: check, grant if missing, curl 200 check; TC-214-08/13 mapped. | Live (TC-214-08, TC-214-13) | Deferred — executable |
| AC6 | Seed migration to prod with explicit confirmation; one update sets `runtime_arn` + `is_enabled = true` (D-39) | Out of scope. Migration `20261022120000_seed_code_review_agent.sql` inserts the row disabled with the `pending-deploy:code-review` placeholder. `is_enabled`, `runtime_arn` and `runtime_qualifier` are not in the `on conflict` update list. | Runbook steps 6–7 / change-record Steps 5–6: each needs a **separately recorded explicit confirmation**. D-39 is one statement, `update agents set runtime_arn = '<ARN>', is_enabled = true where slug = 'code-review' and runtime_arn = 'pending-deploy:code-review' returning …`. It is guarded (zero rows means stop). Revert: disable, or delete if no runs exist. | Live (TC-214-09); seed half pinned by `test_seed_contract.py` | Deferred — executable (DR-7) |
| AC7 | Runbook covers deploy, model access, IAM, rotation, rollback (rule → agent → previous image), verification log; indexed | `docs/runbooks/code-review-deployment.md`: frontmatter, preconditions, a configuration table, 8 steps (deploy with the version-flip check; model access; IAM table plus a `get-role-policy` check; panel policy; Issues read; prod seed; D-39 enable; panel invoke), secret rotation, verification checklist, verification-log table, rollback in spec §15 order, escalation. Indexed in `docs/runbooks/README.md`. | Spec §15 rollback order matches. FR-49a: the runbook ships in the same PR. The S-213 §5 "check CloudWatch for startup failures" handoff is in step 1. | TC-214-10 (manual review: content complete). `checkDocsStructure` reports 2 findings on the new file (DR-5). | Pass (DR-5) |
| AC8 | Panel manual invoke on a scratch PR produces a comment | Out of scope. | Runbook step 8 / change-record Step 7: one comment, run detail shows steps + `audit_report`, run ID into the log. | Live (TC-214-11) | Deferred — executable |

### Judgment 1 — Least privilege and missing grants (key risk)

**Result: no missing grant.** The restricted role keeps every construct grant the runtime needs to start:

- ECR auth and pull, plus `kms:Decrypt` on the image key;
- X-Ray;
- CloudWatch Logs.

It drops only grants the code never uses.

The four candidate grants were each checked against the construct source (`@aws/agentcore-cdk` 0.1.0-alpha.49, `AgentCoreRuntime.js`):

| Candidate | Finding |
| --------- | ------- |
| `ecr:GetAuthorizationToken` | Granted (`EcrAuth`, `*`, which the API requires). |
| Logs | Granted: `logs:DescribeLogGroups` on `*`, plus create, put and read on `/aws/bedrock-agentcore/runtimes/*`. Same as the construct. |
| X-Ray | Granted: `PutTraceSegments`, `PutTelemetryRecords`. The app ships no OTel distro, so these are kept only for construct parity. |
| Workload identity, `bedrock-agentcore:GetWorkloadAccessToken*` | **Not needed.** The construct adds these only in `grantCredentialAccess()`, which runs only when `agentcore.json` has `credentials`; here `credentials: []`. The sibling `security-analyst` is deployed live from the same construct version (alpha.49, `deployed-state.json`) with the same `credentials: []`, so its construct-managed role has no workload-identity grant and it runs. The code never calls `@requires_access_token` or any identity API. |

Comparison with the sibling: the sibling's role is the construct default. It has wildcard Bedrock, Configuration Bundle CRUD, and no `agent-fleet/prod/*` secrets grant from CDK. The siblings' runbooks grant secrets out of band (`issue-77` step 7.6, `agent-fleet/prod/*`). The live sibling role was not inspected, because no AWS call was allowed. The `code_review` role is a strict subset of the sibling's CDK grants, plus the two secret ARNs in CDK, which is an improvement.

Other checks:

- **`-??????` suffix:** correct. Secrets Manager appends exactly six characters. The live PEM ARN in `supabase/seed.sql` ends `-t4sXT2`, so the pattern matches it. The pattern also covers a `GetSecretValue` by name (`SUPABASE_KEY_SECRET_ID`). The secrets use the default `aws/secretsmanager` key (runbook `issue-77`), so no extra `kms:Decrypt` is needed.
- **KMS:** scoped to the stack's own ECR key (`Fn::GetAtt` of `…EncryptionKey`). The key policy grants the account root, so the IAM grant is effective.
- **Cross-Region profile:** `InvokeModel` covers the profile ARN in us-east-1 and the foundation model in each destination Region. That is the documented requirement. The Region list is a candidate (DR-6).
- **Residual deploy risk, not a missing grant (DR-6):** some third-party Bedrock models are enabled on first invocation through an AWS Marketplace subscription. The invoking principal then needs `aws-marketplace:Subscribe`/`ViewSubscriptions`. The runtime role deliberately lacks these. Enablement must be done by an admin principal **before** the runtime invokes. The runbook's "enable in the console" wording should say so.

### Judgment 2 — `agentcore.json` against `config.py`

- **Required vars:** all four are set. `MODEL_ID` is a system-profile ID, not an ARN, and is recognized as OpenAI by the D-35 rule.
- **Clock invariant:** holds; see AC1.
- **`PYTHON_3_14`:** inert for a Container build. `runtimeVersion` is read only on the CodeZip path (`AgentCoreRuntime.js:226`), and the synthesized template has no runtime version. Production runs the Dockerfile's `python:3.13-slim`. CI tests both 3.13 and 3.14, so there is no gap. The sibling has the same setting (DR-4).
- **`AWS_REGION`:** listed in spec §9 and matches the target Region, so the value is harmless. It is redundant, because the platform sets it. If AgentCore treats the name as reserved, CreateAgentRuntime would reject it. No evidence either way; the PR body already says to drop it if rejected (DR-4).

### Judgment 3 — Tests

The CDK tests are meaningful:

- They read the real `agentcore.json` through the CLI's `ConfigIO`, so a schema-invalid file fails.
- They pin the exact statement set with literal ARNs.
- They normalize `Fn::GetAtt` to typed placeholders.
- They assert unconditional Allow.
- They have a negative TC-214-04 class.
- They were written red first (`b2bca61`).

Limits:

- They pin only the current configuration (DR-3).
- No CI job runs them (DR-8).

The seed-contract additions are correct. Because `config` reads the test process's environment, the clock comparisons are against the defaults. That is the intended contract.

### Judgment 4 — Runbook and change record

- **Coverage:** complete for AC3–AC8.
- **D-39:** correct. It is one guarded update, and the seed's `on conflict` list cannot undo it.
- **Rollback:** given per step and in a rollback section (rule → row → previous image or delete-stack, then remove the policy ARNs).
- **Prod apply:** both prod writes require a separately recorded explicit confirmation.
- **`rollback.sh`:** a skeleton that exits 1. That is acceptable before deploy, and Step 8 fills it.
- **Gaps:** the step ordering for TC-214-12, and `supabase db push` having no dry-run (DR-7).

### Judgment 5 — Audit advisory

`npm audit` in `agents/code-review/agentcore/cdk` shows **1 high**: `brace-expansion` 5.0.6, bundled inside `aws-cdk-lib` 2.261.0. `npm audit fix --dry-run` does not clear it, so only an `aws-cdk-lib` bump fixes it. It is used at build/synth time only and is not in the runtime image. The sibling CDK package has the same bundled version.

**No CI step audits it:**

- `ci.yml` runs `make audit` (pip-audit) per Python agent.
- The panel's `pnpm --filter panel run audit` (`panel/scripts/audit.mjs`, `pnpm audit --prod`) covers the panel only.
- The CDK package is not in `pnpm-workspace.yaml` and uses an npm `package-lock.json`.

See DR-8.

## 3. Drift catalog

Every item below is **non-blocking** to PR #445 readiness and to issue #416 completion. Each one routes to `product-engineer`'s `activity-drift-reconciliation`.

| ID   | Description | Impact | Intent | Evidence |
| ---- | ----------- | ------ | ------ | -------- |
| DR-1 | **Platform grants not stated in spec §7.2 or TC-214-03.** §7.2 says the role can do Bedrock on Sol and Secrets read, and "cannot: any write to AWS resources". TC-214-03 expects only {`InvokeModel`, `GetSecretValue`} "plus CloudWatch Logs if the sibling pattern requires it". The delivered role also carries ECR auth and pull, `kms:Decrypt` on the image key, X-Ray writes, and Logs writes, including `logs:PutResourcePolicy`, `GetLogEvents` and `FilterLogEvents`. All come from the construct, which needs them to pull the image and emit telemetry. The log-read and `PutResourcePolicy` actions are not obviously needed by the runtime and could be tightened. | Minor | Intended | `runtime-policy.ts` `platformStatements`; synth template; spec §7.2; test plan TC-214-03 |
| DR-2 | **The override silently drops future grants.** `addPropertyOverride('PolicyDocument.Statement', …)` replaces the whole list at render time. Any statement added later to the same role is discarded without error, so the runtime would fail at run time rather than at synth. Examples: `grantCredentialAccess` if `credentials` are configured, payments `sts:AssumeRole`, or `wire-connections`. The guard only catches a changed tree shape. The exact-set test would still pass, because the extra grants never appear. Latent: today's config adds nothing. | Minor | Unintended | `runtime-policy.ts` `restrictRuntimeRole`; `cdk-stack.ts` payments block; `AgentCoreRuntime.grantCredentialAccess` |
| DR-3 | **A re-vended stack loses the restriction.** If an `agentcore` CLI upgrade regenerates `lib/cdk-stack.ts`, the `restrictRuntimeRole` call is lost and the wildcard Bedrock grant returns. Mitigations: the runbook's step-3 IAM check, and the CDK test, which fails if the call is missing but only when run (DR-8). | Minor | Intended | runbook step 1/3; PR body "Generated stack" |
| DR-4 | **Inert or possibly rejected config values.** `runtimeVersion: PYTHON_3_14` has no effect on a Container build, which runs the Dockerfile's 3.13. It mirrors the sibling and is misleading, not harmful. `AWS_REGION` is set explicitly (spec §9). It is redundant with the platform and may be rejected if AgentCore reserves the name. | Minor | Undetermined | `agentcore.json`; `AgentCoreRuntime.js:226`; synth (no runtime version); Dockerfile |
| DR-5 | **The docs-structure check flags the new runbook.** `checkDocsStructure` (dev-tasks `core/checks`, run against this repository) reports `runbook-filename` (`code-review-deployment.md` does not match `runbook-<verb>-<object>.md`) and `runbook-frontmatter` (`last_verified: never (not yet deployed)` is not a date). TC-214-10 says "`checkDocsStructure` passes (`lint`)". The check is not wired into this repository's `lint`, and 31 pre-existing findings (other runbooks, the index) show the local convention differs. The new file follows the local convention. No staleness findings. Vocabulary conformance (`checkExportedIdentifiers` over the PR's added lines against `docs/domain/ubiquitous-language.md`): **0 hits**. | Minor | Intended | `checkDocsStructure` output; test plan TC-214-10 |
| DR-6 | **Model-access step wording and candidate IDs.** The Sol profile ID, foundation-model ID and profile Regions are unconfirmed candidates (spec §17 Q1). The process to change them is documented and test-enforced. The runbook says "enable in the Bedrock console". If Sol is enabled through an AWS Marketplace subscription on first invoke, an admin principal must do that. The runtime role cannot, because it deliberately has no `aws-marketplace:*`. The runbook does not say this. | Minor | Undetermined | `runtime-policy.ts` CANDIDATE constants; runbook step 2; change-record Step 2 |
| DR-7 | **Change-record ordering and the prod push scope.** (a) Change-record Step 2 lists TC-214-12, an invoke before access is enabled, as its verification. That invoke needs the panel policy, the seed and the enable, which are Steps 3, 5 and 6. The runbook notes this ordering ("run it right after step 7"); the plan does not. (b) `supabase db push` applies **every** unrecorded migration, not only `20261022120000_seed_code_review_agent.sql`. Neither document shows the pending list (`supabase migration list` or `db push --dry-run`) before the user confirms. | Minor | Unintended | `infra/changes/20261024-code-review-runtime/plan.md` Steps 2 and 5; runbook steps 2.1 and 6 |
| DR-8 | **CDK suite and audit not in CI.** No CI job runs the CDK jest suite, so the least-privilege pin runs only as a runbook precondition. No CI job audits the CDK package's npm lockfile, where the bundled `brace-expansion` high sits (Judgment 5). Both match the security-analyst package, and the PR body records both as follow-ups. | Minor | Intended | `.github/workflows/ci.yml`; `pnpm-workspace.yaml`; `npm audit` |
| DR-9 | **Secret coupling to one PEM name.** The PEM grant covers only `agent-fleet/prod/GITHUB_APP_PRIVATE_KEY-??????`. The siblings used `agent-fleet/prod/*`. Today the only `github_installations` row points at it. A new installation whose `private_key_secret_arn` names a different secret fails with `PEM_UNAVAILABLE` until `SECRET_NAMES` is edited. The runbook's rotation section mentions "a new secret name", but not this trigger. | Minor | Intended | `runtime-policy.ts` `SECRET_NAMES`; `supabase/seed.sql`; runbook "Secret rotation" |

Runbook-coverage finding (FR-49b): **not raised.** The PR adds a runbook for its procedure.
Roadmap-mismatch finding: **not raised.** S-214 does not complete Wave B (S-215 remains), and the Wave B row `Not started` refers to unmerged work.

## 4. Edge-case and randomized test outcomes

| Ref | Expectation (test plan) | Outcome |
| --- | ----------------------- | ------- |
| TC-214-01 | Runtime shape, ARM64, PUBLIC, 900/1800, env | Pass (CDK test and synth). |
| TC-214-02 | No secret material in config, CDK, or Dockerfile | Pass. |
| TC-214-03 | Exact role policy | Pass, with 6 platform statements beyond the plan's wording (DR-1). |
| TC-214-04 | No wildcard Bedrock, no writes, no Anthropic or DeepSeek | Pass, except that the Logs and X-Ray telemetry writes are present (DR-1). |
| TC-214-05 | `maxLifetime` = seed; schema max ≤ idle | Pass (`test_seed_contract.py`; the previously skipped test now runs). |
| TC-214-06/07/08/09/11/12/13 | Live | Not run (deploy-gated). The steps are executable per the runbook and change record (DR-6, DR-7). |
| TC-214-10 | Runbook content + index + `checkDocsStructure` | Content and index pass; `checkDocsStructure` reports 2 findings (DR-5). |
| Randomized | — | None defined for S-214. |

**Gates run by this audit:**

- `make validate` in `agents/code-review/app/codeReview`: **all gates passed**. 3167 passed, coverage 99.64% (≥ 90%), pip-audit clean.
- CDK: `npm ci && npm test`: 19/19. `tsc --noEmit`: OK. prettier: OK. `cdk synth` with a placeholder `aws-targets.json`: OK. The placeholder was deleted afterwards.
- `npm audit`: 1 high (`brace-expansion`, bundled).
- PR #445 CI at `c968338`: all 7 checks green (6 Python matrix, 1 panel).

**Documentation structure:** see DR-5. **Vocabulary conformance:** 0 hits. Advisory only; it does not block.

## 5. Recommendations

| ID | Next step | Owner |
| -- | --------- | ----- |
| DR-1 | Write back spec §7.2 and TC-214-03/04 to name the platform statements (ECR pull, image-key decrypt, X-Ray, runtime log group) as allowed telemetry/bootstrap grants. Optional tightening: drop `logs:GetLogEvents`, `logs:FilterLogEvents` and `logs:PutResourcePolicy` after one live run confirms they are unused. | `product-engineer` (spec), `developer` (optional) |
| DR-2 | Change `restrictRuntimeRole` so that unexpected grants fail at synth. Either assert that the construct's statement count matches a known list before overriding, or filter out the unwanted statements instead of replacing the list. Alternatively, record the limit in `runtime-policy.ts` and the runbook. | `developer` |
| DR-3 | No action beyond the existing runbook check. Keep it in the deploy checklist. | no action needed |
| DR-4 | Confirm at deploy step 1 whether `AWS_REGION` is accepted, and record the result in the verification log. Optionally note in `agentcore.json`'s runbook table that `runtimeVersion` is inert for Container builds. | `infra-engineer` at deploy |
| DR-5 | Decide whether this repository adopts the dev-tasks runbook naming and `last_verified` date rules. If it does, rename all runbooks in one docs PR. If not, amend TC-214-10 to drop the `checkDocsStructure` clause. | `product-engineer`, `technical-writer` |
| DR-6 | In runbook step 2, say that model enablement, including any Marketplace subscription, is done by an admin principal before the runtime invokes. Record the confirmed IDs and Regions in the verification log. | `developer` (runbook), `infra-engineer` |
| DR-7 | In `plan.md`, move TC-214-12 to after Step 6, or reorder so it matches the runbook note. In runbook step 6 and plan Step 5, add `supabase migration list --linked` or `supabase db push --dry-run`, and show the pending list in the confirmation request. | `developer` |
| DR-8 | Open a follow-up for a CI job that runs the agent CDK jest suites and a high-severity npm audit of the CDK lockfiles. Bump `aws-cdk-lib` across the CDK packages to clear the bundled `brace-expansion`. | `housekeeping` (CI wiring), `developer` |
| DR-9 | Add one line to the runbook: a new `github_installations` row with a different PEM secret name needs a `SECRET_NAMES` change and a redeploy before it can be used. | `developer` |
