# Operator Runbook — Issue #89: Live panel→agent invocation verification

> **Audience:** the human operator with local AWS credentials (SSO/profile) that can call
> `bedrock-agentcore:InvokeAgentRuntime`, the panel running locally, and Supabase SQL access to the
> project the deployed agent reports to.
>
> **Why this exists:** these checks require a live invocation against the **deployed** AgentCore
> runtime and reads of the shared Supabase database and CloudWatch. None can be performed by the
> developer agent — it has no AWS credentials and cannot reach the runtime. They were recorded
> **BLOCKED** during Wave 4 (tasks 1.17, 1.27) and are closed here now that the runtime is deployed.

| Field | Value |
|-------|-------|
| Issue | [#89](https://github.com/llipe/dev-tasks-agent-fleet/issues/89) (closed with contract evidence; these are the live confirmations) |
| Tracking | Wave 4 plan tasks **1.17**, **1.27**; Wave 4 exit criterion **OQ2** |
| Region | `us-east-1` |
| Supabase project | `hegxeycmbmjfgzqpdiik` (dev-tasks-agent-fleet) |
| Runtime ARN | `arn:aws:bedrock-agentcore:us-east-1:755641879575:runtime/dependencyupdate_dependency_update-UsQc5U5Yz0` (authoritative source: `supabase/seed.sql` `agents.runtime_arn`) |
| Agent slug | `dependency-update` |
| Contract authority | `agents/dependency-update/app/dependencyUpdate/main.py` `_REQUIRED_FIELDS = ("run_id", "repository_org", "repository_name")` |

---

## What each check proves

| Check | Plan item | Proves |
|-------|-----------|--------|
| **A** — happy path `queued → running` | 1.17 (AC1) | The panel's well-formed payload is accepted and the agent reports `running` — the panel→agent boundary works end to end. |
| **B** — malformed payload → `INVALID_PARAMS` | 1.17 (AC2) | The agent's `validate_payload` rejects a payload missing a required field with the contract error code. |
| **C** — `prompt`-wrapping observation | 1.27 (OQ2) | Records the actual shape the deployed AgentCore transport delivers (bare / single-wrapped / double-wrapped), confirming `unwrap_payload` handled it. |

**Key facts from the code (so the checks target the right layer):**

- The panel sends the **bare inner JSON** as the invoke payload (`lib/aws/invoke.ts` does
  `JSON.stringify(payload)` where `payload = buildAgentPayload(...) =
  {run_id, repository_org, repository_name, base_branch, params}`). It never adds a `prompt`
  wrapper itself — so OQ2 is about what the **AgentCore transport** does to that payload.
- `buildAgentPayload` **cannot** emit a malformed payload (it always includes the three required
  fields). So Check B must invoke the **deployed runtime directly** (bypassing the panel) to
  exercise the agent's rejection path.
- The `queued → running` flip is written by the agent's `RunReporter.start()`:
  `PATCH runs SET status='running', started_at=now() WHERE id=eq.<run_id>`. That flip is the AC1
  observable.

---

## Prerequisites (once per session)

1. **AWS credentials** with `bedrock-agentcore:InvokeAgentRuntime` on the runtime:
   ```bash
   aws sso login            # or: export AWS_PROFILE=<profile>
   aws sts get-caller-identity
   export AWS_REGION=us-east-1
   ```

2. **Point the panel at the project the deployed agent reports to.** The panel inserts the `queued`
   row; the deployed agent PATCHes it to `running`. They **must be the same database** or the flip
   is invisible. In `panel/.env.local`:
   ```
   SUPABASE_URL=https://hegxeycmbmjfgzqpdiik.supabase.co
   SUPABASE_SERVICE_ROLE_KEY=<service_role key for hegxeycmbmjfgzqpdiik>
   AGENT_RUNTIME_ROLE_ARN=   # leave UNSET locally — only the Fly branch uses it (S-115)
   ```
   > Local AWS credentials come from the SDK provider chain (SSO/profile/env), **not**
   > `AGENT_RUNTIME_ROLE_ARN` — that variable is read only on the Fly OIDC branch (`lib/aws/credentials.ts`).

3. **Run the panel:** `pnpm --filter panel dev` (Invoke is enabled as of PR #144).

4. **Pick a real repository id** (Check A needs one):
   ```sql
   select id, full_name from repositories where is_enabled and archived_at is null;
   ```

---

## Check A — `queued → running` (happy path, task 1.17 / #89 AC1)

Use the UI (`/agents/dependency-update` → **Invoke** → pick repo → `fix_mode: audit_only` → Run) or
curl the route directly:

```bash
curl -i -X POST http://localhost:3000/api/agents/dependency-update/invoke \
  -H 'content-type: application/json' \
  -d '{"repository_id":"<REPO_UUID>","params":{"fix_mode":"audit_only"}}'
```

**Expected route response:** `202 { "run_id": "<uuid>", "status": "queued" }`.

**Observe the transition** (Supabase SQL, project `hegxeycmbmjfgzqpdiik`):
```sql
select id, status, started_at, session_id, error_code
from runs where id = '<run_id>';
```
- Immediately after submit: `status = 'queued'`.
- Within the start-timeout window (`start_timeout_seconds`, 300 s), once the agent's
  `RunReporter.start()` runs: `status = 'running'`, `started_at` set.

**PASS (AC1):** the row flips `queued → running` with `started_at` populated.

**Cross-check (CloudWatch, agent log group):** expect `GitHub credentials resolved`,
`Repository cloned`, `Toolchain: pm=...` — i.e. the payload was accepted and parsed.

> ⚠️ Do not use a monorepo known to time out on `pnpm list -r --depth Infinity` unless you have the
> #145 fix deployed. #145 makes that step degrade gracefully; without it a huge repo may fail the
> run *after* `running` (which still satisfies AC1 — the `queued → running` flip is what matters).

---

## Check B — malformed payload → `INVALID_PARAMS` (task 1.17 / #89 AC2)

The panel cannot emit a malformed payload, so invoke the **deployed runtime directly** with a
payload that **omits `run_id`**:

```bash
aws bedrock-agentcore invoke-agent-runtime \
  --agent-runtime-arn 'arn:aws:bedrock-agentcore:us-east-1:755641879575:runtime/dependencyupdate_dependency_update-UsQc5U5Yz0' \
  --payload '{"repository_org":"llipe","repository_name":"<any-repo>"}' \
  /tmp/invoke-out.json
cat /tmp/invoke-out.json
```

**Expected:** the agent's terminal chunk carries `"error_code": "INVALID_PARAMS"`. In CloudWatch:
`Invalid payload — missing required fields`.

**PASS (AC2):** `error_code == "INVALID_PARAMS"` and the run does not proceed past validation.

> This is the agent's own `validate_payload` path — the same code the shared fixture test
> (`test_payload_contract_fixture.py`) already pins. Check B confirms it fires on the *live* runtime.

---

## Check C — `prompt`-wrapping observation (task 1.27 / OQ2)

No extra action — **observe** the payload shape during Check A (or B). In CloudWatch for the run,
find the entrypoint's received payload **before** `unwrap_payload` processes it, and record which
shape the transport delivered:

- [ ] **bare** — `{"run_id": ...}` (no wrapper; `unwrap_payload` no-ops)
- [ ] **single-wrapped** — `{"prompt": "{...}"}`
- [ ] **double-wrapped** — `{"prompt": "{\"prompt\": \"{...}\"}"}` (agentcore CLI ≥ 0.28.0)

The agent tolerates all three (`_MAX_UNWRAP_DEPTH = 16`); Check A reaching `running` **is** the proof
that unwrapping succeeded. Check C only **records which shape is real** so `technical-guidelines.md`
§8 can state it as fact rather than an open question.

---

## Results — fill in and report back

| Check | Result | Evidence (run_id / error_code / wrapper shape) |
|-------|--------|-----------------------------------------------|
| A — `queued → running` | ☐ PASS ☐ FAIL | run_id: ______  saw `running` at: ______ |
| B — `INVALID_PARAMS` | ☐ PASS ☐ FAIL | error_code: ______ |
| C — wrapper shape (OQ2) | ☐ observed | shape: ☐ bare ☐ single ☐ double |

### After a successful run — what the developer agent will do

Paste the results table back and the developer agent will:

1. Flip tasks **1.17** and **1.27** and the **OQ2 exit criterion** from `[~]` to `[x]` in
   `workstream/tasks-prd-agent-fleet-panel-v2-wave4-plan.md`.
2. Record the OQ2 wrapper-shape finding in `docs/technical-guidelines.md` §8 (replacing the open
   question with the observed fact).
3. Post the evidence to **#89** and reference it from the S-115 tracking issue (#128).

### Helper script

`panel/scripts/verify-invoke.mjs` automates Check A: it submits an invoke to the local panel, polls
the `runs` row until it reaches `running` (or times out), and prints the row. See its `--help`.
It does **not** cover Check B/C (those need direct AWS/CloudWatch access).
