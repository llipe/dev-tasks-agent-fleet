# ADR-004: Schedule the `pg_cron` reaper and record its verified behaviour

## Status

Accepted

## Context

`reap_stale_runs()` and the `v_runs.effective_status` view were written into
`docs/reference/001_schema.sql` from the first migration, implementing the
two-layer stale-run design described in `docs/technical-guidelines.md` §3
(layer 1 materializes state via `pg_cron`; layer 2 computes `effective_status` at
read time). The `cron.schedule` call at the tail of that file was left
**commented out**, pending manual enablement of the `pg_cron` extension in the
Supabase dashboard.

Issue #77 closed the deployment and E2E path for the `dependency-update` agent
but never covered the reaper — `docs/runbooks/issue-77-deployment-e2e.md`
contains no mention of `pg_cron`, `reap_stale_runs()`, `timed_out`, or
`failed_to_start`. The scheduling command survived only in the superseded
`workstream/pending-manual-config-dependency-update-agent.md` step 5. Four
Phase 1 acceptance criteria depended on the reaper and none had been exercised.

The failure mode this left open is unusually deceptive. Because the panel derives
displayed status from `v_runs.effective_status` (computed at read time, PRD
FR11a), **an unscheduled reaper still renders the correct status in the UI.** The
database is wrong while the interface looks right:

- the explanatory `run_events` row that `reap_stale_runs()` writes is never
  written, so a run would show a terminal status with no reason — contradicting
  `product-context.md` success metric 3;
- `runs.status` stays `queued`/`running` indefinitely, so the parent PRD's
  "absence of executions stuck indefinitely" metric is unmet while appearing met;
- anything not reading through `v_runs` (manual SQL, future retention logic,
  reports) sees the wrong state.

Issue #94 activates the schedule and verifies the behaviour end to end.

## Decision

1. **Activate the schedule in the schema reference.** The `create extension if
   not exists pg_cron;` and
   `select cron.schedule('reap-stale-runs', '* * * * *', $$select reap_stale_runs()$$);`
   statements at the tail of `001_schema.sql` are **uncommented**, so the
   reference file reflects the deployed state rather than a pending intention. The
   explanatory comment about enabling the extension from the Supabase dashboard is
   retained, because `create extension` still requires sufficient privilege.

2. **Record the verification in a dedicated operator runbook.** The scheduling
   step and all acceptance-criteria results live in
   `docs/runbooks/issue-94-reaper-verification.md` rather than as a section of the
   #77 runbook. The reaper content is substantial (scheduling plus five
   verification tasks plus a troubleshooting index) and has a different lifecycle
   from the one-time deployment steps; the #77 runbook cross-links to it.

3. **Record the verified reaper properties in `technical-guidelines.md` §18**, so
   the confirmed behaviour and the accepted tradeoff are discoverable from the
   foundation doc and not only from a runbook.

