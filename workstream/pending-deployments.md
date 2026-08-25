# Pending Deployments — Agent Control Plane v1

Deployment steps deferred during implementation, plus defects found during first-run
verification. Each action requires explicit confirmation before executing.

**Last verified against live AWS:** account `755641879575`, region `us-east-1`.

> **Status update — 2026-08-25 (second pass).** **All eight deployment stages are live.** The
> agent pipeline was already operational (D1 deployed, GitHub App cutover complete, first
> successful run produced PR llipe/memo-cli#49, orchestrator deployed and invoked). **D7 (#60)
> is now closed**: the control-plane role trusts Fly OIDC, has `logs:` and `tag:GetResources`
> grants, the dead credential code is deleted, and the app is deployed at `fleet.llipe.com`
> behind Cloudflare Access with an issued certificate. Decisions recorded in
> [ADR-001](../docs/adr/ADR-001-fly-oidc-sole-credential-path-for-control-plane.md) and
> [ADR-002](../docs/adr/ADR-002-build-is-part-of-the-validate-quality-gate.md).
>
> **What is still open:** **D9** (#62) — `aws/spans` has never received a record, so the runs
> views are empty shells; **D8** (#61) — every agent renders three times, which also affects
> the per-repo agent count; **D4**, **D5**, **D6**, **#59**; and a **new item 20** — the origin
> lockdown required by `docs/technical-guidelines.md` §5 was never implemented, so
> `.fly.dev` is reachable with middleware as the sole control.
>
> `docs/runbook-deployment.md` is the single source of truth for deployment steps; the
> sequences in Part 5 below are retained only where still accurate. The verified live-state and
> root-cause evidence in Parts 1–3 is retained as historical record.
>
> **Recommended order:** #62 (unblocks D5 and makes the runs views real), then #61, then item
> 20 / D4, then #59 and D6.

---

## Part 1 — Verified Current State

Everything below was confirmed against live AWS, not inferred.

> **Note on this section.** It records the state at first-run verification (2026-08-24). The
> two ⚠️/❌ rows have since been resolved — see the status update at the top of this file and
> the Part 6 status board for current state. Retained because Part 2's root-cause analysis
> depends on it.

| Item                            | State                                                                       |
| ------------------------------- | --------------------------------------------------------------------------- |
| `AgentFleetDataStack`           | ✅ Deployed, table `agent-fleet-config` live                                 |
| Seed data                       | ✅ `SUBJECT#llipe/memo-cli` + `AGENT#dep-updater` exists, `enabled: true`     |
| `AgentFleetIamStack`            | ✅ Deployed — but the agent role is **orphaned** (see D4)                     |
| `AgentCore-depupdater-default`  | ✅ Deployed, runtime responds to `agentcore invoke`                           |
| GitHub secret                   | ✅ **Already exists** at `dep-agent/github-pat`, contains key `token`         |
| Runtime IAM role                | ⚠️ At the time: missing 2 permissions — the only thing blocking a successful run. Granted in code by #56 and **since deployed** |
| First pipeline run              | ❌ Failed at 0.27s (root cause below). **A later run succeeded** — PR llipe/memo-cli#49 |

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
| D1     | ✅ Fixed in code (#56) and deployed via `agentcore deploy`      |
| D2     | ✅ Fixed in code (#56), live since the control-plane deploy     |
| D3     | ✅ Fixed in code and docs (#56); `AGENT_LOG_GROUP` set on Fly   |
| D4     | 🟡 Open — decision needed (partially mitigated by D1's fix)     |
| D5     | 🟡 Open — needs a real span record from a successful run; blocked by D9 |
| D6     | ⚪ Open — cosmetic, user-gated cleanup                          |
| D7     | ✅ Resolved 2026-08-25 (#60) — OIDC trust, `logs:`/`tag:` grants, dead code deleted |
| D8     | 🟡 Open — duplicate agent inventory entries, tracked in #61      |
| D9     | 🔴 Open — `aws/spans` empty, no OTEL exporter, tracked in #62    |

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

> **Status: open, out of scope for #56. Blocked by D9 (#62).** Choosing a canonical id needs a
> real span record, and `aws/spans` has never received one because no OTEL exporter is
> installed. D9 must land first; its AC5 produces exactly the evidence this decision needs.

App logs are keyed by the **payload** `session_id` (`test-001`), while AgentCore's own
lines and the span context carry the **runtime** session id
(`f2f904fa-9160-40ee-a6c4-db1f44eb67c9`). `main.py` only injects the runtime id when the
payload omits it.

Impact: joining spans to logs by session id fails whenever the caller supplies its own
`session_id` — which the orchestrator does by design. Affects the run detail view.

Fix: decide which id is canonical, and either always log both or always prefer the
runtime id. Needs verification against a real span record before choosing.

### D6 — Stale runtimes from earlier deploys

> **Status: open, out of scope for #56.** Deleting a live-ish runtime is a user-gated action.

Two leftovers, not one:

- `/aws/bedrock-agentcore/runtimes/dependencyUpdateAgent_depUpdateAgent-D7WI0qFw6a-DEFAULT`
  — from a prior naming scheme (18 KB of logs)
- `/aws/bedrock-agentcore/runtimes/harness_harness_4hgtk-moVgD32GYk-DEFAULT` — unidentified
  (36 KB of logs)

Neither carries `agent:managed=true`, confirmed via `get-resources`, so neither pollutes the
control plane's agent inventory. Purely cosmetic. Confirm each runtime is no longer live
before deleting anything.

### D8 — Agent inventory returns duplicate entries per agent

> **Status: open, tracked in #61.** Unreachable until #60 grants `tag:GetResources`.

AgentCore tags three resources per deployed agent — runtime, runtime-endpoint, and
workload-identity-directory — all with identical `agent:managed=true`, `agent:name`,
`agent:domain`. `listManagedAgents()` in `apps/control-plane/src/server/aws/tagging-adapter.ts`
pushes one `DiscoveredAgent` per tagged resource with no dedupe, so `dep-updater` will render
three times.

The tag propagation is correct; the fix belongs on the read side (dedupe by `agent:name`,
preferring the bare `runtime/...` ARN). Because #60's AC6 checks that the agents list
renders, this is worth landing in the same cycle so that AC is unambiguous.

### D9 — `aws/spans` is empty; no OTEL exporter is installed 🔴

> **Status: open, tracked in #62. Blocks D5 and the runs views.**

`aws/spans` has `storedBytes=0` and its only stream reports `lastEventTimestamp=None`. No
span has ever been delivered, despite the successful run that produced PR llipe/memo-cli#49.
No alternative destination exists in the account.

Two things ruled out first:

- **Transaction Search is enabled** — `Destination: CloudWatchLogs`, `Status: ACTIVE`, 100%
  sampling, since 2026-08-24. It is the required ingestion mechanism (see Stage 3), and it
  is on.
- **The instrumentation wrapper is present** — `Dockerfile.dep-updater` line 93 is
  `CMD ["opentelemetry-instrument", "python", "main.py"]`.

The actual cause: `agents/dep-updater/pyproject.toml` declares only `opentelemetry-api` and
`opentelemetry-sdk`, and `uv.lock` resolves **no `*exporter*` package and no
`aws-opentelemetry-distro`**. So `opentelemetry-instrument` starts, the threading
instrumentation is wired, `emission.py` successfully sets the `llipe.*` attributes on the
live span — and the span is then dropped, because the SDK has nowhere to export it.

Impact: S-010 is unverifiable, S-016/S-017 runs views are empty shells regardless of #60,
D5 stays blocked, and the span fixtures in `packages/shared/__fixtures__/` have never been
validated against a real record.

This means D2's fix was necessary but not sufficient. Pointing `SPANS_LOG_GROUP` at
`aws/spans` was correct per the spec; nothing has ever written to it.

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

Then enable CloudWatch Transaction Search — **already enabled, and it is required.** Per the
[AgentCore observability docs](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-configure.html),
Transaction Search is the one-time setup that ingests AgentCore spans as structured logs
into `aws/spans`. A previous revision of this file claimed it was "not applicable — no X-Ray
segments are emitted"; **that was wrong** and is corrected here. It is active on this
account as of 2026-08-24 (`Destination: CloudWatchLogs`, `Status: ACTIVE`, 100% sampling),
confirmed with `aws xray get-trace-segment-destination`. The console path is CloudWatch →
Application Signals (APM) → Transaction search, not the `Settings → Traces and Metrics`
path previously documented.

`aws/spans` is nevertheless still empty — see D9 (#62). The cause is on the agent side, not
in CloudWatch configuration.

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

**Deployed 2026-08-25.** D7 (#60) is closed. The full corrected sequence lives in
`docs/runbook-deployment.md` — that is the single source of truth for deployment steps. The
commands previously listed here used the wrong app name (`agent-fleet-control-plane`, actually
`dt-agent-fleet-control-plane`), the wrong role name, and the wrong credential env var
(`FLY_AWS_ROLE_ARN`, actually `AWS_ROLE_ARN` — Fly's `init` derives the rest), and omitted the
missing `logs:` grants entirely. Do not follow them.

Required environment on the Fly app: `CF_ACCESS_TEAM_NAME`, `CF_ACCESS_AUD`, `AWS_REGION` and
`AGENT_LOG_GROUP` (no default — D3) as secrets, plus `AWS_ROLE_ARN` in `[env]` in the
repo-root `fly.toml`, where it is reviewable in git. `SPANS_LOG_GROUP` resolves from
`@fleet/shared` and needs no secret.

---

## Part 6 — Status Board

Legend: ✅ done and live · 🟢 fixed in code, pending deploy · 🟡 open · ⚪ cosmetic · 🔲 not started

```
1.  ✅ AgentFleetDataStack (table + GSI)
2.  ✅ Seed script
3.  ✅ AgentFleetIamStack (deployed; role orphaned — D4)
4.  ✅ Agent deploy (AgentCore-depupdater-default)
5.  ✅ GitHub secret dep-agent/github-pat (already existed)
6.  ✅ D1 — runtime role Secrets + constrained DynamoDB grants deployed via agentcore deploy
7.  ✅ D2 — SPANS_LOG_GROUP corrected to aws/spans (live since the control-plane deploy)
8.  ✅ D3 — AGENT_LOG_GROUP required and set on Fly; validation docs discover the group
9.  🟡 D4 — orphaned agent-exec-role: drift guard landed, wiring decision open
10. 🟡 D5 — dual session_id correlation (needs a real span record; blocked by D9)
11. ⚪ D6 — delete two stale runtimes: dependencyUpdateAgent + harness (cosmetic, user-gated)
12. ✅ GitHub App migration — deployed and verified (PR #49 on memo-cli authored by bot)
13. ✅ First successful run — PR llipe/memo-cli#49, S-006…S-009 + S-011 validated
14. ✅ App log group retention set to 30 days; Transaction Search confirmed ACTIVE (S-005)
15. ✅ AgentFleetOrchestrationStack deployed (S-013)
16. ✅ Fly app + Cloudflare Access (S-024) — deployed 2026-08-25, cert issued, 2 machines healthy
17. ✅ D7 — control-plane role: Fly OIDC trust + logs:/tag: grants deployed; dead credential code deleted (#60)
18. 🟡 D8 — agent inventory returns 3 duplicate entries per agent (#61)
19. 🔴 D9 — aws/spans empty: no OTEL exporter installed; runs views have no data (#62)
20. 🟡 Origin lockdown not implemented — .fly.dev reachable, middleware is the sole control there
```

Items 6, 12, 13 confirmed live on 2026-08-24; items 7, 8, 16, 17 on 2026-08-25. Post-cutover
PAT cleanup tracked in #59.

**Item 16 final state (verified 2026-08-25):** Fly app `dt-agent-fleet-control-plane` deployed
from `fly.toml` at the repo root, two `shared-cpu-1x:256MB` machines healthy in `iad`, dedicated
IPv4 + IPv6 allocated. All secrets deployed, none staged, and the two static AWS keys removed.
Cloudflare Access app `fleet` enforcing on `fleet.llipe.com` with a verified Let's Encrypt
certificate at the Fly origin. The cert had been stuck `Not verified` because the order was
created before the app had public IPs — not because of the Cloudflare proxy, which validates
fine given the `_acme-challenge` CNAME and `_fly-ownership` TXT records. `docs/runbook-deployment.md`
is the single source of truth for the sequence.

**Item 20 (new, 2026-08-25):** `docs/technical-guidelines.md` §5 requires two independent
controls — JWT validation *and* origin lockdown — and states the app must not ship with only
one. It shipped with only JWT validation. Recorded as an open deviation in the guidelines and
in §18's trade-off table rather than resolved by relaxing the rule. Needs an issue and a
decision: Cloudflare Tunnel in the machine, or a Cloudflare IP allowlist on the Fly service.

### D7 — Control-plane role cannot authenticate and cannot read logs ✅ RESOLVED 2026-08-25

> **Status: closed, delivered in [#60](https://github.com/llipe/dev-tasks-agent-fleet/issues/60)**
> (task list `workstream/tasks-issue-60-control-plane-iam.md`). Decision recorded in
> [ADR-001](../docs/adr/ADR-001-fly-oidc-sole-credential-path-for-control-plane.md). The four
> gaps below are kept as the historical record; the fix and the two traps that cost a debugging
> cycle each are documented in `docs/runbook-deployment.md` §7.

Four gaps, all verified against live AWS, all now closed:

1. `agent-fleet-control-plane-role` trusts only `ecs-tasks.amazonaws.com` — a leftover from
   an ECS-hosted design. No Fly OIDC provider is registered in the account (only GitHub
   Actions), so `AssumeRoleWithWebIdentity` cannot succeed. Required provider is
   `https://oidc.fly.io/felipe-mallea`, audience `sts.amazonaws.com`, `sub` pattern
   `felipe-mallea:dt-agent-fleet-control-plane:*`.
2. The role has **no `logs:` grants at all**. D2 and D3 fixed _which_ log groups are
   queried; nothing ever granted permission to read them. The runs view and log panel fail
   with `AccessDeniedException` even once trust is fixed.
3. `credentials.ts` reads `FLY_AWS_ROLE_ARN` and `FLY_OIDC_TOKEN_PATH` — **neither is a real
   Fly variable**. Fly's `init` sets `AWS_WEB_IDENTITY_TOKEN_FILE` and
   `AWS_ROLE_SESSION_NAME` when `AWS_ROLE_ARN` is present, and the AWS SDK default chain
   handles the rest. The custom `fromWebToken` branch is dead code that falls through to the
   local-dev `fromEnv()` path, and it reads the token once at import so it never refreshes.
4. `tag:GetResources` is also missing. `server/aws/tagging-adapter.ts` discovers agents by
   the `agent:managed=true` tag filter — this is the grant that fails first, leaving the
   agents list empty and masking the logs problem.

Mechanism, claim values and the corrected fix are documented in
`docs/runbook-deployment.md` §7, verified against Fly's OIDC docs.

**Resolution, 2026-08-25.** All four closed. `infra/lib/iam-stack.ts` registers an
`iam.OpenIdConnectProvider` for `https://oidc.fly.io/felipe-mallea` and the role is assumed by
an `iam.WebIdentityPrincipal` conditioned on `:aud` and `:sub`; `CloudWatchLogsRead` and
`TaggingRead` statements were added; `credentials.ts` now delegates to
`fromNodeProviderChain()` with a startup diagnostic that logs the token's claims but never the
token. The org-slug trap (gap 1) was the actual cause of the `InvalidIdentityTokenException`
seen during rollout — `fly orgs list` prints the alias `personal` while tokens are issued by
`felipe-mallea`, and discovery resolves for both, so only a live token's `iss` claim settles it.
`infra/test/iam-stack.test.ts` carries a regression test against the alias reappearing.

Two verifications remain incomplete, neither blocking:

- `AWS_WEB_IDENTITY_TOKEN_FILE` and `AWS_ROLE_SESSION_NAME` were confirmed via the startup
  diagnostic but not via `fly ssh console -C env`, which fails with a WebSocket 502 behind
  corporate TLS interception. Re-run from an unproxied network.
- Token refresh over long uptime is unobserved. Fly's docs do not say whether `init` rewrites
  `/.fly/oidc_token` as the token ages; watch `fly logs` for `InvalidIdentityToken` after more
  than an hour of uptime. With `auto_stop_machines` enabled it may never surface.

Rejected workaround: an IAM user with access keys. Attaching DynamoDB grants directly to a
user bypasses the attribute conditions and the `InvokeAgentRuntime` deny, which is the same
class of mistake as granting the agent runtime plain `UpdateItem` (Part 3). The inert IAM
user `fleet-control-plane-reader` created during investigation — no policies, no access
keys — **was deleted on 2026-08-25**, and the two static AWS keys were unset from Fly. Static
keys are no longer a documented fallback anywhere; see ADR-001.

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
