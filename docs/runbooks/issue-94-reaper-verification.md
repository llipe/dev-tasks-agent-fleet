# Operator Runbook — Issue #94: pg_cron Reaper Scheduling & Stale-Run Verification

> **Audience:** the human operator with Supabase SQL Editor + AWS (AgentCore, CloudWatch) access.
> **Why this exists:** scheduling the reaper touches the production Supabase database, and the
> stale-run verifications require live invocations and CloudWatch reads. None of it can be
> performed by the developer agent. The repo-side portion of issue #94 (uncommenting the
> `cron.schedule` block in `docs/reference/001_schema.sql`) is already done on branch
> `issue/94-schedule-pg-cron-reaper` (PR #96).
>
> **Location decision (sub-task 6.1):** kept as a **separate runbook** rather than a section in
> [`issue-77-deployment-e2e.md`](issue-77-deployment-e2e.md). The reaper content is substantial
> (scheduling + five verification tasks + several operational gotchas) and has a different
> lifecycle from the one-time deployment steps. The #77 runbook cross-links here.

| Field | Value |
|-------|-------|
| Issue | [#94](https://github.com/llipe/dev-tasks-agent-fleet/issues/94) |
| PR | [#96](https://github.com/llipe/dev-tasks-agent-fleet/pull/96) (draft) |
| Branch | `issue/94-schedule-pg-cron-reaper` |
| Task list | `workstream/tasks-issue-94-schedule-pg-cron-reaper.md` |
| Test plan | `workstream/test-plan-issue-94.md` |
| Schema reference | `docs/reference/001_schema.sql` (`reap_stale_runs()`, `v_runs`) |
| Region | `us-east-1` |

---

## Background — the two-layer design

Two mechanisms implement stale-run detection, and both must be verified:

| Layer | Mechanism | Timing |
|-------|-----------|--------|
| **1 — materialize** | `pg_cron` runs `reap_stale_runs()` every minute; writes the terminal `status` **and** an explanatory `run_events` row | up to 60s behind |
| **2 — read time** | `v_runs.effective_status` computes the terminal status on read | instant |

The explanatory `run_events` row exists **only** in layer 1. This is why an unscheduled reaper is
dangerous rather than merely late: `v_runs` keeps the UI looking correct while `runs.status` stays
wrong forever and the "why" event is never written.

**Two clocks, two states** (D8/D9):

| Condition | New status | Clock |
|---|---|---|
| `status='running'` and `now() > started_at + max_runtime_seconds + grace_seconds` | `timed_out` | `started_at` |
| `status='queued'` and `now() > queued_at + start_timeout_seconds` | `failed_to_start` | `queued_at` |

Thresholds are **snapshotted per run** — so synthetic rows with small values verify the mechanism
in minutes instead of the seeded 62-minute window.

---

## Prerequisites

- [x] `001_schema.sql` applied (tables, `v_runs`, `reap_stale_runs()`, RLS deny-all).
- [x] `002_seed.sql` applied (installation, repos, `dependency-update` agent with
      `max_runtime_seconds=3600`, `grace_seconds=120`, `start_timeout_seconds=300`).
- [x] Agent deployed and runtime `READY` (see [#77 runbook](issue-77-deployment-e2e.md)).

---

## 1 — Schedule the reaper (AC1)

### 1.2 Enable the extension ⚠️ live-DB change

Supabase Dashboard → **Database → Extensions** → enable `pg_cron`. Or in the SQL Editor:

```sql
create extension if not exists pg_cron;
```

- [x] `pg_cron` enabled.

### 1.3 Register the job

```sql
select cron.schedule('reap-stale-runs', '* * * * *', $$select reap_stale_runs()$$);
```

Returns a `jobid`. Safe to re-run — `pg_cron` upserts by `jobname`, so a second call updates the
existing job rather than creating a duplicate.

- [x] Job scheduled.

### 1.4 Verify the job is registered (AC1a)

```sql
select jobid, jobname, schedule, command, active
from cron.job
where jobname = 'reap-stale-runs';
```

Expect exactly one row, `schedule = '* * * * *'`, `active = t`.

- [x] Verified.

### 1.5 Verify the job is firing (AC1b)

Wait 1–2 minutes after scheduling, then:

```sql
select status, return_message, start_time, end_time
from cron.job_run_details
where jobid = (select jobid from cron.job where jobname = 'reap-stale-runs')
order by start_time desc
limit 5;
```

Expect recent rows with `status = 'succeeded'`.

> **Why this query matters beyond AC1:** a reaper that raises inside its tick shows up here as
> `status='failed'` with a `return_message`. Without checking `job_run_details`, a silently failing
> reaper is indistinguishable from a healthy one — the exact class of defect issue #94 exists to
> close.

- [x] Verified.

**Results — AC1** _(executed 2026-08-31)_

| Check | Expected | Observed | Verdict |
|---|---|---|---|
| 1.4 job registered | one row, `* * * * *`, `active=t` | `reap-stale-runs` present and active | ✅ PASS |
| 1.5 job firing | recent `status='succeeded'` rows | recent successful executions confirmed | ✅ PASS |

> Verbatim query output was not retained for these two checks; the operator confirmed both
> assertions held. AC1 is satisfied. Re-run the §1.4/§1.5 queries any time to re-confirm.

---

## 2 — Verify `failed_to_start` (AC2)

Uses a **backdated** `queued_at` so the row is already past its threshold — you wait one cron
tick, not the full 60s + tick.

### 2.2 Insert the synthetic queued run

```sql
insert into runs (
  id, agent_id, agent_version, repository_id, installation_id,
  status, queued_at, max_runtime_seconds, grace_seconds, start_timeout_seconds
)
select
  gen_random_uuid(), a.id, a.version, r.id, r.installation_id,
  'queued', now() - interval '90 seconds', 3600, 120, 60
from agents a
join repositories r on r.full_name = 'llipe/memo-cli'
where a.slug = 'dependency-update'
returning id;   -- capture this
```

### 2.3 Wait one cron tick (≤60s)

> **Not-yet-executed check (AC4, `queued` half) — carried by
> [#101](https://github.com/llipe/dev-tasks-agent-fleet/issues/101).** Before waiting for the tick,
> query the view on the row from 2.2:
> ```sql
> select status, effective_status from v_runs where id = ':id';
> -- expect: queued | failed_to_start
> ```
> `v_runs` has two independent read-time branches (`running`→`timed_out` and
> `queued`→`failed_to_start`); only the `running` one was observed under #94 (§3.3). The `queued`
> branch was verified by inspection of the same `case` expression, not by observation.

### 2.4 Assert the status flipped (AC2)

```sql
select status, error_code, error_message, finished_at
from runs where id = ':id';
```

Expect `status='failed_to_start'`, `error_code='START_TIMEOUT'`, non-null `error_message` and
`finished_at`.

### 2.5 Assert the explanatory event exists (AC2)

```sql
select seq, level, message,
       data->>'reaped_by' as reaped_by,
       data->>'reason'    as reason
from run_events
where run_id = ':id'
order by seq;
```

Expect `level='error'`, `reaped_by='reap_stale_runs'`, `reason='START_TIMEOUT'`.

**Results — AC2** _(executed 2026-08-31, synthetic row)_

| Check | Expected | Observed | Verdict |
|---|---|---|---|
| 2.4 status | `failed_to_start` / `START_TIMEOUT` | flipped to `failed_to_start` within one tick | ✅ PASS |
| 2.5 event | `reason=START_TIMEOUT` row present | explanatory event present | ✅ PASS |

> A second, unplanned confirmation of AC2 was observed on run
> `cba355cb-199e-4444-8818-d0d4cb9c4335`: an orphan `queued` row (agent never reported start
> because the invoke payload was rejected — see §4.1) was reaped at
> `queued_to_reap = 324s` against `start_timeout_seconds = 300`, with `started_at = null` and the
> `START_TIMEOUT` event written. Correct behaviour on a genuine orphan.

---

## 3 — Verify `timed_out` + the two-layer contract (AC3, AC4)

### 3.2 Insert the synthetic running run

Threshold is `max_runtime + grace` = 60 + 10 = 70s; `started_at` backdated 75s makes it eligible
immediately.

```sql
insert into runs (
  id, agent_id, agent_version, repository_id, installation_id,
  status, queued_at, started_at, max_runtime_seconds, grace_seconds, start_timeout_seconds
)
select
  gen_random_uuid(), a.id, a.version, r.id, r.installation_id,
  'running', now() - interval '3 min', now() - interval '75 seconds', 60, 10, 300
from agents a
join repositories r on r.full_name = 'llipe/memo-cli'
where a.slug = 'dependency-update'
returning id;   -- capture this
```

### 3.3 Two-layer check — run IMMEDIATELY, before the next tick (AC4)

```sql
select status, effective_status
from v_runs where id = ':id';
```

Expect `status='running'` **and** `effective_status='timed_out'` at the same time. This is the
behaviour PRD FR11a depends on.

> **If you miss the window** (the tick already fired, both columns read `timed_out`), unschedule,
> insert, observe, then re-schedule:
> ```sql
> select cron.unschedule('reap-stale-runs');
> -- re-run the 3.2 insert, then the 3.3 query — the split is now stable
> select cron.schedule('reap-stale-runs', '* * * * *', $$select reap_stale_runs()$$);
> ```
> Remember to re-schedule, or every later verification will appear to fail.

### 3.4–3.6 Wait one tick, then assert materialization (AC3)

```sql
select status, error_code, error_message, finished_at
from runs where id = ':id';
-- expect: timed_out / RUNTIME_TIMEOUT

select seq, level, message, data->>'reason' as reason
from run_events
where run_id = ':id' and data->>'reaped_by' = 'reap_stale_runs';
-- expect: reason = RUNTIME_TIMEOUT
```

**Results — AC3 / AC4** _(executed 2026-08-31)_

| Check | Expected | Observed | Verdict |
|---|---|---|---|
| 3.3 two-layer (synthetic) | `running` + `effective_status=timed_out` | split observed before the tick | ✅ PASS |
| 3.5 status (synthetic) | `timed_out` / `RUNTIME_TIMEOUT` | materialized after one tick | ✅ PASS |
| 3.6 event (synthetic) | `reason=RUNTIME_TIMEOUT` row present | explanatory event present | ✅ PASS |

### Real-run confirmation of AC3 — run `f63ac9f3-14b0-4157-9484-f2f6b062f846`

A genuine hung `llm_fix` run provided stronger evidence than the synthetic row. The agent died
during the `validate` step (steps 1–6 succeeded; `validate` opened 19:36:07.964 and never closed)
and never reported a terminal status — exactly the failure class the reaper exists to cover.

| Field | Value |
|---|---|
| `started_at` | `2026-08-31 19:34:47.710204+00` |
| threshold | `max_runtime 3600 + grace 120` = **3720 s** → due `20:36:47` |
| `finished_at` (reaped) | `2026-08-31 20:37:00.013991+00` |
| `elapsed_seconds` | **3732.30** |
| `status` | `timed_out` |
| `error_code` | `RUNTIME_TIMEOUT` |
| `error_message` | `Sin reporte de término tras 3720 s (max_runtime 3600 + grace 120).` |
| event | `seq=10`, `level=error`, `reason=RUNTIME_TIMEOUT`, `reaped_by=reap_stale_runs` |

Three properties confirmed by this single run:

1. **No early reap.** Fired 12.3 s after the 3720 s boundary — inside one cron tick, never before
   the threshold.
2. **`seq` monotonicity.** The agent had written events `seq` 1–9; the reaper's event took
   `seq=10` (`max(seq)+1`), so it does not collide with `uq_run_events_seq`.
3. **Two-layer convergence.** Checked at `20:09` (34 min in, pre-threshold), `v_runs` reported
   `running | running` — correctly *not* yet terminal. After the reap, both `status` and
   `effective_status` read `timed_out`. The view leads and the reaper follows, then they agree.

> ⚠️ **Gap observed — the reaper does not close open steps.** `run_steps.seq=7` (`validate`) remains
> `status='running'` with `finished_at=null` inside a now-terminal `timed_out` run.
> `reap_stale_runs()` updates `runs` and writes the `run_events` row but never touches `run_steps`,
> unlike the agent's own failure path which closes open steps as `failed`
> (technical-guidelines §8). Every reaped run therefore leaves an orphan step pinned in `running`.
> Tracked as a follow-up (does not affect any issue #94 acceptance criterion).

### Cleanup synthetic rows

```sql
delete from runs where id in (':id_task2', ':id_task3');  -- events cascade
```

---

## 4 — Reaper interlock: healthy runs must not be reaped (AC5, dep-update AC-36)

> ⏳ **Not closed under #94** — AC5 is carried by
> [#101](https://github.com/llipe/dev-tasks-agent-fleet/issues/101) (see the §4.3 results block for
> why, and §4.4 for the proof that does not depend on #98).

### 4.0 Prerequisite — the run row must exist before invoking (D1)

**A direct `agentcore invoke` does not create the `runs` row.** Per D1 and specification §14, the
**front-end** inserts the `queued` row before invoking; the agent SDK only *updates* it
(`agent_reporter.py::RunReporter.start()` issues a PATCH, never an INSERT). The Next.js panel is
Phase 2 and does not exist yet, so PostgREST's PATCH matches zero rows, returns HTTP 200, and
**nothing appears in `runs` or `v_runs`**.

Insert the row first, simulating what the panel will do:

```sql
insert into runs (
  id, agent_id, agent_version, repository_id, installation_id,
  status, queued_at, max_runtime_seconds, grace_seconds, start_timeout_seconds
)
select gen_random_uuid(), a.id, a.version, r.id, r.installation_id,
       'queued', now(), 3600, 120, 300
from agents a
join repositories r on r.full_name = 'llipe/tf-ecommerce-mgmt'
where a.slug = 'dependency-update'
returning id;
```

> **Symptom if you skip this:** the run stays invisible, then a pre-inserted orphan `queued` row is
> reaped to `failed_to_start` at its threshold with `started_at = null` and zero agent-written
> events. That is the reaper working correctly on an orphan — not an agent bug.

### 4.1 Invoke — payload shape (⚠️ CLI 0.28.0)

`agentcore invoke [prompt]` treats its argument **as** the prompt and wraps it itself as
`{"prompt": "<arg>"}`. At the time this exercise was run, the agent's `unwrap_payload()` stripped
exactly **one** level, so passing an already-wrapped `{"prompt": "{...}"}` arrived
**double-wrapped**; one unwrap left `{"prompt": "{...}"}`, whose only key is `prompt`, and validation
failed with a generic `INVALID_PARAMS` / `"Invalid payload — missing required fields"`.

> **Resolved in [#97](https://github.com/llipe/dev-tasks-agent-fleet/issues/97) (PR #102).**
> `unwrap_payload()` now strips nested lone-`prompt` wrappers in a loop, so the pre-wrapped form is
> accepted verbatim again on CLI ≥ 0.28.0, and a still-wrapper-only payload fails with a distinct
> "appears double-wrapped" message instead of the generic one. The bare-inner-JSON `--prompt-file`
> form below still works and remains the recommended hand-invocation path. This section is kept as
> the record of what was executed during the #94 verification.

**Pass the bare inner JSON.** Write `/tmp/invoke-94.json` with no `prompt` key:

```json
{"run_id": "<UUID-FROM-4.0>", "repository_org": "llipe", "repository_name": "tf-ecommerce-mgmt", "params": {"fix_mode": "llm_fix", "max_fix_attempts": 3}}
```

```bash
cd agents/dependency-update
date -u +"%Y-%m-%dT%H:%M:%S.%3NZ"   # record: needed for the cold-start measurement in 4.3
agentcore invoke --prompt-file /tmp/invoke-94.json
```

Notes:
- `repository_name` is the **repo name only** — not `org/repo`.
- The README §Invocation and #77 runbook §7.7–7.10 examples use the pre-wrapped form; they failed
  on CLI ≥ 0.28.0 when this exercise ran but now work verbatim again (both docs updated in PR #102,
  see [#97](https://github.com/llipe/dev-tasks-agent-fleet/issues/97)).

Confirm it started:

```sql
select status, started_at from runs where id = ':id';   -- expect running + non-null started_at
```

### 4.2 Assert the healthy run is not reaped (AC5)

```sql
select status, outcome, error_code,
       extract(epoch from (finished_at - started_at)) as run_duration_seconds
from runs where id = ':id';
-- expect terminal succeeded|failed, NEVER timed_out

select count(*) from run_events
where run_id = ':id' and data->>'reaped_by' = 'reap_stale_runs';
-- expect 0
```

### 4.3 Measure the cold-start gap (dep-update PRD open question 8)

```sql
select queued_at, started_at,
       extract(epoch from (started_at - queued_at)) as insert_to_start_seconds
from runs where id = ':id';
```

> **Do not read `insert_to_start_seconds` as the cold-start gap when you insert the row manually.**
> It includes the human delay between running the INSERT and running `agentcore invoke`. The
> meaningful figure is **`started_at` − (the `date -u` timestamp from 4.1)**, because in production
> the front-end inserts and invokes within milliseconds. Record both, and label them distinctly.

Compare the true gap against `grace_seconds = 120`. If it approaches 120s, the grace window is too
tight and healthy runs risk being reaped.

**Results — AC5 / AC-36** — ⏳ **PENDING**

| Check | Expected | Observed | Verdict |
|---|---|---|---|
| 4.2 terminal status | `succeeded`/`failed`, never `timed_out` | not executed | ⏳ PENDING |
| 4.2 no reaper event | count = 0 | not executed | ⏳ PENDING |
| 4.3 true cold-start gap | comfortably < `grace_seconds` (120) | not validly measured — see note | ⏳ PENDING |

> **Why pending.** The real 20+ minute `llm_fix` run this AC calls for is **blocked by
> [#98](https://github.com/llipe/dev-tasks-agent-fleet/issues/98)** — the agent dies during
> `validate` without reporting terminal status, so no long run can currently complete. The seeded
> repos also yield `0 in_range` advisories, so the LLM fix loop is never reached and runs finish
> in ~2 minutes regardless.
>
> _Update:_ #98 is **resolved in code** (PR #103 — heartbeat keep-alive + `idleRuntimeSessionTimeout`
> 300 → 900; see `technical-guidelines.md` §8 and [ADR-006](../adr/ADR-006-long-step-keepalive-and-clock-invariant.md)),
> but the fix needs an AgentCore redeploy to take effect, so live AC5 verification stays carried by
> [#101](https://github.com/llipe/dev-tasks-agent-fleet/issues/101).
>
> **On the cold-start measurement.** One attempt produced `insert_to_start = 185.7 s` on run
> `f63ac9f3-…`, but that figure is **invalid** — it includes the human delay between running the
> INSERT and running `agentcore invoke`. The agent's first log (`19:34:47.530`) and `started_at`
> (`19:34:47.710`) are 180 ms apart, so the app reported start essentially instantly. A valid
> measurement requires the `date -u` method in §4.1. Do not record 185.7 s as the cold-start gap
> or as input to a `grace_seconds` decision.
>
> **Partial evidence that does exist.** Run `f63ac9f3-…` was *not* reaped during its ~61 minutes in
> `running` (zero `reaped_by` events until the legitimate 3720 s boundary), which demonstrates the
> reaper does not touch an in-flight run before its threshold. That is a weaker form of the
> interlock claim than AC5 asks for, but it is not nothing.
>
> **To close this AC**, run the synthetic interlock proof in §4.4 — it proves the boundary
> deterministically in minutes and does not depend on the runtime path broken by #98. Execution is
> carried by [#101](https://github.com/llipe/dev-tasks-agent-fleet/issues/101).

### 4.4 Fallback — synthetic interlock proof

If no seeded repo yields a genuinely long `llm_fix` run (e.g. all advisories classify
`major_required`/`unknown`, so zero packages change and the LLM loop is never reached), prove the
interlock deterministically instead:

```sql
-- healthy long-running row with REAL thresholds, 30 min elapsed (well under 3600+120)
insert into runs (
  id, agent_id, agent_version, repository_id, installation_id,
  status, queued_at, started_at, max_runtime_seconds, grace_seconds, start_timeout_seconds
)
select gen_random_uuid(), a.id, a.version, r.id, r.installation_id,
       'running', now() - interval '31 min', now() - interval '30 min', 3600, 120, 300
from agents a join repositories r on r.full_name = 'llipe/memo-cli'
where a.slug = 'dependency-update'
returning id;
```

Across several cron ticks it must stay `running` with `effective_status='running'` and zero reaper
events — proving a legitimately long healthy run is not reaped. Then confirm the boundary does fire
by backdating past the threshold (`started_at = now() - interval '63 min'`, i.e. > 3720s).

---

## 5 — CloudWatch fallback when Supabase is unreachable (AC6)

> ⏳ **Not executed under #94** — this task is carried by
> [#101](https://github.com/llipe/dev-tasks-agent-fleet/issues/101). The procedure below is written
> and ready; run it there. Note the §4.0 pre-insert and §4.1 payload form both apply.

### 5.1 Break PostgREST reachability

Point `SUPABASE_URL` at an unreachable host on the runtime config. **Record the current correct
value first** — it is in `agents/dependency-update/agentcore/agentcore.json` under
`runtimes[].envVars`.

### 5.2–5.4 Invoke and verify

```bash
agentcore invoke --prompt-file /tmp/invoke-94.json
```

- The agent **completes** rather than crashing — reporting failure must never kill the agent.
- After the SDK's 3 retries (`HTTP_RETRIES = 3`), payloads are dumped to stderr → CloudWatch:

```bash
aws logs tail /aws/bedrock-agentcore/<runtime-log-group> \
  --since 15m --region us-east-1 --format short \
  | grep -iE "supabase|retry|payload|report"
```

> 4xx responses are **not** retried (contract error — retrying cannot help); only transient
> failures (5xx, network) use the 3-attempt backoff before the stderr dump.

### 5.5 ⚠️ Restore `SUPABASE_URL`

Restore the recorded value and confirm reporting resumes:

```sql
select status from runs where id = ':new_id';   -- row should be updated normally again
```

> **Leaving `SUPABASE_URL` broken silently breaks every later verification** — the agent runs but
> writes nothing, and pre-inserted rows get reaped as `failed_to_start` with `started_at = null`.
> If you see that signature, check this first.

**Results — AC6** — ⏳ **PENDING** (Task 5 not executed)

| Check | Expected | Observed | Verdict |
|---|---|---|---|
| 5.3 agent completes | normal exit, no crash | not executed | ⏳ PENDING |
| 5.4 CloudWatch payloads | dumped payloads present after 3 retries | not executed | ⏳ PENDING |
| 5.5 restored | reporting works again | not executed | ⏳ PENDING |

> When executing this task, use the **bare-payload `--prompt-file`** invocation form from §4.1 —
> the pre-wrapped form fails with `INVALID_PARAMS` on CLI ≥0.28.0
> ([#97](https://github.com/llipe/dev-tasks-agent-fleet/issues/97)). Remember to insert the
> `queued` row first (§4.0), or the run will be invisible regardless of reachability
> ([#100](https://github.com/llipe/dev-tasks-agent-fleet/issues/100)).

---

## Verification status summary

| AC | Description | Verdict | Evidence |
|----|-------------|---------|----------|
| AC1 | `reap-stale-runs` scheduled `* * * * *` and firing | ✅ **PASS** | §1 results |
| AC2 | `queued` past threshold → `failed_to_start` + event | ✅ **PASS** | §2 results (synthetic + orphan) |
| AC3 | `running` past threshold → `timed_out` + event | ✅ **PASS** | §3 real-run `f63ac9f3-…` |
| AC4 | `v_runs.effective_status` leads the reaper | ✅ **PASS** | §3 synthetic split + real-run convergence (`running` half; the `queued` → `failed_to_start` read-time half was verified by inspection of the same `case` expression, not observed — carried by [#101](https://github.com/llipe/dev-tasks-agent-fleet/issues/101)) |
| AC5 | Healthy long run not reaped; cold-start gap recorded | ⏳ **PENDING** | blocked by [#98](https://github.com/llipe/dev-tasks-agent-fleet/issues/98); use §4.4 synthetic proof — carried by [#101](https://github.com/llipe/dev-tasks-agent-fleet/issues/101) |
| AC6 | Supabase unreachable → agent completes, CloudWatch recoverable | ⏳ **PENDING** | Task 5 not executed — carried by [#101](https://github.com/llipe/dev-tasks-agent-fleet/issues/101) |
| AC7 | Scheduling + results documented | ✅ **PASS** | this runbook |

**Residual verification owner.** Everything left open above —
the AC4 `queued`-half observation, AC5 (interlock proof + a valid cold-start measurement), and AC6 —
is carried by [#101](https://github.com/llipe/dev-tasks-agent-fleet/issues/101)
(*test(infra): complete issue #94 AC5/AC6 reaper verification*). Issue #94 ships with 5 of 7 ACs
verified; #101 is the place those three checks get executed, using the procedures already written in
§2–§5 of this runbook.

---

## Follow-up issues raised by this verification

Four **defects** were discovered while verifying the reaper and are **out of scope for #94** — the
reaper itself behaved correctly in every observed case.

| Issue | Title | Severity | Discovered how |
|-------|-------|----------|----------------|
| [#97](https://github.com/llipe/dev-tasks-agent-fleet/issues/97) | `unwrap_payload` double-wrap breaks `agentcore` CLI ≥0.28.0 invocations | high | Two invocations died with `INVALID_PARAMS` before switching to the bare-payload `--prompt-file` form (§4.1) |
| [#98](https://github.com/llipe/dev-tasks-agent-fleet/issues/98) | Run dies during `validate` step without reporting terminal status | high | Real run `f63ac9f3-…` hung mid-`validate`; reaper had to clean it up 3732 s later (§3 real-run block). **Blocks AC5.** **Resolved (code) in PR #103** — root cause confirmed as AgentCore output-idle reclamation (clean CloudWatch silence on this run, no OOM signature); the entrypoint now live-yields heartbeat chunks during `validate`/`llm_fix`, `idleRuntimeSessionTimeout` raised 300 → 900, and the timeout clocks are enforced consistent by `config.assert_clock_invariant()`. Live AC2/AC3 verification pending a runtime redeploy. See `technical-guidelines.md` §8. |
| [#99](https://github.com/llipe/dev-tasks-agent-fleet/issues/99) | `reap_stale_runs()` leaves open `run_steps` in `running` | medium | Same run: `validate` step still `running` inside a terminal `timed_out` run (Known limitations §2) |
| [#100](https://github.com/llipe/dev-tasks-agent-fleet/issues/100) | Control plane must insert the `queued` runs row before invoking | medium | Direct `agentcore invoke` left runs invisible — agent only PATCHes, never INSERTs (§4.0) |

Dependency note: **#98 blocks AC5** of this issue. #97 and #100 are prerequisites for anyone
re-running §4 or §5 by hand, which is why both are cross-referenced from those sections and from the
troubleshooting index.

A fifth issue carries the **unfinished verification** rather than a defect:

| Issue | Title | Carries |
|-------|-------|---------|
| [#101](https://github.com/llipe/dev-tasks-agent-fleet/issues/101) | `test(infra): complete issue #94 AC5/AC6 reaper verification` | AC5 (§4.2–§4.4 interlock proof + a valid `date -u` cold-start measurement), AC6 (§5 CloudWatch fallback, including the §5.5 restore), and the AC4 `queued` → `failed_to_start` read-time observation (§2 + a pre-tick `v_runs` query) |

---

## Troubleshooting index

| Symptom | Cause | Fix |
|---|---|---|
| Run invisible in `runs`/`v_runs` after invoke | No row inserted; agent only PATCHes (D1) | Insert the `queued` row first (§4.0) — [#100](https://github.com/llipe/dev-tasks-agent-fleet/issues/100) |
| `INVALID_PARAMS` / "missing required fields" | Payload double-wrapped by CLI ≥0.28.0 | Resolved in [#97](https://github.com/llipe/dev-tasks-agent-fleet/issues/97) (PR #102): `unwrap_payload` now loops, so the pre-wrapped form works verbatim; bare inner JSON via `--prompt-file` (§4.1) also works. A still-wrapper-only payload now logs "appears double-wrapped" |
| Row reaped `failed_to_start`, `started_at=null`, no agent events | Agent never reported start — broken `SUPABASE_URL`, `run_id` mismatch, or invalid payload | Check §4.1 payload, §5.5 restore, and that the invoke `run_id` matches the inserted row exactly |
| Run stuck `running`, last step open, no terminal report | Agent died mid-step without reporting | The reaper covers it at `started_at + 3720s`. Investigate the container — [#98](https://github.com/llipe/dev-tasks-agent-fleet/issues/98) |
| Step stuck `running` inside a terminal run | Reaper does not close open steps | Known gap — [#99](https://github.com/llipe/dev-tasks-agent-fleet/issues/99) |
| `v_runs` and `runs` disagree | Expected between threshold and the next tick — that is the two-layer design | None; confirm they converge after the tick |
| Reaper appears to do nothing | Job unscheduled (e.g. left unscheduled after a §3.3 retry) | Re-run `cron.schedule` (§1.3) and check `cron.job` |

---

## Known limitations observed during verification

### 1 — Agent dies mid-`validate` without reporting terminal status → [#98](https://github.com/llipe/dev-tasks-agent-fleet/issues/98)

A real `llm_fix` invocation (`f63ac9f3-…`) died during the `validate` step
(`run_steps` showed `validate` open, `runs.status` stuck `running`) and was correctly reaped
3732 s later. Two config facts are relevant, tracked outside issue #94:

- The entrypoint is an async generator that yields **only** its final result, so a run produces no
  stream output for its whole duration, against `idleRuntimeSessionTimeout: 300`.
- `TEST_TIMEOUT` defaults to **600 s**, twice that idle timeout.

Consequence for verification: AC5's "real 20+ minute `llm_fix` run" may not be achievable until
that is resolved — use the synthetic interlock proof in §4.4 instead.

### 2 — Reaper leaves open `run_steps` dangling → [#99](https://github.com/llipe/dev-tasks-agent-fleet/issues/99)

`reap_stale_runs()` transitions `runs` and writes the explanatory `run_events` row, but does not
close open `run_steps`. A reaped run keeps its in-flight step at `status='running'`,
`finished_at=null` indefinitely — unlike the agent's own failure path, which closes open steps as
`failed`. Phase 2 impact: the Run Detail steps panel (DESIGN.md §5.3) would render a
perpetually-running step inside a terminal run. Tracked as a follow-up; no issue #94 acceptance
criterion asserts step closure.

### 3 — The ~60-minute stale window is by design, not a defect

Because `max_runtime_seconds` mirrors AgentCore's `maxLifetime` (3600) plus `grace_seconds` (120),
a container that dies early still shows `running` until the 3720 s boundary. Run `f63ac9f3-…` died
around 19:36 and was only marked `timed_out` at 20:37 — a ~61-minute window where the panel shows a
plausible-but-stale `running`. This is the accepted D8 tradeoff; operators should not read it as a
reaper failure.
