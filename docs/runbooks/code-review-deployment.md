---
name: runbook-code-review-deployment
trigger: Deploying or redeploying the code-review agent, moving it to Claude Sonnet 5.5 (v1.8), changing its model, creating or rotating its Anthropic API key, setting up the `/review` PR-comment trigger, rotating its secrets, or a code-review run that fails or does nothing
owner: operator (repository owner)
last_verified: 2026-11-04 — redeploy to version 5 with `main` f4443bd (#477, D-67), ChangeId 20261103-code-review-redeploy-v15; version 4 on 2026-11-03 with d20d73a (#473, #474), ChangeId 20261103-code-review-redeploy-v14. First live deploy 2026-10-24 (ChangeId 20261024-code-review-runtime)
related: ["agents/code-review/agentcore/agentcore.json", "agents/code-review/agentcore/iam/runtime-role-policy.json", "agents/code-review/agentcore/cdk/test/code-review-runtime.test.ts", "supabase/migrations/20261125120000_seed_code_review_agent.sql", "supabase/migrations/20261103120000_seed_code_review_agent.sql", "infra/changes/20261024-code-review-runtime/", "infra/agentcore-invoke-policy.json", "docs/runbooks/webhook-rules.md", "docs/runbooks/webhook-deployment.md"]
---

# Code review agent: deployment and PR-comment trigger

How the `code-review` agent is deployed, how its model and API key are set up, and how to make a
`/review` comment on a pull request start a review. The agent reads one PR and posts one
comment on it. It never approves, merges, pushes or labels.

Blast radius: one AgentCore runtime, one IAM role, one Secrets Manager secret (the Anthropic API
key), one `agents` row and one webhook rule. Every review costs Anthropic API tokens. The rule's
author guard is what limits who can spend them.

> **v1.8 is not live yet.** The code on `main` after PR v1.7 (issues #480, #481) calls Claude
> Sonnet 5.5 on the Anthropic API for both the review and the context-selection call. The live
> runtime (version 5) is still the Bedrock build on `deepseek.v3.2`. The move is the S-218
> `infra-engineer` pass (issue #482), done in the order in [section 1a](#1a-move-to-v18-claude-sonnet-55).
> Until then, "What is deployed" shows the live state, and the v1.8 column shows the target.

## What is deployed

| Item | Live (runtime version 5) | v1.8 target (after S-218) |
| --- | --- | --- |
| AgentCore runtime | `codereview_code_review-g73KtjA3MT` (`arn:aws:bedrock-agentcore:us-east-1:755641879575:runtime/codereview_code_review-g73KtjA3MT`) | same runtime, a new version |
| CloudFormation stack | `AgentCore-codereview-default` (project `agents/code-review/agentcore/`) | same |
| Execution role | `agent-fleet-code-review-runtime`, inline policy `code-review-runtime` = the v1.0 record [`role-policy.json`](../../infra/changes/20261024-code-review-runtime/role-policy.json) | same role; inline policy = [`iam/runtime-role-policy.json`](../../agents/code-review/agentcore/iam/runtime-role-policy.json): **no `bedrock:` action** (D-74) |
| Model | `MODEL_ID=deepseek.v3.2` on Bedrock (D-66) | `MODEL_ID=claude-sonnet-5-5` on the Anthropic API (D-71, D-80). `SELECTION_MODEL_ID` is unset, so the selection call uses `MODEL_ID` too |
| Region | `AWS_REGION=us-east-1` (spec §9) | same; used for Secrets Manager only |
| Lifecycle | idle 900 s, max 1800 s; a run stops itself at 900 s (D-32) | same |
| Secrets (read on every run, by name) | `agent-fleet/prod/SUPABASE_SERVICE_ROLE_KEY`, `agent-fleet/prod/GITHUB_APP_PRIVATE_KEY` | those two, plus `agent-fleet/prod/ANTHROPIC_API_KEY` (env `ANTHROPIC_API_KEY_SECRET_ID`, D-88) |
| `agents` row params | `max_diff_lines` ≤ 10,000; `max_context_tokens` ≤ 400,000, default 150,000 | `max_diff_lines` ≤ 20,000 (D-77); `max_context_tokens` ≤ 900,000, default 900,000 (D-90) |
| `agents` row | slug `code-review`, enabled, `runtime_arn` = the runtime ARN above | same |
| Panel permission | `panel-agentcore-invoke` / `invoke-runtime` lists the runtime ARN and `…/runtime-endpoint/DEFAULT` | same |

The runtime uses a **dedicated role** (`executionRoleArn` in `agentcore.json`). The AgentCore CDK
construct then imports it read-only and attaches nothing. Without it, the construct would grant
`bedrock:InvokeModel` on every foundation model. The CDK tests fail if any `bedrock:` action ever
comes back, in the stack or in the role policy.

The API key reaches the SDK only as the client constructor's `api_key`. It is never an environment
variable, never logged, and the scrubber removes it from every comment, event and artifact (D-88).

## Preconditions

- AWS access to account `755641879575` (`us-east-1`) for the local profile and the AWS MCP server.
- Docker running (the CDK build stages the container locally; CodeBuild builds the ARM64 image).
- A local, gitignored `agents/code-review/agentcore/aws-targets.json`:
  `[{ "name": "default", "account": "755641879575", "region": "us-east-1" }]`.
- The Supabase CLI logged in to the account that owns `hegxeycmbmjfgzqpdiik`
  (`supabase projects list` must show it), and the checkout linked
  (`supabase link --project-ref hegxeycmbmjfgzqpdiik`).
- The GitHub App installation has Issues read (it has Issues write; checked 2026-10-24).
- For v1.8: access to the Anthropic Console organization that owns the API key, at **Tier 4 or
  higher** (D-78). Only the operator handles the key value.
- No other open branch or PR is changing the same agent: `gh pr list --search "code-review"` and
  `git branch -a | grep -i code-review`. On 2026-10-24 a parallel code-only PR (#445) was found
  only after deploying, and had to be reconciled.
  **Never `agentcore deploy` from a branch whose `agentcore.json` differs from what you mean to
  make live**: CloudFormation applies the whole template, including a different role or model.

## 1. Deploy or redeploy the runtime

Deploy from a checkout of `main` (or the commit being rolled out). Commit the updated
`.cli/deployed-state.json` afterwards, in a draft PR. Example: ChangeId
`20261103-code-review-redeploy-v15`.

1. Run the CDK tests. They pin the role policy, the env and the runtime config.
   `test/setup-project-root.ts` pins the AgentCore project root, so they run from the `cdk`
   directory or from the repo root:

   ```bash
   cd agents/code-review/agentcore/cdk && npm ci && npm test
   # or, from the repo root: npm --prefix agents/code-review/agentcore/cdk test
   ```

2. Preview the change. Read the diff before applying:

   ```bash
   cd agents/code-review && agentcore deploy --diff --json
   ```

   An env-var change shows as one `[~] AWS::BedrockAgentCore::Runtime` property. Anything that adds
   an `AWS::IAM::Role` for the runtime, or any `bedrock:` action, is wrong. Stop.

3. Apply it: `cd agents/code-review && agentcore deploy -y --json`
4. Commit `agents/code-review/agentcore/.cli/deployed-state.json`.

Reversible: redeploy the previous commit (see Rollback).

## 1a. Move to v1.8 (Claude Sonnet 5.5)

The order is fixed (D-89). The runtime goes first because a version 5 runtime validates params
against its own schema and rejects the new 900,000-token default. The migration goes second, and the
riel rule last. Each step is one `infra-engineer` step with its own approval, backup and revert,
recorded under `infra/changes/<ChangeId>/` (S-218, issue #482).

1. **Tier check (D-78).** In the Anthropic Console, open **Settings → Limits** for the organization
   that owns the key and read the **input tokens per minute (ITPM)** limit for `claude-sonnet-5-5`.
   Record the tier and the number in the change record.
   - ITPM ≥ 900,000: go on. One review fits in one minute's budget.
   - ITPM < 900,000: a review near the budget can be a `429` (`MODEL_RATE_LIMITED`). Go on with the
     deploy, but before step 5 write a follow-up seed migration that lowers the **default**
     `max_context_tokens` to fit the limit. The schema **maximum** stays 900,000.
2. **Create the key secret** (section 5, "Create the Anthropic API key secret"). Do this before the
   deploy: without it every run fails with `INTERNAL_ERROR` and no model call.
3. **Apply the v1.8 role policy.** Back up the live policy first. The backup is what the v1.8
   rollback restores:

   ```bash
   aws iam get-role-policy --role-name agent-fleet-code-review-runtime \
     --policy-name code-review-runtime --query PolicyDocument --output json \
     > infra/changes/<ChangeId>/backup/role-policy.before.json
   aws iam put-role-policy --role-name agent-fleet-code-review-runtime \
     --policy-name code-review-runtime \
     --policy-document file://agents/code-review/agentcore/iam/runtime-role-policy.json
   ```

   Simulate it. `secretsmanager:GetSecretValue` on the new secret's full ARN (from step 2) must
   return `allowed`, and `bedrock:InvokeModel` on `arn:aws:bedrock:us-east-1::foundation-model/deepseek.v3.2`
   must return `implicitDeny`:

   ```bash
   aws iam simulate-principal-policy \
     --policy-source-arn arn:aws:iam::755641879575:role/agent-fleet-code-review-runtime \
     --action-names secretsmanager:GetSecretValue --resource-arns <secret ARN>
   ```

   Between this step and step 4 the live version 5 runtime can no longer call Bedrock, so `/review`
   runs fail with `BEDROCK_ACCESS_DENIED`. Applying the policy after step 4 instead leaves the v1.8
   runtime unable to read its key. To avoid either window, apply the policy in two passes:
   1. Before step 4, apply `runtime-role-policy.json` **plus** the backup's `bedrock:InvokeModel`
      statement (an interim document in the change record). Both runtimes then work.
   2. After step 4 is verified, apply `runtime-role-policy.json` as is and simulate again.

   Until the second pass, a rollback (Rollback step 4) needs no IAM change. If you apply the final
   policy in one pass, turn the `/review` rule off first (Rollback step 1) and back on after step 4.
4. **Deploy the runtime** (section 1), then verify it (section "Verification"). This includes the
   v1.6 change from #478. The footer of the review comment names the answering model.
5. **Apply the seed migration, with explicit user confirmation.**
   `supabase/migrations/20261125120000_seed_code_review_agent.sql`: one idempotent upsert of the
   `agents` row's `params_schema` and `default_params`. Its header holds the verify query. Then
   check the panel's params form: `max_context_tokens` 900,000 is accepted, 900,001 is rejected.
6. **Raise the riel `/review` rule's `max_diff_lines` to 20,000** (section 4, "Check the saved rule").
   A rule that sets `max_context_tokens` under `static` keeps that value: set it to 900,000 (or the
   step 1 default), or the review keeps the old 150,000-token budget.

## 2. Model access

### Check that the account can use the model

The agent uses one Anthropic model ID (`MODEL_ID`, `claude-sonnet-5-5`) for the review and, unless
`SELECTION_MODEL_ID` is set, for the selection call. Three things must hold:

| Gate | Where you see it | Fix |
| --- | --- | --- |
| A valid key for the organization | `MODEL_ACCESS_DENIED` (401/403) on every run | create or rotate the key (section 5) |
| The organization's tier and ITPM limit (D-78) | Console → Settings → Limits; `MODEL_RATE_LIMITED` (429 after the SDK's retries) | move to a higher tier, or lower the default `max_context_tokens` |
| The model ID is available to the organization | a `404`/`400` from the API, reported as `MODEL_API_ERROR` | use an available model ID (below) |

To probe before a switch, send one tiny request from the Anthropic Console **Workbench** with the
model ID. Do not paste the key into a shell command: it would land in the shell history. If you need
a shell probe, read the key from Secrets Manager into a `0600` header file and pass the file to
`curl`, so the key is never an argument or an environment variable:

```bash
umask 077; hdr=$(mktemp)
printf 'x-api-key: %s\n' "$(aws secretsmanager get-secret-value \
  --secret-id agent-fleet/prod/ANTHROPIC_API_KEY --query SecretString --output text)" > "$hdr"
curl -sS https://api.anthropic.com/v1/messages -H @"$hdr" \
  -H 'anthropic-version: 2023-06-01' -H 'content-type: application/json' \
  -d '{"model":"claude-sonnet-5-5","max_tokens":64,"messages":[{"role":"user","content":"Say ok."}]}' \
  | jq '{model, stop_reason, usage}'
rm -f "$hdr"
```

Pass: an HTTP 200 whose `model` is the ID you sent. The agent logs only the error class, the HTTP
status and the `request-id` of a failure, never the API's message (ADR-009). The probe is where you
see the message.

### Switch the model

The agent has one model-specific module, `model_adapter.py`. A switch to another Anthropic model is
configuration only, and needs no IAM change:

1. Probe the model (above).
2. Update the tests first: `MODEL_ID` in
   `agents/code-review/agentcore/cdk/test/code-review-runtime.test.ts`. It should fail.
3. Set `MODEL_ID` (and `SELECTION_MODEL_ID`, to give the selection call its own model) in
   `agents/code-review/agentcore/agentcore.json`. Use an Anthropic model ID, never an ARN or a
   Bedrock ID.
4. Add the model's price to `MODEL_PRICES` in `agents/code-review/app/codeReview/config.py`
   (USD per million input and output tokens, D-87). A model not in the table still works, but its
   runs record no `cost_usd`, with one `warn` per run.
5. Make the tests pass, redeploy (section 1), then record the change as a decision in
   `workstream/decisions-code-review-agent.md`. A non-Anthropic provider is a code change, not a
   switch.

## 3. Permissions

- **Runtime role.** `GetSecretValue` on exactly three secrets (the Supabase key, the App PEM and the
  Anthropic API key); ECR pull on `codereview/*`; `kms:Decrypt` on the ECR repository's key, only
  through ECR; CloudWatch Logs, X-Ray, configuration-bundle reads. **No `bedrock:` action** (D-74).
  Nothing else. The source of truth is
  [`agents/code-review/agentcore/iam/runtime-role-policy.json`](../../agents/code-review/agentcore/iam/runtime-role-policy.json),
  pinned by the CDK test. The Anthropic secret is named with the `-??????` suffix wildcard, because
  its random suffix is set when it is created. That matches exactly one six-character suffix and no
  other secret name. The two older secrets are named by their full suffix.
- **Panel invoke.** `infra/agentcore-invoke-policy.json` is the live
  `panel-agentcore-invoke/invoke-runtime` document. Each runtime needs **both** its ARN and
  `…/runtime-endpoint/DEFAULT` (issue #280). Always edit the live document, not an older copy:
  `aws iam get-role-policy --role-name panel-agentcore-invoke --policy-name invoke-runtime`.

## 4. Set up the `/review` PR-comment trigger

A comment `/review` on an open PR starts a review of **that** PR. One webhook rule does this.
It needs no code, but four settings are easy to get wrong. The PR number in particular has to come
from the event, not be typed in.

### Before you start

- The repository has a GitHub endpoint in `/webhooks` whose **event allowlist includes
  `issue_comment`**, and GitHub sends that event to it. See
  [`webhook-deployment.md`](webhook-deployment.md).
- The repository is registered and **enabled** on `/repositories`.
- "Ignore events from the fleet's bot" is on (the default), so the agent's own comment never
  triggers another run.

### The rule

Open the endpoint (`/webhooks/<endpoint id>`), choose **Add rule**, and fill it in **in this order**:

1. **Name:** `/review`.
2. **Events:** tick **`issue_comment`** only.
   - A comment in the PR's *Conversation* tab is an `issue_comment`, because GitHub treats every PR
     as an issue.
   - `pull_request_review_comment` fires only for inline comments on diff lines. On its own it
     misses the normal case.
3. **Conditions.** Add all four, exactly as written (they are case-sensitive):

   | Field | Operator | Value | Why |
   | --- | --- | --- | --- |
   | `action` | `equals` | `created` | otherwise editing or deleting the comment fires again |
   | `issue.pull_request` | `exists` | — | `issue_comment` also fires on plain issues; this keeps it to PRs |
   | `comment.body` | `prefix` | `/review` | only a comment that **starts** with the command; `contains` also fires on a reply that quotes it. Note: `prefix /review` also matches `/reviewer …` (accepted, spec §7.1) |
   | `comment.author_association` | `in` | `OWNER, MEMBER, COLLABORATOR` | **cost and abuse guard**: without it anyone who can comment, including strangers on a public repo, can trigger a paid review |

4. **Agent:** `code-review`. **Repository:** *From the payload*, path `repository.full_name` (the
   default).
5. **Fill from the payload. Do this before touching the parameter grid.** Click
   **+ Add payload value**, choose **`pr_number`**, and type the path **`issue.number`**.
6. **Parameters grid:** now **clear `pr_number`** so it is empty. Leave the others at their
   defaults (v1.8: `max_diff_lines` 2000, `max_context_tokens` 900000, `max_suggestions` 5,
   `run_timeout_seconds` 900, `reasoning_effort` high, `context_folders` `docs,workstream`,
   `context_selection` llm). The riel rule raises `max_diff_lines` to 20000 (D-89).
7. **Guardrails:** keep "Disable after 3 consecutive failed starts"; leave "Notify me when a run
   succeeds" off unless you want a notification per review. **Enabled:** on.
8. **Save.** Then move the rule **above** any broader `issue_comment` rule on the same endpoint:
   the first matching rule wins.

**The ordering trap (steps 5 and 6).** `pr_number` is required. If you clear it *before* adding the
payload row, saving fails with `params must have required property 'pr_number'`. The obvious way out
is to type a number, but then **every** `/review` reviews that fixed PR, whatever PR the
comment is on. Always add the payload row first, then clear the field. With the field empty, a
delivery that lacks `issue.number` is **rejected** instead of reviewing the wrong PR.

### Inline review comments too (optional)

A rule maps each parameter from **one** path, so inline comments need a **second rule**:

- event `pull_request_review_comment`;
- conditions `action equals created`, `comment.body prefix /review`, and the same
  `author_association` guard (no `issue.pull_request` condition: this event is always on a PR);
- payload value `pr_number` ← **`pull_request.number`**;
- the endpoint's allowlist must include `pull_request_review_comment`.

### Check the saved rule

What the database should hold after v1.8 (`select event_types, conditions, params from webhook_rules where name = '/review'`):

```json
{
  "event_types": ["issue_comment"],
  "params": {
    "from_payload": { "pr_number": "issue.number" },
    "static": { "max_context_tokens": 900000, "max_diff_lines": 20000, "max_suggestions": 5,
                "reasoning_effort": "high", "run_timeout_seconds": 900 }
  }
}
```

There must be **no `pr_number` under `static`**. If there is one, the rule ignores the PR it was
called on. A rule saved before v1.8 carries `"max_context_tokens": 150000` under `static`, and that
value wins over the new default. Raise it as in section 1a step 6.

### Test it

1. On an **open** PR in the repository, comment `/review`.
2. The endpoint's delivery log shows `fired`, with a run link.
3. On the run page, check **Parameters**: `pr_number` must equal the PR you commented on.
4. Within a few minutes, the PR gets a comment headed `## Code review: **clear**` or
   `**blocking**`. Its footer names the model that answered (`answered_by_model`: a server-side
   fallback can answer with another Claude model, D-86) and links the run.

### What each outcome means

| You see | Meaning | What to do |
| --- | --- | --- |
| Delivery `ignored`: event not in endpoint's events | the endpoint does not accept `issue_comment` | add it to the endpoint's allowlist, and to the GitHub webhook's events |
| Delivery `no_match` | a condition failed | check the casing of `/review`; the comment must **start** with it; the author must be owner, member or collaborator |
| Delivery `rejected`: parameters failed the agent's schema | `pr_number` could not be filled, or a value is over a maximum | the payload row is missing or names the wrong path; the event has no `issue.number`; or the rule sets a limit the `agents` row does not allow yet (raise it only after the migration, D-89) |
| Delivery `rejected`: repository not registered/enabled | the repository is not on `/repositories`, or is disabled | register or enable it |
| Delivery `skipped` | a code-review run is already active for this repository (G1), or the fleet cap is reached | wait for it to finish and comment again; a second `/review` during a run is dropped, not queued |
| Run `succeeded` / `not_applicable`, **no comment** | the PR is closed or merged, or GitHub returned 404 | expected: the agent does not review landed code. Comment on an open PR |
| Run `succeeded` / `not_applicable`, budget comment | over `max_diff_lines`, or the expanded diff is over `max_context_tokens` | expected for very large PRs; raise the rule's limits within the schema maximum |
| Run reviews the wrong PR | `pr_number` is fixed under `static` | the ordering trap: add the payload row, clear the field, save |
| Run `failed` / `MODEL_ACCESS_DENIED`, failure comment on the PR | the Anthropic API rejected the key (401 or 403): bad, revoked or under-scoped | check the key in the Console; rotate it (section 5) |
| Run `failed` / `MODEL_RATE_LIMITED`, failure comment | a `429` outlasted the SDK's retries (D-78, D-85) | check the tier's ITPM limit (section 1a step 1); comment `/review` again later, or lower the rule's `max_context_tokens` |
| Run `failed` / `MODEL_API_ERROR`, failure comment | Anthropic 5xx or connection error after retries, an unhandled `400` (a second context-length rejection included), or a timeout before the deadline | retry; if it repeats, look up the `request-id` in `runs.error_message` and check [status.anthropic.com](https://status.anthropic.com) |
| Run `failed` / `MODEL_REFUSED`, failure comment | the model refused, and the server-side fallback refused too (D-72) | read the PR for content a model may decline to review; the run never parses refused text |
| Run `failed` / `MODEL_OUTPUT_INVALID`, failure comment | the reply was still invalid after the one repair call | retry; if it repeats on one PR, keep the run ID for the escalation |
| Run `failed` / `RUN_TIMEOUT`, failure comment | the 900 s run deadline was reached | retry; a very large PR can need a lower `max_context_tokens` |
| Run `failed` / `INTERNAL_ERROR` with no model call | among other causes, the Anthropic key secret is missing, unreadable or empty | check the secret and the role's `GetSecretValue` grant (section 3) |
| Run `failed` / `GITHUB_PERMISSION_DENIED` | the App lost access to the repository | check the installation's repository access and permissions |
| Run `failed` / `INVALID_PARAMS` | a parameter is out of range (for example a fixed limit) | fix the value in the rule |
| Context line "selection failed; rule-based context only" | the context-selection call failed (any API error, a refusal, a timeout or invalid output). The review still ran on the rule-based context (FR-33) | nothing, if it is rare; `runs.metrics.selection_reason` says which (`api_error`, `timeout`, `invalid_output`, `prompt`, `error`) |

`BEDROCK_ACCESS_DENIED` and `BEDROCK_ERROR` were the version 5 codes. A v1.8 runtime never writes
them; older runs keep them.

## 5. Rotate a secret

The runtime reads every secret from Secrets Manager **at the start of every run** (no cache), so a
rotation needs no redeploy.

### Create the Anthropic API key secret

Once, before the v1.8 deploy (section 1a step 2). First create the key in the Anthropic Console,
in the organization from the tier check, and name it after the agent (for example
`agent-fleet-code-review`) so it can be found and revoked. The key value must never be in a shell
history, a chat, a log or a committed file. Store it with either:

- **The AWS console:** Secrets Manager → **Store a new secret** → *Other type of secret* →
  **Plaintext**, paste the key, name it `agent-fleet/prod/ANTHROPIC_API_KEY`, no rotation. Or:
- **The CLI from a `0600` temp file** that you fill in an editor, never on the command line:

  ```bash
  umask 077; f=$(mktemp)
  ${EDITOR:-vi} "$f"   # paste the key and save; the runtime strips a trailing newline
  aws secretsmanager create-secret --name agent-fleet/prod/ANTHROPIC_API_KEY \
    --description "code-review agent: Anthropic API key (D-88)" \
    --secret-string "file://$f" --query ARN --output text
  rm -f "$f"
  ```

Record the returned ARN (with its suffix) in the change record. The value is never recorded.

### Rotate the Anthropic API key

1. Create a new key in the Anthropic Console. Keep the old one active.
2. Put the new value, from a `0600` temp file as above:
   `aws secretsmanager put-secret-value --secret-id agent-fleet/prod/ANTHROPIC_API_KEY --secret-string "file://$f"`, then `rm -f "$f"`.
3. Run one panel invoke (Verification step 2). It must succeed and its footer name the model.
4. Revoke the old key in the Console. A run that started before step 2 finishes with the old key,
   so wait until no code-review run is active.

A leaked key: revoke it in the Console **first** (runs fail with `MODEL_ACCESS_DENIED` until step 2),
then do steps 1–3.

### The GitHub App key and the Supabase key

- **GitHub App private key.** Generate a new key in the App settings and put it:
  `aws secretsmanager put-secret-value --secret-id agent-fleet/prod/GITHUB_APP_PRIVATE_KEY --secret-string file://<new.pem>`.
  Run one panel invoke (verification below), then delete the old key in GitHub. The secret is
  shared with the other agents, so verify one of them too.
- **Supabase service-role key.** Shared by every agent. Follow the panel and scheduler runbooks; no
  code-review step beyond a verification run.

The role grants the GitHub and Supabase secret ARNs by their full suffix. Deleting and
**recreating** a secret changes the suffix and breaks the grant. Use `put-secret-value`, never delete
and recreate. The Anthropic secret's `-??????` wildcard would match a recreated suffix, but the same
rule applies: a deleted secret has a recovery window, and its name cannot be reused during it.

## Verification

1. `aws bedrock-agentcore-control get-agent-runtime --region us-east-1 --agent-runtime-id codereview_code_review-g73KtjA3MT`
   shows `READY`, `roleArn` = `agent-fleet-code-review-runtime`, and `MODEL_ID` as in
   `agentcore.json`.
2. Panel → Invoke → **Code Review** on `llipe/security-analyst-fixture`, `pr_number` = `5` (a draft
   scratch PR with two deliberate bugs; do not merge it). Expect `succeeded` / `needs_review` and a
   comment listing two blocking findings in `app/pagination.py`. From v1.8 the footer names the
   answering model and `runs.metrics.answered_by_model` records it.
3. From v1.8: the key is absent from the run's CloudWatch log events
   (`/aws/bedrock-agentcore/runtimes/codereview_code_review-g73KtjA3MT-DEFAULT`, bounded
   `--start-time`); search for its first characters only, from a file, never by pasting the key.
4. Add a row to the log below.

### Verification log

The rows below are the version 4 and 5 (Bedrock) history. The first v1.8 row is added by S-218
(issue #482).

| Date | Run | Trigger | Model | Result |
| --- | --- | --- | --- | --- |
| 2026-10-24 | `bf95f3c6-3ba4-495e-b0c7-a8ff46b7929b` | panel, fixture PR #5 | `us.openai.gpt-6.1-sol` | `failed` / `BEDROCK_ACCESS_DENIED` with a failure comment (edge case reproduced) |
| 2026-10-24 | `40e7d207-d5a2-4311-ad18-e319ef3d892e` | panel, fixture PR #5 | `us.openai.gpt-6.1-sol` | `failed` / `BEDROCK_ACCESS_DENIED`: account not entitled to the model (agreement accepted) |
| 2026-10-24 | `db46270a-d954-4071-b0e2-a9810ef3d0f4` | panel, fixture PR #5 | `deepseek.v3.2` | `succeeded` / `needs_review`, 17.5 s, 1 call, 0 repairs, 2,643 in / 711 out tokens; both seeded bugs flagged as blocking |
| 2026-10-24 | `c36deb30-9173-41c1-891a-852954b009d2` | webhook `/code-review` (rule since renamed `/review`), `llipe/riel#630` | `deepseek.v3.2` | `succeeded` / `not_applicable`: PR already merged. `pr_number` 630 taken from `issue.number` |

## Rollback

In order of reach. Each step is reversible.

1. **Stop new runs from comments.** `/webhooks/<endpoint>` → the `/review` rule → **Enabled**
   off. This takes effect immediately.
2. **Stop all runs.** Disable the agent (panel, or
   `update agents set is_enabled = false where slug = 'code-review'`).
3. **Previous image or config.** Check out the previous commit of `agents/code-review/` and
   redeploy (section 1). AgentCore keeps earlier runtime versions; the stack update points the
   endpoint back.
4. **Roll v1.8 back to runtime version 5.** The reverse of section 1a, in this order, because a
   version 5 runtime rejects the v1.8 params:
   1. Set the riel `/review` rule back within the old bounds: `max_diff_lines` ≤ 10,000 (2,000),
      `max_context_tokens` ≤ 400,000 (150,000).
   2. Re-apply `supabase/migrations/20261103120000_seed_code_review_agent.sql`'s statement (the
      previous seed values). Its upsert restores the v1.4 `params_schema` and `default_params`;
      `runtime_arn` and `is_enabled` are untouched.
   3. Restore the Bedrock grant from the change backup:
      `aws iam put-role-policy --role-name agent-fleet-code-review-runtime --policy-name code-review-runtime --policy-document file://infra/changes/<ChangeId>/backup/role-policy.before.json`.
      It must hold `bedrock:InvokeModel` on `deepseek.v3.2` again (simulate it as in section 1a step 3).
   4. Redeploy the version 5 commit (`main` f4443bd's `agents/code-review/`) as in section 1, so
      `MODEL_ID=deepseek.v3.2` and no `ANTHROPIC_API_KEY_SECRET_ID`.
   5. Leave the Anthropic key secret in place (version 5 never reads it), or revoke the key in the
      Console and schedule the secret's deletion if v1.8 is abandoned.
5. **Remove the agent.** Run `infra/changes/20261024-code-review-runtime/rollback.sh` (it reverts
   every applied step newest-first; `--from <step>` starts partway). It deletes the stack and the
   role. The `agents` row is deleted only if no `runs` reference it. Runs block the delete
   (`on delete restrict`), and a delete would also cascade to webhook rules and schedules, so with
   run history the script leaves the row disabled.

There is no data to migrate back. Comments already posted on PRs stay.

## Escalation

- Collect: the run ID, its `error_code` and `error_message` (they carry the SDK error class, the
  HTTP status and the Anthropic `request-id`, never the API's message), the delivery row from the
  endpoint log, and `get-agent-runtime` output.
- `MODEL_ACCESS_DENIED` that the probe (section 2) reproduces: the key or its organization. Check
  the Console; open an Anthropic support request with the `request-id` if the key is valid.
- `MODEL_RATE_LIMITED` on most large reviews: the tier's ITPM limit (D-78). Request a higher tier,
  or lower the default `max_context_tokens` through a seed migration.
- Runtime will not start (`agentcore status` not READY): CloudWatch log group
  `/aws/bedrock-agentcore/runtimes/codereview_code_review-g73KtjA3MT-DEFAULT`, using a bounded
  `--start-time`.
- Change history: `infra/changes/20261024-code-review-runtime/result.md` and the later
  `infra/changes/*code-review*` records.
