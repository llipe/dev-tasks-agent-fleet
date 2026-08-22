# Pending Deployments — Agent Control Plane v1

Deployment steps deferred during implementation, plus defects found during first-run
verification. Each action requires explicit confirmation before executing.

**Last verified against live AWS:** account `755641879575`, region `us-east-1`.

> **Status update — issue #56 / PR #57.** Defects **D1, D2 and D3 are fixed in code** on
> branch `issue/56-deployment-correctness-fixes` and are **pending deployment**. Nothing in
> the live account has changed since the verification below: the runtime role still lacks
> its data-plane permissions until `agentcore deploy` runs, so a run today still fails the
> same way. The verified live-state and root-cause evidence in Parts 1–3 is retained
> deliberately — it is the record the fixes were derived from, not a description of the
> current code. Per-defect status is in Part 4; the deploy sequence is in Part 5.

---

## Part 1 — Verified Current State

Everything below was confirmed against live AWS, not inferred.

| Item                            | State                                                                       |
| ------------------------------- | --------------------------------------------------------------------------- |
| `AgentFleetDataStack`           | ✅ Deployed, table `agent-fleet-config` live                                 |
| Seed data                       | ✅ `SUBJECT#llipe/memo-cli` + `AGENT#dep-updater` exists, `enabled: true`     |
| `AgentFleetIamStack`            | ✅ Deployed — but the agent role is **orphaned** (see D4)                     |
| `AgentCore-depupdater-default`  | ✅ Deployed, runtime responds to `agentcore invoke`                           |
| GitHub secret                   | ✅ **Already exists** at `dep-agent/github-pat`, contains key `token`         |
| Runtime IAM role                | ⚠️ Missing 2 permissions — **the only thing blocking a successful run** (granted in code by #56; pending deploy) |
| First pipeline run              | ❌ Failed at 0.27s (root cause below, confirmed from logs)                    |

### Confirmed working (from the first run's logs)

- Non-blocking entrypoint — returned `status: accepted` immediately (S-007)
- Async task lifecycle — `add_async_task` / `complete_async_task` both fired
- Structured JSON logging — real JSON lines with `session_id`, `agent`, `repo` (S-008)
- Docker image built in CodeBuild, container starts, imports resolve
- Runtime role already has `bedrock:InvokeModel` (the fix agent will work)

### Real resource names (the previously documented names were wrong)

| Purpose             | Actual name                                                                 |
| ------------------- | --------------------------------------------------------------------------- |
| Agent app logs      | `/aws/bedrock-agentcore/runtimes/depupdater_dep_updater-M4gkuL4wSr-DEFAULT`  |
| Spans               | `aws/spans` (exists, retention already 30 days)                              |
| Runtime exec role   | `AgentCore-depupdater-defa-ApplicationAgentDepUpdate-rUTxhPZ6kWBL`           |

`/aws/agentcore/dep-updater` and `/aws/vendedlogs/agentcore/dep-updater/spans` **do not
exist and never will** — see defects D2 and D3.

---

## Part 2 — Root Cause of the Failed Run

Two `AccessDeniedException`s, verbatim from the runtime log group:

```
1. secretsmanager:GetSecretValue on resource: dep-agent/github-pat
   because no identity-based policy allows the secretsmanager:GetSecretValue action

2. dynamodb:UpdateItem on resource: arn:aws:dynamodb:us-east-1:755641879575:table/agent-fleet-config
   because no identity-based policy allows the dynamodb:UpdateItem action
```

The pipeline threw at `get_github_token()`, the generic `except Exception` handler caught
it, and `finally` called `complete_async_task()` — so the CLI reported success in 0.27s.

**This is a single-cause failure: the AgentCore runtime execution role has no permissions
beyond what AgentCore provisions by default.** The secret exists. The code path is correct.
The seed data is correct.

### Corrections to the previous version of this document

| Previously claimed                                    | Reality                                                  |
| ----------------------------------------------------- | -------------------------------------------------------- |
| Secret does not exist; create `agent-fleet/github-pat` | Secret **already exists** at `dep-agent/github-pat`      |
| Change the code default secret path (`sed main.py`)   | **No code change needed** — path is already correct      |
| Grant `bedrock:InvokeModel`                            | **Already granted** by AgentCore's default policy        |
| DynamoDB item may need seeding                          | **Already seeded**                                       |

Do not apply those steps. They were inference, not verification.

---

## Part 3 — The Blocker and How to Fix It Properly

The runtime role needs exactly two additions:

1. `secretsmanager:GetSecretValue` on `dep-agent/github-pat`
2. `dynamodb:UpdateItem` (+ `GetItem`/`Query`) on `agent-fleet-config`

### Critical design constraint

`infra/lib/iam-stack.ts` deliberately constrains the agent's DynamoDB writes:

- **Allow** `UpdateItem` only when every touched attribute is in
  `AGENT_EXEC_WRITE_ATTRIBUTES` = `pk`, `sk`, `last_status`, `last_outcome_url`
- **Deny** `PutItem` outright (would replace the whole item)
- **Deny** `UpdateItem` touching `enabled` or `params` (defence in depth)

Granting the runtime plain `dynamodb:UpdateItem` would **silently discard the entire
write-separation control** that S-004 exists to enforce. The agent would be able to
flip `enabled` or rewrite `params`. Any fix must replicate all three statements.

### Option A — Codify in the vended CDK stack (RECOMMENDED — **implemented in #56**)

> **Landed.** All five statements are now in
> `agents/dep-updater/agentcore/cdk/lib/cdk-stack.ts`, sourced from
> `agents/dep-updater/agentcore/cdk/lib/fleet-iam-attributes.ts` — a mirror of the
> `@fleet/shared` allowlists that `infra/test/vended-cdk-iam-drift.test.ts` fails CI on if
> it drifts. The vended CDK app cannot import `@fleet/shared` (the AgentCore CLI stages it
> as a standalone npm project outside the pnpm workspace), so the mirror plus the drift
> guard is the enforcement mechanism. Covered by 17 assertions in
> `agents/dep-updater/agentcore/cdk/test/cdk.test.ts`. **Still needs `agentcore deploy` to
> take effect.**

`agents/dep-updater/agentcore/cdk/lib/cdk-stack.ts` **is tracked in git** (confirmed via
`git ls-files`), and it already uses the `env.runtime.role.addToPrincipalPolicy(...)`
pattern for payments. Grants added there are reproducible, survive redeploys, and are
reviewable.

**This is a code change — it must be delegated to `developer`, not applied ad hoc.**

Scope of the change:

- Add `secretsmanager:GetSecretValue` scoped to the `dep-agent/github-pat` ARN
- Add `dynamodb:GetItem` / `Query` on the table + GSI
- Add `dynamodb:UpdateItem` with the `ForAllValues:StringEquals` condition on
  `AGENT_EXEC_WRITE_ATTRIBUTES`
- Add the explicit `DenyPutItem` and `DenyWriteForbiddenAttributes` statements
- Source the attribute lists from `@fleet/shared` (`AGENT_EXEC_WRITE_ATTRIBUTES`) so the
  vended stack cannot drift from `infra/lib/iam-stack.ts`
- Add a CDK assertion test mirroring `infra/test/iam-stack.test.ts`

Then redeploy:

```bash
cd agents/dep-updater && agentcore deploy
```

### Option B — Manual inline policy (smoke test only, **no longer needed**)

> Option A has landed in code, so this path exists only as a historical record. Prefer
> `agentcore deploy`. Using it now would create the very IAM drift the fix removes.

Use only to prove the pipeline end-to-end before Option A lands. It is **undocumented
infrastructure drift** and must be removed once Option A is deployed.

This modifies IAM on a live role. Confirm before running.

```bash
RUNTIME_ROLE=$(aws cloudformation describe-stack-resources \
  --stack-name AgentCore-depupdater-default \
  --query "StackResources[?ResourceType=='AWS::IAM::Role'].PhysicalResourceId" \
  --output text | tr '\t' '\n' | grep RuntimeExecutionRole)

echo "Target role: $RUNTIME_ROLE"   # verify before proceeding

aws iam put-role-policy \
  --role-name "$RUNTIME_ROLE" \
  --policy-name "DepUpdaterTempSmokeTest" \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [
      {
        "Sid": "SecretsManagerRead",
        "Effect": "Allow",
        "Action": "secretsmanager:GetSecretValue",
        "Resource": "arn:aws:secretsmanager:us-east-1:755641879575:secret:dep-agent/github-pat-*"
      },
      {
        "Sid": "DynamoDBRead",
        "Effect": "Allow",
        "Action": ["dynamodb:GetItem", "dynamodb:Query"],
        "Resource": [
          "arn:aws:dynamodb:us-east-1:755641879575:table/agent-fleet-config",
          "arn:aws:dynamodb:us-east-1:755641879575:table/agent-fleet-config/index/*"
        ]
      },
      {
        "Sid": "DynamoDBUpdateOutcome",
        "Effect": "Allow",
        "Action": "dynamodb:UpdateItem",
        "Resource": "arn:aws:dynamodb:us-east-1:755641879575:table/agent-fleet-config",
        "Condition": {
          "ForAllValues:StringEquals": {
            "dynamodb:Attributes": ["pk", "sk", "last_status", "last_outcome_url"]
          }
        }
      },
      {
        "Sid": "DenyPutItem",
        "Effect": "Deny",
        "Action": "dynamodb:PutItem",
        "Resource": "arn:aws:dynamodb:us-east-1:755641879575:table/agent-fleet-config"
      },
      {
        "Sid": "DenyWriteForbiddenAttributes",
        "Effect": "Deny",
        "Action": "dynamodb:UpdateItem",
        "Resource": "arn:aws:dynamodb:us-east-1:755641879575:table/agent-fleet-config",
        "Condition": {
          "ForAnyValue:StringEquals": {
            "dynamodb:Attributes": ["enabled", "params"]
          }
        }
      }
    ]
  }'
```

Removal once Option A is deployed:

```bash
aws iam delete-role-policy --role-name "$RUNTIME_ROLE" --policy-name "DepUpdaterTempSmokeTest"
```

---

## Part 4 — Defects Found During Verification

These are correctness bugs in committed code and docs, not deployment steps. Each needs a
`developer` task.

**Defect status at a glance**

| Defect | Status                                                         |
| ------ | -------------------------------------------------------------- |
| D1     | ✅ Fixed in code (#56) — pending `agentcore deploy`             |
| D2     | ✅ Fixed in code (#56) — takes effect on control-plane redeploy |
| D3     | ✅ Fixed in code and docs (#56)                                |
| D4     | 🟡 Open — decision needed (partially mitigated by D1's fix)     |
| D5     | 🟡 Open — needs a real span record from a successful run         |
| D6     | ⚪ Open — cosmetic, user-gated cleanup                          |

### D1 — Runtime role has no data-plane permissions (the blocker)

> **Status: fixed in code (#56), pending deploy.** The five statements are in the vended
> CDK stack (Part 3, Option A). The live role is unchanged until `agentcore deploy` runs.

Covered in Part 3. Root cause: `agentcore.json` has no mechanism wiring the runtime to
`agent-fleet-agent-exec-role`, and the vended CDK never grants equivalents.

### D2 — `SPANS_LOG_GROUP` points at a non-existent log group ⚠️ HIGH

> **Status: fixed in code (#56).** `packages/shared/src/observability-config.ts` now reads
> `aws/spans`, pinned by a regression test in `observability-config.test.ts`, and
> `docs/runbook-observability-setup.md` records the corrected value with a historical note.
> This was spec fidelity, not a new decision: the specification's resolution of PRD open
> question #1 always said "Shared `aws/spans` log group". Takes effect for the runs view on
> the next control-plane deploy.

The original defect, for the record — `packages/shared/src/observability-config.ts` read:

```ts
export const SPANS_LOG_GROUP = "/aws/vendedlogs/agentcore/dep-updater/spans" as const;
```

That group does not exist. Spans actually land in **`aws/spans`** (which exists and
already has 30-day retention). The spec's own resolution of PRD open question #1 says
_"Shared `aws/spans` log group"_ — so the constant and
`docs/runbook-observability-setup.md` both drifted away from the approved decision.

Impact: every control-plane Logs Insights query (S-017, S-016) targets a group that does
not exist, so the runs view returns nothing. Not detectable by unit tests because they
assert against the constant.

Fix: correct the constant to `aws/spans`, correct the runbook's "Span Destination" and
"Configuration" sections, and confirm the committed span fixtures in
`packages/shared/__fixtures__/` match real `aws/spans` records.

### D3 — Documented app log group name is fictional

> **Status: fixed in code and docs (#56).** `workstream/manual-validation-checklist.md` now
> discovers the group, and `apps/control-plane`'s `resolveAgentLogGroup()` requires
> `AGENT_LOG_GROUP` and returns an actionable error when it is unset instead of falling back
> to a guessed name. `docs/runbook-deployment.md` documents where the value comes from and
> when to refresh it. **`AGENT_LOG_GROUP` must be set on the control-plane deploy** — this
> is now a hard requirement, not a fallback.

`workstream/manual-validation-checklist.md` (and the prior version of this file)
reference `/aws/agentcore/dep-updater`. The real group is
`/aws/bedrock-agentcore/runtimes/depupdater_dep_updater-M4gkuL4wSr-DEFAULT`.

The suffix `-M4gkuL4wSr` is AgentCore-generated and will change if the runtime is
recreated, so validation docs must **discover** the group rather than hardcode it:

```bash
aws logs describe-log-groups \
  --log-group-name-prefix /aws/bedrock-agentcore/runtimes/depupdater_dep_updater \
  --query 'logGroups[0].logGroupName' --output text
```

Fix: update the S-008 verification steps to use discovery.

### D4 — `agent-fleet-agent-exec-role` is orphaned

> **Status: open, partially mitigated by #56.** The second half of the proposed fix is done —
> the vended CDK now derives its grants from a mirror of the same `@fleet/shared` allowlists,
> with `infra/test/vended-cdk-iam-drift.test.ts` failing CI if the two diverge. What remains
> is the decision on whether to wire the runtime to the orphaned role at all.

`AgentFleetIamStack` creates it with the correct constrained policy, trusted by
`bedrock-agentcore.amazonaws.com` — but AgentCore creates and uses its own role, so this
one is never assumed by the agent. It still has value as the contract fixture the IAM
integration tests assume into, but right now the deployed agent's real permissions are
governed by a completely different role that the tests never inspect.

Fix (decision needed): either wire the runtime to this role if AgentCore supports an
execution-role override, or keep it as the contract fixture and make the vended CDK
derive its grants from the same `@fleet/shared` allowlists, plus a test asserting the two
stay identical.

### D5 — Two different session IDs for one run

> **Status: open, out of scope for #56.** Choosing a canonical id needs a real span record
> from a successful run, which does not exist yet.

App logs are keyed by the **payload** `session_id` (`test-001`), while AgentCore's own
lines and the span context carry the **runtime** session id
(`f2f904fa-9160-40ee-a6c4-db1f44eb67c9`). `main.py` only injects the runtime id when the
payload omits it.

Impact: joining spans to logs by session id fails whenever the caller supplies its own
`session_id` — which the orchestrator does by design. Affects the run detail view.

Fix: decide which id is canonical, and either always log both or always prefer the
runtime id. Needs verification against a real span record before choosing.

### D6 — Stale runtime from an earlier deploy

> **Status: open, out of scope for #56.** Deleting a live-ish runtime is a user-gated action.

`/aws/bedrock-agentcore/runtimes/dependencyUpdateAgent_depUpdateAgent-D7WI0qFw6a-DEFAULT`
is a leftover from a prior naming scheme. Confirm the runtime is no longer live before
deleting anything. Cosmetic; not blocking.

---

## Part 5 — Execution Sequence

### Stage 1 — Unblock the agent (deploy the D1 fix)

The grants are in code (Part 3, Option A). Deploy them:

```bash
cd agents/dep-updater
agentcore deploy --dry-run   # validate + synth, no AWS changes
agentcore deploy
```

If the GitHub App cutover is being done at the same time, follow
`docs/runbook-github-app.md` **first** — `agentcore.json` now points
`GITHUB_SECRET_ID` at `dep-agent/github-app`, which does not exist until that runbook
has been followed. Rollback is flipping that value back to `dep-agent/github-pat`.
Option B is no longer the path; it would reintroduce IAM drift.

### Stage 2 — First successful run

```bash
cd agents/dep-updater
agentcore invoke '{"session_id": "smoke-001", "repo": "llipe/memo-cli"}'
```

Expect **2–10 minutes**, not 0.27s. Follow along:

```bash
LG=$(aws logs describe-log-groups \
  --log-group-name-prefix /aws/bedrock-agentcore/runtimes/depupdater_dep_updater \
  --query 'logGroups[0].logGroupName' --output text)

aws logs filter-log-events --log-group-name "$LG" \
  --filter-pattern '{ $.session_id = "smoke-001" }' \
  --query 'events[*].message' --output text
```

Acceptance checks for S-006 through S-011:

| Check                                 | Command / expectation                                                     |
| ------------------------------------- | ------------------------------------------------------------------------- |
| Pipeline behaviour unchanged (S-006)  | Logs show clone → install → audit → update → lint/format/typecheck → test |
| No idle-timeout kill (S-007)          | Run exceeds 5 min and still completes                                      |
| JSON logs filterable (S-008)          | Filter above returns only this run's lines                                 |
| `llipe.*` span attributes (S-010)     | Query `aws/spans` — the corrected `SPANS_LOG_GROUP` value (D2)              |
| Outcome stamped (S-011)               | `last_status` / `last_outcome_url` set; `enabled` / `params` untouched      |

```bash
# S-011 verification
aws dynamodb get-item --table-name agent-fleet-config \
  --key '{"pk":{"S":"SUBJECT#llipe/memo-cli"},"sk":{"S":"AGENT#dep-updater"}}' \
  --output json
```

If `memo-cli` has no available updates the run legitimately ends at
`"no changes after update — nothing to do"` with `last_status: success`. That still
validates S-006 through S-009 and S-011, but produces no PR and no model spans — so
**S-010's token/model assertions need a run with a forced test failure** (already tracked
as deferred sub-task 12.1).

### Stage 3 — Observability finish (S-005)

`aws/spans` already has 30-day retention. Remaining:

```bash
# App log group has no retention set
aws logs put-retention-policy --log-group-name "$LG" --retention-in-days 30
```

Then enable CloudWatch Transaction Search at 1% sampling (console only):
CloudWatch → Settings → Traces and Metrics → Transaction Search → Edit.

No longer blocked — D2's fix records the correct span destination (`aws/spans`).

### Stage 4 — Orchestrator Lambda (S-013)

Independent of the agent defects.

```bash
cd infra
pnpm run cdk diff AgentFleetOrchestrationStack
pnpm run cdk deploy AgentFleetOrchestrationStack

aws lambda invoke --function-name agent-fleet-orchestrator \
  --payload '{"agent":"dep-updater","scheduledAt":"2026-01-28T10:00:00Z"}' \
  /tmp/orchestrator-output.json
```

Note: the orchestrator will hit the same permission class of problem if its role is not
the one the Lambda actually runs as. Verify before assuming.

### Stage 5 — Control Plane on Fly.io (S-024)

See `docs/runbook-deployment.md`. D2 is fixed, so the runs view now targets the real span
group. Two environment variables are required on the Fly app: `SPANS_LOG_GROUP` resolves
from `@fleet/shared`, but **`AGENT_LOG_GROUP` must be set explicitly** (D3) — the app no
longer guesses it and will surface an actionable error if it is missing.

```bash
flyctl apps create agent-fleet-control-plane --org <your-org>
fly secrets set CF_ACCESS_TEAM_NAME="<team>" CF_ACCESS_AUD="<aud>" \
  AWS_REGION="us-east-1" \
  AGENT_LOG_GROUP="$(aws logs describe-log-groups \
    --log-group-name-prefix /aws/bedrock-agentcore/runtimes/depupdater_dep_updater \
    --query 'logGroups[0].logGroupName' --output text)" \
  --app agent-fleet-control-plane
flyctl deploy --config infra/control-plane.fly.toml --remote-only
```

Also requires Cloudflare Access app, Cloudflare Tunnel, and the Fly → AWS OIDC trust
policy.

---

## Part 6 — Status Board

Legend: ✅ done and live · 🟢 fixed in code, pending deploy · 🟡 open · ⚪ cosmetic · 🔲 not started

```
1.  ✅ AgentFleetDataStack (table + GSI)
2.  ✅ Seed script
3.  ✅ AgentFleetIamStack (deployed; role orphaned — D4)
4.  ✅ Agent deploy (AgentCore-depupdater-default)
5.  ✅ GitHub secret dep-agent/github-pat (already existed)
6.  🟢 D1 — runtime role Secrets + constrained DynamoDB grants in vended CDK  ← DEPLOY TO UNBLOCK
7.  🟢 D2 — SPANS_LOG_GROUP corrected to aws/spans (runs view fixed on redeploy)
8.  🟢 D3 — AGENT_LOG_GROUP now required; validation docs discover the group
9.  🟡 D4 — orphaned agent-exec-role: drift guard landed, wiring decision open
10. 🟡 D5 — dual session_id correlation (needs a real span record)
11. ⚪ D6 — delete stale dependencyUpdateAgent runtime (cosmetic, user-gated)
12. 🟢 GitHub App migration — code + runbook ready; secret must be created before deploy
13. 🔲 First successful run (validates S-006 … S-011)
14. 🔲 App log group retention + Transaction Search (S-005)
15. 🔲 AgentFleetOrchestrationStack (S-013)
16. 🔲 Fly app + Cloudflare Access/Tunnel (S-024)
```

Nothing on this board has been applied to live AWS by issue #56. Items 6, 7, 8 and 12 are
code changes awaiting the user's gated deploy step.

---

## Notes

- `agentcore invoke` calls the **remote deployed runtime**; it never runs code locally.
- Payload shape (from `payload.py`): `session_id` and `repo` required; `params` accepts
  only `allow_fixes` (bool) and `max_fix_attempts` (int) — unknown keys are rejected, not
  stripped. Defaults: `allow_fixes: true`, `max_fix_attempts: 3`.
- Quote the JSON in a single argument or zsh will try to parse the braces.
- `outcome_store.py` requires the item to pre-exist (`attribute_exists(pk)`); a missing
  seed row is logged and swallowed, never surfaced as a run failure.
- All CDK stacks use `RemovalPolicy.RETAIN`; DynamoDB deletion protection is on.
- The seed script is idempotent (`attribute_not_exists`), safe to re-run.
- The `-M4gkuL4wSr` suffix in the runtime log group is AgentCore-generated. Always
  discover it; never hardcode.
