# ADR-001: LLM Fix-Agent Escape Hatch — Sandbox + Deterministic Mandate Backstop

## Status

Accepted

## Context

The `dependency-update` agent's pipeline is deterministic: audit → classify →
update → validate → open PR. Some dependency updates break the project's own
checks (lint/format/typecheck/tests) in ways a deterministic pass cannot repair
— a renamed export, a stricter type, a changed function signature. Without a
repair step, every such update dead-ends at `VALIDATION_FAILING` and requires a
human, defeating the agent's purpose for a large class of updates.

Issue #75 introduced an LLM "escape hatch" to adapt **source code** so the
checks pass again. This raises three concerns that the foundation docs did not
previously cover:

1. **Security posture of giving a model tools.** The model can read/write files
   and run shell commands inside a cloned repository that also holds a
   short-lived GitHub token and runs under the Supabase service-role key (D15,
   R2). An unconstrained tool surface is a workspace-escape and
   arbitrary-write risk.
2. **The mandate problem.** The whole point of the agent is to apply *safe*
   dependency updates. A model told to "make the checks pass" can trivially do
   so by rolling back the update, widening a semver range, deleting a test, or
   removing a dependency — silently defeating the security intent.
3. **Doc drift.** `technical-guidelines.md` §11 still claimed "no formalized
   test suite exists," and §16 declared the agent's LLM client "outside the
   scope of this document." Both are now false: a `pytest` suite exists and
   `strands-agents` is a committed runtime dependency.

The pre-existing repo rule — "treat human PR review as the actual gate" — is a
backstop for git operations, not a substitute for a machine-enforced guarantee
on what the model may change.

## Decision

1. **The LLM sits outside the deterministic path, reachable from one edge only.**
   It is invoked solely when validation fails after a dependency update, in
   `llm_fix` mode, with `max_fix_attempts > 0`. It never judges vulnerabilities,
   selects versions, or writes the PR body.
2. **Exactly five sandboxed tools** (`shell`, `read_file`, `write_file`,
   `find_files`, `grep_code`). Every path-taking tool resolves against the
   workspace root through `_safe_path`, which refuses absolute paths, `../`
   traversal, and symlink escapes (verified against the real path via
   `os.path.realpath`). `shell`/`find_files`/`grep_code` are confined to the
   workspace cwd.
3. **The system prompt states the mandate** (no test-weakening, no dependency
   rollback, no range widening / major bump, no dependency add/remove, no
   lockfile edits) — but the prompt is treated as guidance, not control.
4. **A deterministic backstop enforces the mandate.** After the bounded,
   re-validating loop, `verify_no_mandate_violation` compares `package.json`
   dependency specifiers against the post-deterministic-update snapshot. Any
   widened range, major bump, or added/removed dependency terminates the run
   `failed` / `needs_review` / `MANDATE_VIOLATION` and blocks PR creation.
5. **`strands-agents` (Strands + Amazon Bedrock) is a committed agent runtime
   dependency**, model selectable via `MODEL_ID` (default
   `us.anthropic.claude-sonnet-4-6`). The vendored `agent_reporter.py` remains
   byte-identical to `docs/reference/agent_reporter.py`; a per-module mypy
   override suppresses only the `exit-return` code for that file so the
   typecheck gate stays clean without editing the vendored copy.
6. **Foundation docs are corrected to current state:** §6 gains the sandbox +
   mandate rule, §11 is replaced with the implemented pytest layer taxonomy
   (deferring detail to `TESTING.md`), and §16 records the Strands/Bedrock
   dependency and the mypy override.

## Alternatives Considered

- **Prompt-only enforcement (no deterministic check).** Rejected: a system
  prompt is not a guarantee. A model that widens a range still produces green
  checks, so the security intent would be silently defeated with no signal.
- **Broad/unbounded tool access (or a general filesystem tool).** Rejected:
  larger attack surface for workspace escape and out-of-tree writes, with no
  corresponding benefit for the narrow "fix source to match new deps" task.
- **No escape hatch at all (human handles every validation break).** Rejected:
  discards the agent's value for the common, mechanical breakages that dominate
  dependency updates.
- **Re-verify the update via a literal pre-update baseline.** Rejected in favor
  of a post-deterministic-update snapshot: the deterministic `pnpm/npm update`
  legitimately changes in-range specifiers, so a pre-update baseline would
  false-positive; the post-update baseline isolates exactly the model's changes.

## Consequences

**Positive**

- The model can repair mechanical breakages without being able to subvert the
  update's security purpose — the violation path is machine-enforced, not
  trust-based.
- Workspace-escape and out-of-tree writes are blocked at the tool boundary and
  covered by tests (traversal/absolute/symlink/null-byte).
- Foundation docs now match implemented reality (testing surface + dependency
  set), reducing onboarding drift.

**Negative / trade-offs**

- Bedrock/Strands is now on the agent's critical path for `llm_fix` runs,
  adding cost, latency, and a model-availability dependency (bounded by
  `max_fix_attempts` and `TOOL_COMMAND_TIMEOUT`).
- `shell` still permits arbitrary commands within the workspace cwd; isolation
  rests on the container boundary and cwd confinement, not on command
  allowlisting.
- No Layer 3 evaluation harness exists for the LLM output; correctness of a
  "fix" is asserted only by the re-run validation suite, not by semantic evals.

**Follow-up actions**

- Persist `llm_used` / `fix_attempts` into `runs.metrics` (deferred to #76/#77;
  values are computed and returned in the entrypoint payload today).
- Emit the test-output tail as a `run_artifact` on budget exhaustion (deferred
  to #76, which owns PR/artifact plumbing).
- Reconcile PRD requirement 50 wording ("pre-update state" → "post-
  deterministic-update state") so spec and code agree (product-engineer).

## Related

- Requirements:
  - `docs/requirements/prd-dependency-update-agent.md` (§2.1 pipeline shape,
    reqs 44–52)
  - `docs/requirements/prd-agent-fleet-panel-v2.md` (`fix_mode` parameter)
- Workstream:
  - `workstream/fidelity-report-75.md` (audit-mode fidelity report for #75)
- Docs updated:
  - `docs/technical-guidelines.md` (§6, §11, §16, changelog 1.2)
  - `agents/dependency-update/README.md` (Pipeline / LLM fix loop, env vars)
- Implementation:
  - `agents/dependency-update/app/dependencyUpdate/fix_agent.py`
  - `agents/dependency-update/app/dependencyUpdate/main.py`
  - `agents/dependency-update/app/dependencyUpdate/pyproject.toml`
