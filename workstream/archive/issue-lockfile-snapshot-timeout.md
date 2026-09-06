## Summary

The `dependency-update` agent crashes the entire pipeline when the lockfile snapshot command (`pnpm list -r --depth Infinity --json`) exceeds its timeout on a large monorepo.

## Evidence (from a live run against `llipe/tf-ecommerce-mgmt`)

```
subprocess.TimeoutExpired: Command '['pnpm', 'list', '-r', '--depth', 'Infinity', '--json']'
timed out after 180 seconds
...
  File "/app/main.py", line 583, in invoke
    pkgs_before = snapshot_lockfile_packages(workspace, pm)
  File "/app/audit.py", line 282, in snapshot_lockfile_packages
    raise RuntimeError(f"Failed to run {pm} list: {exc}") from exc
RuntimeError: Failed to run pnpm list: Command '[...]' timed out after 180 seconds
```

The run reaches the `audit` step, then dies with an unhandled `RuntimeError`.

## Root cause

`snapshot_lockfile_packages` (added in #90 for monorepo-accurate `packages_changed`) runs a full transitive, workspace-recursive listing under the generic `TOOL_COMMAND_TIMEOUT` (180 s). On a large monorepo that walk legitimately exceeds 180 s, and the function **raises** — which propagates all the way out of `invoke` and aborts the run.

Two problems:
1. **Wrong failure mode.** This snapshot feeds the `packages_changed` **metric** only; it is not on the critical audit/update/PR path. A metric that is expensive to gather must never abort the run.
2. **Wrong budget.** A quick-tool timeout (180 s) is too small for a full transitive monorepo walk.

## Fix

- `snapshot_lockfile_packages` **degrades gracefully**: on timeout, `OSError`, non-zero exit with no output, empty output, or unparseable JSON, it logs a warning and returns `{}`. `diff_packages` then reports 0 changed packages for that run (an under-reported metric) while the pipeline completes. A non-zero exit that still prints usable JSON (npm/pnpm peer/extraneous warnings) is still parsed.
- New `LOCKFILE_SNAPSHOT_TIMEOUT` config (default 300 s, override via env), kept `<= TEST_TIMEOUT` (600 s) so the #98 clock invariant still holds. `assert_clock_invariant` now enforces `0 < LOCKFILE_SNAPSHOT_TIMEOUT <= TEST_TIMEOUT`.
- `run_audit` is intentionally left raising on timeout: the audit itself is the critical path (no audit → nothing to classify), and it is a fast command that does not share the monorepo-walk cost.

## Scope

Agent-only reliability fix (`audit.py`, `config.py`, agent unit tests). Not a Wave 4 change. Requires an AgentCore runtime rebuild + redeploy to take effect on the deployed agent.

## Tests

- `test_timeout_degrades_to_empty_snapshot`, `test_command_failure_degrades_to_empty_snapshot`, `test_nonzero_exit_no_output_degrades_to_empty`, `test_unparseable_json_degrades_to_empty`, `test_nonzero_exit_with_output_still_parses`, `test_snapshot_uses_dedicated_lockfile_timeout`.
- Clock-invariant: `test_lockfile_snapshot_timeout_within_test_timeout`, `test_lockfile_snapshot_exceeding_test_timeout_is_rejected`, `test_nonpositive_lockfile_snapshot_is_rejected`.
- `make validate-py` green: 452 passed, lint/format/typecheck/audit clean.