4. **Route the defects the verification surfaced to their own issues** rather than
   expanding #94. The reaper behaved correctly in every observed case; the four
   defects live elsewhere in the stack (#97, #98, #99, #100). The verification steps
   that could not be executed are likewise routed to a single follow-up (#101)
   instead of holding #94 open.

## Verified behaviour

Confirmed against real run `f63ac9f3-14b0-4157-9484-f2f6b062f846`, an
`llm_fix` invocation that hung during its `validate` step and never reported
terminal status — the exact failure class the reaper exists to cover:

| Property | Evidence |
|---|---|
| Fires at the threshold, never early | Reaped at `elapsed 3732.30 s` against `max_runtime 3600 + grace 120 = 3720 s` — 12.3 s late, inside one cron tick |
| Writes the explanatory event | `seq=10`, `level=error`, `reason=RUNTIME_TIMEOUT`, `reaped_by=reap_stale_runs` |
| `seq` monotonicity holds | Agent had written `seq` 1–9; the reaper took `max(seq)+1 = 10`, no `uq_run_events_seq` collision |
| Two-layer design behaves as specified | `v_runs` read `running` pre-threshold, then both `status` and `effective_status` agreed `timed_out` after materialization |
| `failed_to_start` branch works on a genuine orphan | Run `cba355cb-…` (agent never started, `started_at` null) reaped at 324 s against `start_timeout_seconds = 300`, with the `START_TIMEOUT` event |

## Alternatives Considered

- **Leave the schedule commented and document the manual step only.** Rejected:
  the command already lived in a superseded workstream file and had been missed
  once by #77. Encoding it in the schema reference is what makes it discoverable
  with the DDL it belongs to.
- **Add the reaper content as a section of the #77 runbook.** Rejected on size and
  lifecycle grounds; cross-linked instead.
- **Build the Phase 2 panel first and verify the reaper through the UI.**
  Explicitly rejected in the issue: the view masks an unscheduled reaper, so
  building the panel first would hide a live defect behind a correct-looking
  interface.
- **Verify with real long-running agent invocations only.** Not viable — the
  seeded thresholds imply a 62-minute wait per case, and #98 currently prevents
  long runs from completing at all. Synthetic rows with backdated timestamps and
  small snapshotted thresholds (safe because thresholds are per-run snapshots, D8)
  verify the same code paths in minutes.

## Consequences

**Positive.**

- The last Phase 1 infrastructure gap is closed; stale runs now reach a terminal
  state with a written reason instead of hanging indefinitely.
- The two-layer contract is empirically confirmed rather than assumed, which
  matters because Phase 2's panel duplicates the view's `case` expression in
  TypeScript (parent PRD §616-620) and needs a pinned reference behaviour.
- The verification produced a reusable operator runbook with a troubleshooting
  index, replacing scattered notes in a superseded workstream file.

**Negative / accepted.**

- **A ~61-minute stale window is inherent.** Because `max_runtime_seconds` mirrors
  AgentCore's `maxLifetime` (3600) plus `grace_seconds` (120), a container that
  dies early still reads `running` until the 3720 s boundary. The verified run
  died around 19:36 and was marked `timed_out` at 20:37. This is the accepted D8
  tradeoff — `last_heartbeat_at` (declared, unused in v1) is the lever if it ever
  needs tightening.
- **Reaped runs left orphan `run_steps` — resolved in #99.** As recorded at the time of this
  verification, `reap_stale_runs()` did not close open steps, unlike the agent's own failure path
  (§8), so every reaped run left an in-flight step pinned `running`. Issue
  [#99](https://github.com/llipe/dev-tasks-agent-fleet/issues/99) closed this under the present
  decision context (a small behavioural correction, not a new decision): the reaper now closes open
  `run_steps` as `failed` (`finished_at=now()`, attributing `error_message`) on both the `timed_out`
  and `failed_to_start` branches, reusing the existing `step_status` enum value (no migration). See
  `technical-guidelines.md` §7/§8.
- **This ADR is recorded on partial verification: 5 of 7 acceptance criteria.**
  AC5 (healthy long-running `llm_fix` not reaped early, plus the cold-start gap
  measurement) is blocked by #98, since no long run can currently complete; the
  synthetic interlock proof in the runbook §4.4 is the recommended substitute. AC6
  (CloudWatch fallback) was not executed. AC4 is recorded PASS on its
  `running`→`timed_out` half; the `queued`→`failed_to_start` read-time branch of the
  same `case` expression was verified by inspection, not observation. All three
  residual checks are carried by **[#101](https://github.com/llipe/dev-tasks-agent-fleet/issues/101)**
  and appear as `PENDING` in the runbook's verification status summary rather than
  being silently omitted. The decision to activate the schedule does not depend on
  them: every executed case confirmed the reaper, and the pending items concern
  the must-not-reap direction and the SDK fallback path.
- **The cold-start gap remains unmeasured.** The one attempt
  (`insert_to_start = 185.7 s`) is invalid — it includes human delay between the
  row INSERT and the `agentcore invoke`, since the panel that would do both
  atomically is Phase 2. That figure must not be cited as a measurement or fed
  into a `grace_seconds` decision. dependency-update PRD open question 8 stays open.
- **Nothing in the repo detects drift between this DDL and the deployed database.**
  The reaper, the view, and the event contract live only in `001_schema.sql`, applied
  by hand; there is no migration runner, checksum, or Layer 2.5 harness. Issue #94 was
  itself a defect of that class. See `TESTING.md` (Database / reaper layer) for the
  ranked gap analysis and the proposed harness.

## Related

- Issue [#94](https://github.com/llipe/dev-tasks-agent-fleet/issues/94) — this work
- PR [#96](https://github.com/llipe/dev-tasks-agent-fleet/pull/96)
- `docs/runbooks/issue-94-reaper-verification.md` — operator runbook and results
- `docs/reference/001_schema.sql` — `reap_stale_runs()`, `v_runs`, the schedule block
- `docs/technical-guidelines.md` §3 (two-layer design), §7 (thresholds and current
  scheduling state), §14 (reaper observability), §18 (open defects)
- `TESTING.md` — Database / reaper layer structural gap analysis
- Parent PRD `prd-agent-fleet-panel-v2.md` — FR3, FR8, FR11a, D8, D9, D10
- Follow-up defects: [#97](https://github.com/llipe/dev-tasks-agent-fleet/issues/97), [#98](https://github.com/llipe/dev-tasks-agent-fleet/issues/98), [#99](https://github.com/llipe/dev-tasks-agent-fleet/issues/99), [#100](https://github.com/llipe/dev-tasks-agent-fleet/issues/100)
- Residual verification: [#101](https://github.com/llipe/dev-tasks-agent-fleet/issues/101) — AC5, AC6, and the AC4 `queued` half
