### Verifier audit — #145 (lockfile snapshot timeout fix)

**Fidelity: High.** Grey-box audit against the delivered change.

| Check | Evidence | Verdict |
| ----- | -------- | ------- |
| No crash on timeout | `test_timeout_degrades_to_empty_snapshot` (returns `{}`, does not raise) | PASS |
| Metric-only degradation, pipeline completes | snapshot feeds `packages_changed` only; returns `{}` on failure | PASS |
| Dedicated larger budget | `test_snapshot_uses_dedicated_lockfile_timeout` — 300 s, `> TOOL_COMMAND_TIMEOUT` | PASS |
| Clock invariant preserved | new `0 < LOCKFILE_SNAPSHOT_TIMEOUT <= TEST_TIMEOUT` relation + rejection tests; shipped-config check passes | PASS |
| Non-zero exit that still prints JSON is parsed | `test_nonzero_exit_with_output_still_parses` | PASS |
| Critical path unchanged | `run_audit` still raises (deliberate); `diff_packages`/`count_advisories_fixed` untouched | PASS |
| No scope creep | only `audit.py`, `config.py`, 2 test files; no schema/data/API change | PASS |

**Drift:** one intentional behavior-contract change — `snapshot_lockfile_packages` raise→`{}`. This *is* the fix; the single test asserting the old raise-behavior was updated. No unintended drift.

**Gates:** `make validate-py` green — ruff + format + mypy clean, **452 passed**, `pip-audit` clean.

**Deploy caveat:** this is a deployed AgentCore artifact; the fix takes effect on the live agent only after a runtime rebuild + redeploy (carried into S-115).

`coverage_gate: PASS` (new/changed lines in `snapshot_lockfile_packages` and the invariant relation are all exercised).
