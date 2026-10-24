---
name: runbook-code-review-deployment
trigger: Deploying or redeploying the code-review agent, changing its model, setting up the `/review` PR-comment trigger, rotating its secrets, or a code-review run that fails or does nothing
owner: operator (repository owner)
last_verified: 2026-10-24 — first live deploy (ChangeId 20261024-code-review-runtime). Panel run db46270a reviewed a scratch PR on DeepSeek V3.2; webhook run c36deb30 fired from a `/code-review` comment with `pr_number` taken from the payload
related: ["infra/changes/20261024-code-review-runtime/", "agents/code-review/agentcore/agentcore.json", "agents/code-review/agentcore/cdk/test/code-review-runtime.test.ts", "infra/agentcore-invoke-policy.json", "supabase/migrations/20261022120000_seed_code_review_agent.sql", "docs/runbooks/webhook-rules.md", "docs/runbooks/webhook-deployment.md"]
---

# Code review agent: deployment and PR-comment trigger

How the `code-review` agent is deployed, how to give it a model, and how to make a
`/review` comment on a pull request start a review. The agent reads one PR and posts one
comment on it. It never approves, merges, pushes or labels.

Blast radius: one AgentCore runtime, one IAM role, one `agents` row and one webhook rule. Every
review costs Bedrock tokens. The rule's author guard is what limits who can spend them.

## What is deployed

| Item | Value |
| --- | --- |
| AgentCore runtime | `codereview_code_review-g73KtjA3MT` (`arn:aws:bedrock-agentcore:us-east-1:755641879575:runtime/codereview_code_review-g73KtjA3MT`) |
| CloudFormation stack | `AgentCore-codereview-default` (project `agents/code-review/agentcore/`) |
| Execution role | `agent-fleet-code-review-runtime`, inline policy `code-review-runtime` = [`role-policy.json`](../../infra/changes/20261024-code-review-runtime/role-policy.json) |
| Model | `MODEL_ID=deepseek.v3.2`: on-demand, us-east-1 only, no marketplace agreement (D-59). `AWS_REGION=us-east-1` is set explicitly (spec §9) |
| Lifecycle | idle 900 s, max 1800 s; a run stops itself at 900 s (D-32) |
| Secrets (read on every run, by name) | `agent-fleet/prod/SUPABASE_SERVICE_ROLE_KEY`, `agent-fleet/prod/GITHUB_APP_PRIVATE_KEY` |
| `agents` row | slug `code-review`, enabled, `runtime_arn` = the runtime ARN above |
| Panel permission | `panel-agentcore-invoke` / `invoke-runtime` lists the runtime ARN and `…/runtime-endpoint/DEFAULT` |

The runtime uses a **dedicated role** (`executionRoleArn` in `agentcore.json`). The AgentCore CDK
construct then imports it read-only and attaches nothing. Without it, the construct would grant
`bedrock:InvokeModel` on every foundation model. The CDK tests fail if that grant ever comes back.

## Preconditions

- AWS access to account `755641879575` (`us-east-1`) for the local profile and the AWS MCP server.
- Docker running (the CDK build stages the container locally; CodeBuild builds the ARM64 image).
- A local, gitignored `agents/code-review/agentcore/aws-targets.json`:
  `[{ "name": "default", "account": "755641879575", "region": "us-east-1" }]`.
- The Supabase CLI logged in to the account that owns `hegxeycmbmjfgzqpdiik`
  (`supabase projects list` must show it), and the checkout linked
  (`supabase link --project-ref hegxeycmbmjfgzqpdiik`).
