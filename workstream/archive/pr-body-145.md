## fix(agent): lockfile snapshot degrades instead of crashing on timeout

Closes #145

### Problem

On a live run against a large monorepo (`llipe/tf-ecommerce-mgmt`), the `dependency-update` agent crashed in the `audit` step:

```
subprocess.TimeoutExpired: Command '['pnpm', 'list', '-r', '--depth', 'Infinity', '--json']'
timed out after 180 seconds
  File "/app/main.py", line 583, in invoke
    pkgs_before = snapshot_lockfile_packages(workspace, pm)
RuntimeError: Failed to run pnpm list: ... timed out after 180 seconds
```

`snapshot_lockfile_packages` (added in #90 for monorepo-accurate `packages_changed`) ran a full transitive, workspace-recursive listing under the generic 180 s `TOOL_COMMAND_TIMEOUT` and **raised** on timeout — aborting the entire run for what is only a **metric-gathering** step.

### Fix

- **Degrade, never crash.** `snapshot_lockfile_packages` now returns `{}` with a logged warning on timeout, `OSError`, non-zero exit with no output, empty output, or unparseable JSON. `diff_packages` then reports 0 changed packages for that run (an under-reported metric) while the audit→update→PR pipeline completes. A non-zero exit that still prints usable JSON (npm/pnpm peer/extraneous warnings) is still parsed.
- **Dedicated budget.** New `LOCKFILE_SNAPSHOT_TIMEOUT` (default **300 s**, env-overridable), kept `<= TEST_TIMEOUT` (600 s) so the #98 four-clock invariant still holds. `assert_clock_invariant` now enforces `0 < LOCKFILE_SNAPSHOT_TIMEOUT <= TEST_TIMEOUT`.
- `run_audit` intentionally still raises on timeout — the audit itself is the critical path (no audit → nothing to classify) and is a fast command, not the monorepo walk.

### Files

- `audit.py` — graceful-degrade `snapshot_lockfile_packages`; module logger.
- `config.py` — `LOCKFILE_SNAPSHOT_TIMEOUT` + invariant relation.
- `tests/unit/test_audit.py` — replaced the old "raises RuntimeError" test with degrade-to-`{}` cases (timeout, OSError, non-zero-no-output, unparseable) + the "non-zero-with-JSON still parses" and "uses the dedicated timeout" cases.
- `tests/unit/test_clock_invariant.py` — new `LOCKFILE_SNAPSHOT_TIMEOUT` relation coverage.

### Testing

`make validate-py` green: ruff + format + mypy clean, **452 passed**, `pip-audit` clean. Test-first (the timeout/degrade tests were written before the code change).

### Behavior change note

This changes a documented contract: `snapshot_lockfile_packages` previously raised `RuntimeError` on command failure and now returns `{}`. The old behavior was the bug (it crashed the pipeline); the one test asserting it was updated deliberately.

### Migration lifecycle

**Not applicable** — agent code only, no schema/data/API change.

### Deploy note

This is a **deployed** AgentCore artifact. The fix takes effect on the live agent only after an AgentCore runtime **rebuild + redeploy** — it does not change behavior of the currently-running container until then. Flagging for the S-115 deploy work.

### Scope

Standalone `dependency-update` reliability fix — **not** part of Wave 4 (which touched only the panel + the payload fixture). `audit.py` was last modified in #90.
