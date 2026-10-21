# Research: bug-fix agent HOW-phase spec inputs

**Scope:** Agent Fleet Control Plane. Bug-fix agent (`agents/bug-fix/`) specification preparation, drawing from sibling `security-analyst` and `dependency-update` agents.

**Date:** 2026-10-18  
**Repository:** llipe/dev-tasks-agent-fleet  
**Base branch:** main  
**Commit SHA:** 49c3314 (Merge PR #325, PRD v1.1 and WHAT decision log merged)  
**Invoking agent:** N/A (researcher invoked directly for HOW-phase planning)  
**Research question:** 10 specific questions on sibling agent architecture, contracts, deployment, and panel rendering (per PRD §12 Technical Considerations and Open Questions §18.1-8).

---

## Answer Summary

Sibling agents (`security-analyst`, `dependency-update`) share modular structure across agent_reporter, credentials, heartbeat, signal_backstop, scrubber, and pull_request. Reporting uses existing `run_outcome` enum (no migration needed). Scheduler G5 and G1 gates key on `(agent_id, repository_id)` without reference to `issue_number`. GitHub App tokens are minted on-demand via RS256 JWT; issue write permission status unverified. Deployment is ARM64-only Python containers with entrypoint config in `agentcore.json`; `MODEL_ID` env var is default `us.anthropic.claude-sonnet-4-6`. Seed rows carry `default_params` and `params_schema` for all params including labels (D-44–D-46 unresolved in UI form submission). Toolchain detection in `toolchain.py` covers pnpm/npm only (JS/TS); Python Makefile targets are named in D-19 but not yet implemented. CLI subprocess execution includes timeouts and env scrubbing via `scrubber.py`. Panel run-summary rendering maps outcome values to display labels in `run-row.ts` (`needs_review` → "NEEDS REVIEW", `not_applicable` → "N/A").

---

## Q1: Sibling agent module structure

| Module | Location | Shared? | Contract |
|--------|----------|---------|----------|
| `agent_reporter.py` | `agents/{agent}/app/{AgentCase}/agent_reporter.py` | Both | Reporting lifecycle: `start()`, `succeed(outcome)`, `fail(error_code)`, `step()`, `log()`, `artifact()`. Reads `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `RUN_ID`, `RUN_PARAMS` env; buffers `run_events` (50 or 2sec flush), writes `run_steps`, `run_artifacts` (lines 205–388). No dependencies: stdlib + urllib. |
| `credentials.py` | agents/{agent}/app/{AgentCase}/credentials.py | Both | Resolves GitHub App installation from Supabase, fetches PEM from AWS Secrets Manager, mints RS256 JWT, exchanges for installation token via `POST /app/installations/{id}/access_tokens`. Returns `TokenContext(token, issued_at, installation_id)`. Refreshes if stale (>45 min). (lines 1–224) |
| `heartbeat.py` | agents/{agent}/app/{AgentCase}/heartbeat.py | Both | Periodic ping to keep run's `last_heartbeat_at` current, preventing reaper timeout (D1 contract). Interval ≤ 60% of `max_runtime_seconds`. |
| `signal_backstop.py` | agents/{agent}/app/{AgentCase}/signal_backstop.py | Both | Catches SIGTERM, applies disposition-like terminal event (`failed` + error_code). Fallback for hard kills and timeouts when wrapper's own finally-block cannot run. |
| `scrubber.py` | agents/{agent}/app/{AgentCase}/scrubber.py | Both | Removes secrets (GitHub token, Supabase key) from all text output, subprocess stdout/stderr, error messages. Called before logging any error path. (lines 1–32) |
| `pull_request.py` | agents/{agent}/app/{AgentCase}/pull_request.py | Both | Opens Draft PR: clones, checks out branch, stages/commits, pushes, calls GitHub API to create PR. Body always via `--body-file` (no inline multiline in API payload). Records `pull_request` artifact with PR metadata. (23,724 bytes in security-analyst; 18,174 in dependency-update — different fixers/validation). |
| `toolchain.py` | agents/dependency-update/app/dependencyUpdate/toolchain.py | dependency-update only | Detects package manager (pnpm/npm via packageManager field → lockfile → fail), resolves scripts in package.json (test mandatory, lint/format/typecheck optional with variants). Returns `ScriptContract` with resolved script names. Not in security-analyst. |

**Summary:** Six modules shared across both agents; `pull_request.py` is duplicated (not symlinked) to allow agent-specific customization (commit message, rationale template). `toolchain.py` is dependency-update-only; no Python equivalent shipped yet (D-19 unresolved).

---

## Q2: Reporting contract — outcomes, error codes, artifact recording

### Run outcomes (enum `run_outcome`, no migration)

Source: `supabase/migrations/20260902200101_initial_schema.sql:16-18`

```sql
create type run_outcome as enum (
  'fixed', 'partial', 'no_vulnerabilities', 'needs_review', 'not_applicable'
);
```

**agent_reporter.py** defines methods:

- `succeed(outcome: str, result: dict | None = None, metrics: dict | None = None)` — records `status='succeeded'` + named outcome + optional result dict and metrics. Outcomes documented at line 279: `fixed | partial | no_vulnerabilities | needs_review | not_applicable`. Only pre-existing values used.
- `fail(error_code: str, error_message: str, outcome: str | None = None, ...)` — records `status='failed'` + `error_code` + `error_message` (truncated to 2000 bytes) + optional outcome and metrics.

**Error codes:** Not enumerated in schema; caller-defined strings. Examples from `reap_stale_runs()` (lines 277–281):
- `RUNTIME_TIMEOUT` — max_runtime + grace exceeded
- `START_TIMEOUT` — never reported started

Agent must define its own error codes for credential failures, clone failures, CLI crashes, etc.

### run_steps / run_events writing

- **run_steps:** Created on `step()` entry (line 315–320), updated on exit with status (`succeeded|failed|skipped`), `finished_at`, optional `error_message`. Sequential `seq` per run.
- **run_events:** Appended on `log()` (level: debug|info|warn|error), buffered and flushed every 50 events or 2 seconds (lines 346–348, 355–361). Include `step_id` (null if no active step), `message` (max 8192 bytes), `data` dict.

### pull_request artifact

- **Type:** `pull_request` (artifact_type enum, line 23)
- **Fields:** `run_id`, `type='pull_request'`, `title` (optional, PR title), `url` (PR URL), `metadata` (jsonb, agent-supplied dict)
- **Recording:** `run.artifact('pull_request', url=pr.url, title=pr.title, ...)` (agent_reporter.py:365–371)
- **G5 keying:** Scheduler queries `run_artifacts a WHERE a.type='pull_request'` joined to runs; if any unresolved (created after `pr_block_cleared_at`, no superseding manual run), schedule is blocked (G5_open_pr.sql:29–52).

---

## Q3: G5 open-PR backoff — keying logic

Source: `supabase/migrations/20261013165000_scheduler_g5_open_pr.sql`

**Function:** `scheduler.open_pr_block_run(p_agent_id uuid, p_repository_id uuid, p_cleared_at timestamptz) returns uuid`

**Keys on:**
1. `(agent_id, repository_id)` — same agent-repo pair
2. `pr_block_cleared_at` — manual clear timestamp (nullable; null = never cleared)

**Unresolved criteria (lines 43–51):**
- PR artifact `created_at > p_cleared_at` (G5-c: not manually cleared) AND
- No later MANUAL `trigger_type='manual'` run of same `(agent_id, repository_id)` exists (G5-a: not superseded)

**No explicit issue_number keying.** Returns the most-recent PR run's id, or null if resolved.

**In fire_due_schedules:**
- G1 overlap check first (lines 108–113): `has_active_run(agent_id, repo_id)` → block on 'overlap'
- G5 open-PR check second (lines 116–124): `open_pr_block_run(...)` → block on 'open_pr' if non-null
- Both auto-clear on next tick if condition resolves (lines 87–97)

---

## Q4: G1 overlap suppression — keying logic

Source: `supabase/migrations/20261013164000_scheduler_g1_overlap.sql`

**Function:** `scheduler.has_active_run(p_agent_id uuid, p_repository_id uuid) returns boolean`

**Keys on:**
1. `agent_id` — not repository-generic (one agent may run many repos)
2. `repository_id` — nullable (some agents may not require one)

**Active definition (lines 25–31):**
```sql
select exists (
  select 1 from v_runs
   where agent_id = p_agent_id
     and repository_id is not distinct from p_repository_id  -- null-safe equality
     and effective_status in ('queued', 'running')
)
```

Uses `v_runs.effective_status` (not raw `status`), so a stale `running` past reaper threshold reads as `timed_out` and does NOT block.

**No issue_number in the gate.** (D-10/D-44 applies to selection, not scheduling guards.)

---

## Q5: GitHub App credentials — token minting and permissions

Source: `agents/security-analyst/app/securityAnalyst/credentials.py` (same in dependency-update)

### Token minting (lines 152–181)

```python
def mint_installation_token(app_id: int, installation_id: int, pem: str) -> str:
    now = int(time.time())
    assertion = jwt.encode(
        {"iat": now - 60, "exp": now + 540, "iss": str(app_id)},
        pem,
        algorithm="RS256",
    )
    resp = requests.post(
        f"https://api.github.com/app/installations/{installation_id}/access_tokens",
        headers={"Authorization": f"Bearer {assertion}", "Accept": "application/vnd.github+json"},
        timeout=30,
    )
    return resp.json()["token"]
```

JWT valid 9 minutes (iat - 60s for clock skew, exp + 540s). Each install gets a fresh short-lived token.

### Installation lookup

Queried from `github_installations` table (Supabase) via PostgREST (lines 79–116):
```python
url = f"{supabase_url}/rest/v1/github_installations?github_org_slug=eq.{org}&is_enabled=eq.true&select=app_id,installation_id,private_key_secret_arn"
```

Returns `(app_id, installation_id, private_key_secret_arn)`.

### Permissions

**Requested/assumed:** The PRD (§12, line 188) notes "**GitHub App permissions.** The agent needs issue write (assign, labels, comments) in addition to contents and pull-request write. **Whether the existing installation grants issue write is unverified.**"

**Current use in agents:**
- `security-analyst` pull_request.py: no issue mutations (PRs only)
- `dependency-update` pull_request.py: no issue mutations (PRs only)

**For bug-fix agent (FR-7, FR-22):** Claim and disposition comments, label changes, assignee changes. Requires issue write. **Status: unverified — must confirm at GitHub App config time.**

---

## Q6: Deployment & infra — scripts, Dockerfile, agentcore config, ARM64, IAM policy, MODEL_ID

### Dockerfile & Base Image

Both agents: `Python:3.13-slim` base (ARM64 native confirmed). (security-analyst Dockerfile line 15, dependency-update line 10)

**Architectures:**
- dependency-update: Node 26 multi-stage (copies node_modules + pnpm to Python image)
- security-analyst: CodeQL, Gitleaks, Trivy (Go binaries), plus node-only for CodeQL JS/TS support

All pinned to ARM64 releases (codeql-linux-arm64.zip, trivy_..._Linux-ARM64.tar.gz, gitleaks_..._linux_arm64.tar.gz).

### agentcore.json

Source: `agents/{agent}/agentcore/agentcore.json`

**Structure (both agents):**
```json
{
  "name": "dependencyupdate" | "securityanalyst",
  "runtimes": [{
    "name": "dependency_update" | "security_analyst",
    "build": "Container",
    "entrypoint": "main.py",
    "codeLocation": "app/dependencyUpdate/" | "app/securityAnalyst/",
    "runtimeVersion": "PYTHON_3_14",
    "networkMode": "PUBLIC",
    "protocol": "HTTP",
    "envVars": [
      { "name": "SUPABASE_URL", "value": "https://hegxeycmbmjfgzqpdiik.supabase.co" },
      { "name": "SUPABASE_KEY_SECRET_ID", "value": "agent-fleet/prod/SUPABASE_SERVICE_ROLE_KEY" },
      { "name": "MODEL_ID", "value": "us.anthropic.claude-sonnet-4-6" }
    ],
    "lifecycleConfiguration": {
      "idleRuntimeSessionTimeout": 900,
      "maxLifetime": 3600 | 5400  -- JS/TS 3600s, Python 5400s
    }
  }]
}
```

**MODEL_ID:** Default `us.anthropic.claude-sonnet-4-6` (Bedrock model endpoint). Resolved by agent entrypoint (main.py) to CLI parameter. **Exact CLI mapping not found in codebase** (PRD open Q1).

### Deployment script

Source: seed at line 53-118 (`supabase/seed.sql`)

```sql
insert into agents (
  slug, name, version,
  runtime_arn, runtime_qualifier,
  max_runtime_seconds, grace_seconds, start_timeout_seconds,
  default_params, params_schema
) values (
  'dependency-update', 'Dependency Update', '0.1.0',
  'arn:aws:bedrock-agentcore:us-east-1:755641879575:runtime/dependencyupdate_dependency_update-UsQc5U5Yz0',
  'DEFAULT',
  3600, 120, 300,
  '{"fix_mode":"audit_only",...}'::jsonb,
  $json${...JSON Schema...}$json$::jsonb
) on conflict (slug) do update set ...
```

**runtime_arn** reported by `agentcore status` after deploy (issue #77, noted at line 64). **Seed comment (lines 45–50):** "max_runtime_seconds MUST match maxLifetime in agentcore.json", "start_timeout_seconds is the queue clock, NOT idleRuntimeSessionTimeout".

### Panel invoke-runtime IAM policy

**Not found in codebase.** PRD §12 (line 186) and issue #280 context note: "the panel's `invoke-runtime` IAM policy (it lists runtime and `runtime-endpoint/DEFAULT` ARNs explicitly; a new runtime is not covered without an entry)". **Policy is AWS CloudFormation or Terraform, not version-controlled in this repo or awaiting `infra-engineer` pass.**

Invoke occurs via `panel/lib/aws/invoke.ts:56–89` (`BedrockAgentCoreClient.send(InvokeAgentRuntimeCommand)`), which requires IAM permission to `bedrock-agentcore:InvokeAgentRuntime` on the runtime ARN.

---

## Q7: Seed shape — agents row, default_params, params_schema, runtime_arn

Source: `supabase/seed.sql:53–118` (dependency-update example)

```sql
insert into agents (
  id, slug, name, description, version,
  runtime_arn, runtime_qualifier,
  requires_repository, max_runtime_seconds, grace_seconds, start_timeout_seconds,
  default_params, params_schema,
  is_enabled, created_at, updated_at
)
values (
  gen_random_uuid(),
  'dependency-update',
  'Dependency Update',
  'Runs npm audit against a repository...',
  '0.1.0',
  'arn:aws:bedrock-agentcore:us-east-1:755641879575:runtime/dependencyupdate_dependency_update-UsQc5U5Yz0',
  'DEFAULT',
  true,
  3600,  -- max_runtime_seconds (MUST match agentcore.json maxLifetime)
  120,   -- grace_seconds
  300,   -- start_timeout_seconds
  '{"fix_mode":"audit_only","fail_on_findings":true,"max_fix_attempts":3}'::jsonb,
  $json${ "type": "object", "additionalProperties": false, "required": ["fix_mode"],
    "properties": { "fix_mode": {...}, "fail_on_findings": {...}, "max_fix_attempts": {...} } }$json$::jsonb,
  true, now(), now()
)
on conflict (slug) do update set name = excluded.name, ...;
```

**For bug-fix agent, required additions (from PRD FR-1, FR-1a):**

```sql
default_params: {
  "repo": null,  -- or define a structure? (open)
  "issue_number": null,
  "assignee": null,
  "select_labels": ["type: bug", "status: ready"],
  "claim_remove_labels": ["status: ready"],
  "claim_add_labels": ["status: in-progress"],
  "disposition_add_labels": ["status: needs-refinement"],
  "max_turns": 40,
  "cli_timeout_minutes": 30,
  "run_lifetime_minutes": 60
}

params_schema: {
  "type": "object",
  "additionalProperties": false,
  "required": ["repo"],
  "properties": {
    "repo": { "type": "string", "pattern": "^[^/]+/[^/]+$" },
    "issue_number": { "type": ["integer", "null"], "minimum": 1 },
    "assignee": { "type": ["string", "null"] },
    "select_labels": { "type": "array", "items": {"type": "string"}, "minItems": 1 },
    "claim_remove_labels": { "type": "array", "items": {"type": "string"} },
    "claim_add_labels": { "type": "array", "items": {"type": "string"}, "minItems": 1 },
    "disposition_add_labels": { "type": "array", "items": {"type": "string"} },
    ...
  }
}
```

**Decision D-47 status:** Label arrays are **stored in `schedules.params` (jsonb) and validated server-side**, but **panel form does not submit them** (lines 70–77 of `panel/lib/schema/form.ts` map `items` → unsupported). Manual invoke / schedule fire both validate and forward arrays if present; neither route merges `agents.default_params` server-side. **Unresolved gap: panel form UI for label parameters.**

---

## Q8: Toolchain detection — pnpm/npm behavior, Python/Makefile handling

Source: `agents/dependency-update/app/dependencyUpdate/toolchain.py` (JS/TS only) + D-19 decision

### JS/TS (toolchain.py, lines 1–258)

**Package manager detection (lines 96–125):**
1. `packageManager` field in package.json (e.g. `"pnpm@9.1.0"`)
2. `pnpm-lock.yaml` → pnpm
3. `package-lock.json` → npm
4. Fail: `ToolchainError('NO_PACKAGE_MANAGER', ...)`

**Script detection (lines 221–257):**
- Reads `package.json` scripts
- Mandatory: `test`
- Optional with variants: `lint` (lint), `format` (format, format:check), `typecheck` (typecheck, type-check)
- Returns `ScriptContract(test, lint, format, typecheck, lint_fix, format_fix, missing_optional)`

**pnpm version resolution (lines 128–162):**
- `packageManager` field → major version
- `pnpm-lock.yaml` lockfileVersion → major (9→9, 6→8, 5→7)
- `ensure_pnpm_version()` installs correct major if current does not match

### Python (not yet implemented, D-19 accepted but unresolved)

From decision D-19: "Canonical gate names as `package.json` scripts (JS/TS) or **`Makefile` targets (Python)**".

**What is needed (PRD §6, D-19, open Q5):**
- Detect Python repo (presence of `Makefile` with canonical targets?)
- Read targets: `test`, `lint`, `format`, `format-check`, `typecheck`
- Mechanism to locate and run changed tests (pytest paths; D-15 red-to-green)

**Current gap:** No `toolchain.py` equivalent for Python. Must define:
- Detection rule (Makefile only? pyproject.toml markers?)
- Make target names (assume POSIX `make test`, `make lint`, etc.?)
- Test file discovery for red-to-green validation

---

## Q9: CLI subprocess execution — env scrubbing, timeouts, kill patterns

Source: `agents/dependency-update/app/dependencyUpdate/` (representative; security-analyst mirrors)

### Subprocess execution pattern

**validator.py:65–74** (canonical pattern)

```python
def _run(cmd: list[str], cwd: str, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
        timeout=timeout,
    )
```

**Timeout values (config.py):**
- `TOOL_COMMAND_TIMEOUT` — lint, format, typecheck (typically 30–60s per tool)
- `TEST_TIMEOUT` — test script (typically 300s or more, tunable)
- Named constants prevent magic numbers

**No env manipulation visible.** Subprocess inherits parent env (which is scrubbed before logging).

### Environment scrubbing (scrubber.py:10–31)

```python
def scrub(text: str, secrets: list[str]) -> str:
    for s in secrets:
        if s and s in text:
            text = text.replace(s, "***")
    return text

def scrub_process_error(exc: subprocess.CalledProcessError, secrets: list[str]) -> None:
    exc.cmd = scrub(cmd_str, secrets)
    exc.stderr = scrub(exc.stderr, secrets)
    exc.stdout = scrub(exc.stdout, secrets)
```

**Applied to:** All error paths before logging/reporting. Secrets list built from GitHub token + Supabase key (agent_reporter and credentials objects).

### CLI wall-clock timeout (bug-fix agent, FR-12, D-22)

**Not yet implemented, but specified:**
- `--max-turns` 40 (Claude CLI flag, model decision boundary)
- CLI wall-clock kill: 30 minutes (wrapper-managed subprocess timeout)
- Whole-run lifetime: 60 minutes (database-side reaper)

**No OS-level kill signal visible** in existing agents (they run synchronously to completion and respect Python subprocess timeout). Bug-fix agent must add explicit `subprocess.timeout` or `signal.alarm()` (SIGALRM) for wall-clock enforcement.

---

## Q10: Panel run-summary rendering — needs_review / not_applicable outcomes

Source: `panel/lib/domain/run-row.ts:95–111`

```typescript
export function outcomeLabel(outcome: RunOutcome | null): string {
  switch (outcome) {
    case "fixed":
      return "FIXED";
    case "no_vulnerabilities":
      return "NO VULNS";
    case "partial":
      return "PARTIAL";
    case "needs_review":
      return "NEEDS REVIEW";
    case "not_applicable":
      return "N/A";
    default:
      return "—";
  }
}
```

**Rendering locations:**
1. **Run history row** — `panel/components/RunHistoryRow` calls `outcomeLabel()` and renders as a tag (§8.2 of design doc, uppercase, colored by status)
2. **Pages:** `/agents/[slug]` (line 234 of page.tsx), `/runs/[id]` (line 229), `/` (line 149) all query and pass `outcome` to the shaper
3. **Shaper** (`buildRunRow`, line 179): `outcomeLabel: outcomeLabel(run.outcome)`, `hasOutcome: run.outcome != null`

**Display:**
- `needs_review` → green background (succeeded status) + "NEEDS REVIEW" label (PR opened but human review required; only outcome that leaves run in succeeded state without a finished work product)
- `not_applicable` → yellow/gray background (gating failure, no work attempted) + "N/A" label

**Tests:** `panel/tests/unit/run-row.test.ts` line 40–42:
```typescript
expect(buildRunRow(run({ outcome: "needs_review" }), T0).outcomeLabel).toBe("NEEDS REVIEW");
```

---

## Not Investigated

1. **PRD Open Questions 2–8 (HOW phase, deferred to spec):** CLI model authentication, allowed-tools set enforcement, code-file classification rule, claim-marker format (bot-identity verification), "open linked PR" detection algorithm, red-to-green test locator (pytest path rules), GitHub App issue-write confirmation, default assignee resolution.
2. **Python Makefile contract:** Exact target names, test-file discovery for red-to-green, relationship to `pyproject.toml`.
3. **Panel IAM policy document:** CloudFormation/Terraform source (not in this repo; awaits infra-engineer review per issue #280).
4. **D-47 unresolved:** Panel form submission for label-array params (form.ts line 70–77 currently routes to unsupported).

---

## Confidence

**High (85%)** for Q1–Q3, Q5, Q7, Q10 (existing code, schema enums, tests).  
**Medium (70%)** for Q4 (null-safe equality and effective_status derivation documented, but issue_number integration not tested in scheduler context).  
**Medium (65%)** for Q6 (Dockerfile and agentcore.json clear; MODEL_ID mapping to CLI not found; IAM policy is external).  
**Medium (65%)** for Q8 (JS/TS complete; Python contract from D-19 but not implemented).  
**High (90%)** for Q9 (subprocess patterns clear; wall-clock enforcement unimplemented but specified).

---

## Relationships

- **G1/G5 scheduling:** Both key `(agent_id, repo_id)`, orthogonal to `issue_number` (selection gate only, not scheduling guard). Bug-fix agent receives no scheduling changes; default-params merging must occur server-side in fire endpoint (panel/app/api/internal/schedules/[id]/fire/route.ts:124).
- **Toolchain precedent:** dependency-update's pnpm/npm detection and script reading is the reference implementation for JS/TS (reusable). Python must follow same pattern (detect, resolve, return contract) but is unimplemented.
- **Credentials:** GitHub App token minting is identical across agents; bug-fix agent reuses `credentials.py` unchanged. Issue-write permission must be confirmed at GitHub App config time (gap noted in PRD §12).
- **Red-to-green validation (D-15):** validator.py's subprocess timeout and output capture patterns are reusable. Test locator (changed test files, per-runner paths) is the unresolved piece shared with Python contract.

---

## External Sources

- Issue #280: panel `invoke-runtime` IAM policy scope (referenced in PRD §12, not resolved in code)
- Issue #77: runtime_arn reporting after `agentcore deploy` (dependency-update seed notes this)

---

## Changelog

| Version | Date       | Changes |
|---------|------------|---------|
| 1.0     | 2026-10-18 | Initial research; answers Q1–Q10 per PRD §18; records D-47 unresolved gap (panel form label params); identifies Python Makefile contract and GitHub App issue-write as unverified assumptions. |