- The GitHub App installation has Issues read (it has Issues write; checked 2026-10-24).
- No other open branch or PR is changing the same agent: `gh pr list --state all --search "S-214"`
  and `git branch -a | grep -i code-review`. On 2026-10-24 a parallel code-only PR (#445) on
  `integration/code-review-agent-wave-b` was found only after deploying, and had to be reconciled.
  **Never `agentcore deploy` from a branch whose `agentcore.json` differs from what is live** (see
  "What is deployed"): CloudFormation applies the whole template, including a different role or model.

## 1. Deploy or redeploy the runtime

1. Run the CDK tests. They pin the role policy and the runtime config. `test/setup-project-root.ts`
   pins the AgentCore project root, so they run from the `cdk` directory or from the repo root:

   ```bash
   cd agents/code-review/agentcore/cdk && npm ci && npm test
   # or, from the repo root: npm --prefix agents/code-review/agentcore/cdk test
   ```

2. Preview the change. Read the diff before applying:

   ```bash
   cd agents/code-review && agentcore deploy --diff --json
   ```

   An env-var change shows as one `[~] AWS::BedrockAgentCore::Runtime` property. Anything that adds
   an `AWS::IAM::Role` for the runtime, or a `bedrock:` action, is wrong. Stop.

3. Apply it: `cd agents/code-review && agentcore deploy -y --json`
4. Commit `agents/code-review/agentcore/.cli/deployed-state.json`.

Reversible: redeploy the previous commit (see Rollback).

## 2. Model access

### How to tell whether the account can use a model

Bedrock has **three** separate gates. `GetFoundationModelAvailability` shows only two of them:

| Gate | Where you see it | Fix |
| --- | --- | --- |
| IAM | `SimulatePrincipalPolicy` on the role | the role policy |
| Marketplace agreement (third-party models only) | `agreementAvailability` | accept the offer (`CreateFoundationModelAgreement`) |
| Account entitlement for newly launched models | **only** the error text of a real call | ask AWS for access, or choose another model |

GPT-6.1 Sol failed on the third gate on 2026-10-24. The availability API reported `AUTHORIZED` and
`AVAILABLE`, and every call still failed with "openai.gpt-6.1-sol is not available for this
account". The agent reports any of the three as `BEDROCK_ACCESS_DENIED` and, by design, does not
log the AWS message (ADR-009). So **probe before you switch**: send one tiny call as an admin
principal, with the same forced tool the agent uses:

```bash
aws bedrock-runtime converse --region us-east-1 --model-id <model-or-profile-id> \
  --messages '[{"role":"user","content":[{"text":"Submit verdict clear."}]}]' \
  --inference-config maxTokens=1024 \
  --tool-config '{"tools":[{"toolSpec":{"name":"submit_review","inputSchema":{"json":{"type":"object","properties":{"verdict":{"type":"string","enum":["clear","blocking"]}},"required":["verdict"]}}}}],"toolChoice":{"tool":{"name":"submit_review"}}}'
```

Pass: `stopReason` is `tool_use` with `{"verdict":"clear"}`. Give it at least 1024 tokens. Some
models (DeepSeek, Kimi) write text or reasoning before the tool call, and at 64 tokens they look
broken when they are not. A `ValidationException` about `toolChoice` means the agent would fall
back to plain JSON (D-34): usable, but less reliable.

Models probed on 2026-10-24, all passing: `deepseek.v3.2` (in use), `us.moonshotai.kimi-k3`,
`mistral.devstral-2-123b`. Changing to a non-DeepSeek provider needs a data-policy decision first
(D-18 approves DeepSeek only).

### Switch the model

The agent has no model-specific code beyond the reasoning field, which it sends only for
`openai.gpt-*` IDs. A switch is configuration only:

1. Probe the model (above).
2. Update the tests first: `MODEL_ID` and `MODEL_ARNS` in
   `agents/code-review/agentcore/cdk/test/code-review-runtime.test.ts`. They should fail.
3. Set `MODEL_ID` in `agents/code-review/agentcore/agentcore.json`. Use a model ID or a
   *system-defined* inference-profile ID (`us.…`), never an ARN. Then change the Bedrock statement
   in the role policy:
   - an on-demand model needs one ARN, `arn:aws:bedrock:us-east-1::foundation-model/<id>`;
   - a cross-Region profile needs the profile ARN plus the foundation-model ARN in every Region the
     profile lists.
4. Make the tests pass, then apply the policy:
   `aws iam put-role-policy --role-name agent-fleet-code-review-runtime --policy-name code-review-runtime --policy-document file://<policy.json>`
5. Simulate it: `aws iam simulate-principal-policy --policy-source-arn arn:aws:iam::755641879575:role/agent-fleet-code-review-runtime --action-names bedrock:InvokeModel --resource-arns <arn>` should return `allowed`; the previous model should return `implicitDeny`.
6. Redeploy (section 1), then record the change as a decision in `workstream/decisions-code-review-agent.md`.

## 3. Permissions

- **Runtime role.** Bedrock `InvokeModel` on exactly the current model; `GetSecretValue` on exactly
  the two secrets; ECR pull on `codereview/*`; `kms:Decrypt` on the ECR repository's key, only
  through ECR; CloudWatch Logs, X-Ray, configuration-bundle reads. Nothing else. The source of
  truth is `role-policy.json` in the ChangeId folder, and the CDK test pins it.
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
6. **Parameters grid:** now **clear `pr_number`** so it is empty. Leave the other five at their
   defaults (`max_diff_lines` 2000, `max_context_tokens` 150000, `max_suggestions` 5,
   `run_timeout_seconds` 900, `reasoning_effort` high).
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

What the database should hold (`select event_types, conditions, params from webhook_rules where name = '/review'`):

```json
{
  "event_types": ["issue_comment"],
  "params": {
    "from_payload": { "pr_number": "issue.number" },
    "static": { "max_context_tokens": 150000, "max_diff_lines": 2000, "max_suggestions": 5,
                "reasoning_effort": "high", "run_timeout_seconds": 900 }
  }
}
```

There must be **no `pr_number` under `static`**. If there is one, the rule ignores the PR it was
called on.

### Test it

1. On an **open** PR in the repository, comment `/review`.
2. The endpoint's delivery log shows `fired`, with a run link.
3. On the run page, check **Parameters**: `pr_number` must equal the PR you commented on.
4. Within about a minute (p95 to be measured in S-215), the PR gets a comment headed
   `## Code review: **clear**` or `**blocking**`. Its footer names the model and links the run.

### What each outcome means

| You see | Meaning | What to do |
| --- | --- | --- |
| Delivery `ignored`: event not in endpoint's events | the endpoint does not accept `issue_comment` | add it to the endpoint's allowlist, and to the GitHub webhook's events |
| Delivery `no_match` | a condition failed | check the casing of `/review`; the comment must **start** with it; the author must be owner, member or collaborator |
| Delivery `rejected`: parameters failed the agent's schema | `pr_number` could not be filled | the payload row is missing or names the wrong path; the event has no `issue.number` |
| Delivery `rejected`: repository not registered/enabled | the repository is not on `/repositories`, or is disabled | register or enable it |
| Delivery `skipped` | a code-review run is already active for this repository (G1), or the fleet cap is reached | wait for it to finish and comment again; a second `/review` during a run is dropped, not queued |
| Run `succeeded` / `not_applicable`, **no comment** | the PR is closed or merged, or GitHub returned 404 | expected: the agent does not review landed code. Comment on an open PR |
| Run reviews the wrong PR | `pr_number` is fixed under `static` | the ordering trap: add the payload row, clear the field, save |
| Run `failed` / `BEDROCK_ACCESS_DENIED`, failure comment on the PR | the model is unusable for the account (section 2) | probe the model as an admin; fix IAM, the agreement, or switch models |
| Run `failed` / `GITHUB_PERMISSION_DENIED` | the App lost access to the repository | check the installation's repository access and permissions |
| Run `failed` / `INVALID_PARAMS` | a parameter is out of range (for example a fixed limit) | fix the value in the rule |

## 5. Rotate a secret

The runtime reads both secrets from Secrets Manager **at the start of every run** (no cache), so a
rotation needs no redeploy.

- **GitHub App private key.** Generate a new key in the App settings and put it:
  `aws secretsmanager put-secret-value --secret-id agent-fleet/prod/GITHUB_APP_PRIVATE_KEY --secret-string file://<new.pem>`.
  Run one panel invoke (verification below), then delete the old key in GitHub. The secret is
  shared with the other agents, so verify one of them too.
- **Supabase service-role key.** Shared by every agent. Follow the panel and scheduler runbooks; no
  code-review step beyond a verification run.

The role grants these two secret ARNs by their full suffix. Deleting and **recreating** a secret
changes the suffix and breaks the grant. Use `put-secret-value`, never delete and recreate.

## Verification

1. `aws bedrock-agentcore-control get-agent-runtime --region us-east-1 --agent-runtime-id codereview_code_review-g73KtjA3MT`
   shows `READY`, `roleArn` = `agent-fleet-code-review-runtime`, and `MODEL_ID` as in
   `agentcore.json`.
2. Panel → Invoke → **Code Review** on `llipe/security-analyst-fixture`, `pr_number` = `5` (a draft
   scratch PR with two deliberate bugs; do not merge it). Expect `succeeded` / `needs_review` and a
   comment listing two blocking findings in `app/pagination.py`.
3. Add a row to the log below.

### Verification log

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
4. **Remove the agent.** Run `infra/changes/20261024-code-review-runtime/rollback.sh` (it reverts
   every applied step newest-first; `--from <step>` starts partway). It deletes the stack and the
   role. The `agents` row is deleted only if no `runs` reference it. Runs block the delete
   (`on delete restrict`), and a delete would also cascade to webhook rules and schedules, so with
   run history the script leaves the row disabled.

There is no data to migrate back. Comments already posted on PRs stay.

## Escalation

- Collect: the run ID, its `error_code` and `error_message` (they carry the AWS request ID), the
  delivery row from the endpoint log, and `get-agent-runtime` output.
- `BEDROCK_ACCESS_DENIED` that the admin probe reproduces: an AWS Support case for model access,
  with the probe's error text and request ID.
- Runtime will not start (`agentcore status` not READY): CloudWatch log group
  `/aws/bedrock-agentcore/runtimes/codereview_code_review-g73KtjA3MT-DEFAULT`, using a bounded
  `--start-time`.
- Change history: `infra/changes/20261024-code-review-runtime/result.md`.
