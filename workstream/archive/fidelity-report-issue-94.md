# Fidelity Report — Issue #94

## Verdict

- **Fidelity: Medium**
- **Highest drift impact: Major**
- **Scope:** issue #94 (`fix(infra): schedule pg_cron reaper and verify stale-run detection (Phase 1 gap)`) · branch `issue/94-schedule-pg-cron-reaper` · draft PR #96 · commits `9036501`, `96ba230`, `14bf5a0`, `f2ba48f`
- **Mode:** Audit (grey-box) — non-blocking, additive gate
- **AC coverage:** 5 of 7 verified (AC1, AC2, AC3, AC7 fully; AC4 partially but recorded as PASS). AC5, AC6 recorded PENDING.

Drift does **not** block PR or issue completion. One item below is not drift but a
workflow-gate conflict, and it is the only thing I would change before merging.

## Human-Readable Summary

The reaper is now scheduled and it demonstrably works. Before this change, runs
whose agent died could sit in the database marked "running" or "queued" forever,
with no recorded reason — while the panel's read-time view would still display the
correct status, hiding the problem behind a correct-looking interface. That gap is
now closed: a scheduled job runs every minute, moves abandoned runs to a terminal
state, and writes the explanatory log row that is the only place the "why" is ever
recorded.

The strongest evidence is not the synthetic test the issue asked for — it is a real
run that genuinely hung. An `llm_fix` invocation died partway through its test step
and never reported back. The reaper caught it 12.3 seconds after its 62-minute
deadline, marked it timed out, wrote the reason, and did so without disturbing the
run's existing log sequence. It also left that run alone for the full 62 minutes
beforehand, which is exactly the behaviour you want from something that has the
power to declare work dead.

Two of the seven checks were not completed. One (a healthy long-running job proving
it is not killed early) is genuinely obstructed by a separate defect that stops long
runs from finishing at all, filed as #98. The other (confirming the agent survives
and its data is recoverable when the database is unreachable) was simply not run. Both
are labelled PENDING in the runbook rather than quietly dropped, which is the right
call — but the reasoning attached to the first one is broader than the facts support:
two of its three checks do not actually depend on #98 and could be completed today in
about fifteen minutes using procedures already written into the runbook.

The work also produced something the issue did not ask for and that is arguably worth
more than the verification itself: four real defects elsewhere in the system, found by
actually exercising the path (#97, #98, #99, #100). None of them are reaper bugs. Every
one is documented with a symptom, a cause, and a fix, and cross-linked from a
troubleshooting table an operator can use without reading the whole document.

The practical caution: the pull request says it closes issue #94. Merging it as written
will close the issue automatically with two of its seven acceptance criteria still
unverified. That is a bookkeeping problem, not a quality problem, and it is easy to fix
before merge.

## Per-AC Results

| AC | Description | Codebase evidence | Workstream evidence | Test/observed evidence | Result |
|----|-------------|-------------------|---------------------|------------------------|--------|
| AC1 | `cron.job` shows `reap-stale-runs` at `* * * * *`; `cron.job_run_details` shows recent successes | `001_schema.sql:323-325` — `create extension pg_cron` + `cron.schedule('reap-stale-runs','* * * * *', …)` uncommented (diff confirms exactly this, 7 lines) | Runbook §1.3-1.5 with ready-to-paste queries; task 1.1-1.6 `[x]` | Runbook §1 results table: job present and active; recent `succeeded` rows confirmed. **Verbatim output not retained** — operator attestation only | **Pass** (weak evidence — see Drift #2) |
| AC2 | Synthetic `queued` past `start_timeout_seconds` → `failed_to_start` + explanatory event within one tick | `reap_stale_runs()` loop 2 (`001_schema.sql:296-311`): sets `failed_to_start`/`START_TIMEOUT`, inserts event with `reaped_by`/`reason` at `max(seq)+1` | Runbook §2 with exact insert SQL; task 2.1-2.6 `[x]` | Synthetic row flipped within one tick with the event; **plus an unplanned genuine orphan** — run `cba355cb-…` reaped at 324s vs `start_timeout_seconds=300`, `started_at=null` | **Pass** |
| AC3 | Synthetic `running` past `max_runtime + grace` → `timed_out` + explanatory event within one tick | `reap_stale_runs()` loop 1 (`001_schema.sql:265-291`): `timed_out`/`RUNTIME_TIMEOUT`, `error_message` interpolates both thresholds, event at `max(seq)+1` | Runbook §3 + real-run block; task 3.1-3.7 `[x]` | Synthetic row PASS **and** real run `f63ac9f3-…`: `elapsed 3732.30s` vs 3720s threshold (12.3s late, inside one tick), `RUNTIME_TIMEOUT`, event at `seq=10` after agent's 1-9, no `uq_run_events_seq` collision | **Pass** (exceeds requested — real hung run, not only synthetic) |
| AC4 | `v_runs.effective_status` reports terminal status **for both cases** before the reaper materializes it | `v_runs` case expression (`001_schema.sql:240-247`) has two independent branches: `running`→`timed_out` (line 242) and `queued`→`failed_to_start` (line 245) | Runbook §3.3 covers the `running` branch only; **§2 contains no `v_runs` check at all**; task list maps AC4→3.3 only | `running` half: synthetic pre-tick split observed, plus real-run convergence (`running\|running` pre-threshold → both `timed_out` after). **`queued`→`failed_to_start` read-time half: no recorded observation** | **Drift** — recorded PASS; one of two required cases unevidenced (Drift #1) |
| AC5 | Real long-running `llm_fix` not reaped early; cold-start gap recorded against `grace_seconds=120` | N/A — live-infra behaviour | Runbook §4 results table marked PENDING with rationale; §4.4 synthetic fallback authored and ready; tasks 4.1-4.4 `[ ]` | Not executed. Partial: `f63ac9f3-…` sat `running` ~61 min with zero reaper events until its legitimate boundary. Cold-start figure of 185.7s explicitly invalidated (human delay; agent's first log and `started_at` 180ms apart) | **Pending** (blocker attribution over-broad — Drift #3) |
| AC6 | Supabase unreachable → agent completes, payloads recoverable from CloudWatch | N/A — live-infra behaviour | Runbook §5 fully authored (break/verify/restore, with the ⚠️ restore warning); tasks 5.1-5.6 `[ ]` | Not executed. No rationale recorded | **Pending** (Drift #4) |
| AC7 | Scheduling step and all results documented in the deployment runbook | `001_schema.sql` reflects deployed state rather than pending intention | `issue-94-reaper-verification.md` (566 lines: scheduling, AC1-AC6 procedures, results tables, troubleshooting index, known limitations, follow-ups); `issue-77-deployment-e2e.md` cross-link + 2 gotchas; `technical-guidelines.md` §18 + changelog 1.5; `ADR-004` | Doc review: all AC results recorded including the two PENDING ones; location decision (separate runbook vs. §-in-#77) explicitly justified in both runbook and ADR | **Pass** |

## Grey-Box Code Findings (independent of the operator's execution)

Read directly from `docs/reference/001_schema.sql`, not from the runbook's claims:

1. **The "must not reap" guards are present in the DDL and structurally sound.**
   The `running` loop filters `status = 'running' and started_at is not null and now() > started_at + make_interval(...)`;
   the `queued` loop filters `status = 'queued'` with `queued_at` declared `not null default now()` (line 124).
   So: already-terminal rows are excluded by the status predicate, `started_at IS NULL`
   is excluded explicitly, and a future-dated `started_at` makes the comparison false.
   `v_runs` degrades the same way — a NULL `started_at` makes the `case` comparison NULL
   and falls through to `else r.status`. This materially changes how the "reaper never
   verified to refrain" finding should be weighted (see the assessment section).
2. **`for update skip locked`** on both loops is the intended concurrency guard, but
   its behaviour under overlapping ticks is asserted nowhere — this is the one
   refrain-adjacent property that inspection cannot settle.
3. **`security definer` + `set search_path = public`** is correct for a function that
   must write under RLS deny-all.
4. **#99 confirmed by inspection:** neither loop touches `run_steps`. The claim that
   every reaped run leaves an orphan step pinned `running` is accurate, and it follows
   from the code, not just from one observation.
5. **No out-of-scope functional change.** The entire schema diff is 7 lines
   (comment removal + a clarifying comment). `heartbeat`, `cancel`, and `retention`
   appear 7 times across the diff, all in explanatory prose (e.g. `last_heartbeat_at`
   named as the future lever for tightening the stale window) — never as new behaviour.
   No panel/UI file was touched. **Out-of-scope boundary respected.**

## Drift Catalog

All drift below is **non-blocking** to PR/issue completion.

### Drift #1 — AC4 recorded PASS with only one of its two required cases evidenced
- **Impact: Major.** **Intent: Unintended.**
- AC4 as written requires `effective_status` to lead the reaper "for **both** cases".
  The `running`→`timed_out` half is well evidenced (synthetic split + real-run
  convergence). The `queued`→`failed_to_start` half has no recorded observation:
  runbook §2 checks `runs` and `run_events` only and never queries `v_runs`, and the
  task list maps AC4 solely to sub-task 3.3. The traceability matrix names
  "E2E-4 (both queued + running halves)" as the positive test but records only the
  running result.
- The underlying technical risk is **low** — line 245 is a readable, symmetric branch
  of the same `case` expression, and I verified it by inspection. The drift is in the
  **verdict**, not the code: an explicit AC clause is marked PASS on half its evidence.
  It matters because Phase 2 duplicates this `case` expression in TypeScript and will
  treat the runbook as the pinned reference behaviour.
- **Cost to close: ~2 minutes, no dependency on #98 or anything else.** Re-run the §2.2
  insert and query `select status, effective_status from v_runs where id = ':id';`
  before the next tick. Expect `queued | failed_to_start`.
- **Evidence:** `001_schema.sql:240-247`; runbook §2 (absence of any `v_runs` query);
  `tasks-issue-94-…md` sub-task 3.3; `traceability-matrix-issue-94.md` AC4 row.
- **Non-blocking.**

### Drift #2 — AC1 rests on operator attestation with no captured output
- **Impact: Minor.** **Intent: Unintended** (acknowledged in the artifact).
- The runbook states plainly: "Verbatim query output was not retained for these two
  checks." AC1 is the only AC whose entire evidence base is an unrecorded assertion.
  Every other passing AC carries a run ID, a timestamp, or a numeric measurement.
- Mitigating: AC2 and AC3 both materialized, which is only possible if the job was
  genuinely firing. AC1 is therefore corroborated indirectly and is very unlikely to
  be wrong — the gap is reproducibility, not correctness.
- **Evidence:** runbook §1 results table and the note beneath it.
- **Non-blocking.**

### Drift #3 — AC5's blocker attribution is broader than the facts support
- **Impact: Major.** **Intent: Undetermined.**
- The runbook and ADR-004 both attribute AC5's PENDING status to #98. That holds for
  the literal "real 20+ minute `llm_fix` run" framing. It does **not** hold for two of
  the three checks in the results table:
  - **4.2 (healthy run not reaped early)** — runbook §4.4 already contains a synthetic
    interlock proof using *real* thresholds (3600/120) with a 30-minute-old
    `started_at`, held across several ticks, then backdated past 3720s to confirm the
    boundary fires. It exercises the same code path and depends on nothing that #98
    breaks. The runbook itself says "To close this AC, run the synthetic interlock
    proof in §4.4" — and then leaves the AC PENDING anyway.
  - **4.3 (cold-start gap)** — measuring `started_at` minus the `date -u` timestamp
    needs *a* real invocation, not a *long* one. The runbook's own note says seeded
    repos yield `0 in_range` advisories so runs finish in ~2 minutes regardless. The
    invalid 185.7s figure was correctly rejected; the valid measurement procedure
    (§4.1) was not attempted. I could not confirm from the artifacts that any short
    run has completed cleanly post-#98, so this is "appears achievable", not
    "certainly achievable".
- Risk of leaving it as-is: AC5 is parked behind a defect that need not gate it, so it
  is likely to stay open until #98 is fixed — and #98's fix is unscoped. dependency-update
  PRD open question 8 (`grace_seconds` sizing) stays open with it.
- **Evidence:** runbook §4.2/§4.3/§4.4 and the "Why pending" note; ADR-004
  Consequences; `technical-guidelines.md` §18 (#98 row: "Blocks issue #94 AC5").
- **Non-blocking.**

### Drift #4 — AC6 not executed, with no recorded rationale
- **Impact: Major.** **Intent: Intended** (deliberate, honestly labelled).
- Runbook §5 is fully authored — break `SUPABASE_URL`, invoke, assert completion,
  grep CloudWatch, restore — including the warning that leaving it broken silently
  poisons later verification. The results table says only "Task 5 not executed."
  Unlike AC5, no blocker is claimed and none is apparent: the two known obstacles
  (#97 payload shape, #100 pre-insert) both have documented workarounds referenced
  from §5 itself.
- AC6 is the only check covering the agent-side reporting fallback, and
  `agent_reporter.py` has no committed automated tests either — so this path has
  neither manual nor automated coverage in either direction.
- **Evidence:** runbook §5 results table; `TESTING.md` ranked gap 6.
- **Non-blocking.**

### Drift #5 — GitHub issue checklist out of sync with the local task list
- **Impact: Minor.** **Intent: Unintended.**
- The issue's **Scope** section checkboxes (lines 24-27, 33-36, 42-46, 65-66 of the body)
  are all unchecked despite the corresponding work being done and recorded — including
  "Uncomment the scheduling block", which is the commit this PR is built on.
  Separately, Execution Task List sub-task **6.4 is `[x]` locally and `[ ]` on GitHub**.
  Task 7.1-7.3 (AC mapping, out-of-scope confirmation, checklist sync) are unchecked in
  both, which is consistent — that wrap-up genuinely has not run.
- The `implement` activity requires local and GitHub checklists to stay aligned at all
  times and drift to be reconciled immediately.
- **Evidence:** `gh issue view 94` body vs. `workstream/tasks-issue-94-schedule-pg-cron-reaper.md`.
- **Non-blocking.**

### Drift #6 — `traceability-matrix-dep-update-agent.md` still shows AC-36 dynamic half unexercised
- **Impact: Minor.** **Intent: Intended** (task 4.4 is openly pending).
- Consistent with AC5 being PENDING, so not a contradiction. Worth noting only because
  real partial evidence now exists and is recorded nowhere in that matrix: run
  `f63ac9f3-…` was not reaped across ~61 minutes in `running`.
- **Non-blocking.**

### Drift #7 — uncommitted and untracked files on the branch
- **Impact: Minor.** **Intent: Unintended.**
- `TESTING.md` is **modified but uncommitted** — it carries the qa-engineer's Layer 2.5
  gap analysis, the ranked database/reaper gap table, and the follow-up-issue testing
  consequences. If PR #96 merges as-is, that analysis is not in the merge.
- `agents/dependency-update/invoke-84.json` is **untracked** — an operator scratch file
  holding the payload for run `f63ac9f3-…`. It contains a run ID and repo name, no
  credentials. The filename references issue 84 while the content belongs to #94.
- **Evidence:** `git status --porcelain`.
- **Non-blocking**, but the first item needs an action before merge or work is lost.

## Workflow-Gate Conflict (not drift — flagged separately)

**`Closes #94` in the PR body will auto-close the issue with 2 of 7 ACs unverified.**

This is distinct from the drift above. PR #96's body contains `Closes #94`, so merging
to `main` closes the issue. The `implement` activity's completion gate states plainly
that **all** acceptance criteria must be verified before an issue is closed, and that
task lists must reach final state. At merge time, AC5 and AC6 are PENDING and parent
tasks 4.0, 5.0, and 7.0 are open. Auto-closing would record #94 as done while its own
runbook documents two unverified criteria.

To be explicit about what this is and is not: the drift findings above genuinely do not
block merge, and this audit does not gate PR completion. This item is a bookkeeping
conflict with the repo's own stated gate, and it is cheap to resolve.

**Recommended resolution — pick one, in order of preference:**

1. **Close the two cheap gaps first, then merge as written.** Drift #1 (~2 min) and
   AC5's §4.4 interlock proof (~10 min, no #98 dependency) are both executable now.
   That takes verified coverage from 5/7 to 6.5/7 and makes `Closes #94` nearly honest.
   AC6 (~15 min) would finish it.
2. **Change `Closes #94` to `Refs #94`** and file one follow-up issue —
   *"Complete issue #94 AC5/AC6 verification"* — scoped to: the §4.4 synthetic interlock
   proof, the §4.1 `date -u` cold-start measurement, the §5 CloudWatch fallback, and the
   AC4 `queued`-half read-time check. Leave #94 open until that lands, or close #94 and
   let the follow-up carry the remainder explicitly.
3. **Merge as written and immediately reopen #94** with a comment listing the residual
   ACs. Works, but leaves a closed-then-reopened issue and is the least legible option.

Either way: commit `TESTING.md` before merging (Drift #7).

## Assessment of the Specific Questions Raised

**Is shipping with AC5+AC6 PENDING legitimate partial delivery, or unacknowledged drift?**
It is **acknowledged** partial delivery, not hidden drift — and the acknowledgement is
unusually thorough: the runbook results tables, ADR-004's Consequences section, the
traceability matrix coverage roll-up, and `technical-guidelines.md` §18 all state it, and
the invalid 185.7s cold-start figure was actively invalidated rather than quietly booked
as a result. That is the opposite of drift concealment. What is *not* legitimate is the
combination of (a) PENDING status, (b) an over-broad blocker attribution, and (c) an
auto-closing `Closes #94`. Any one of those alone is fine. Together they close an issue
on a blocker that only covers part of what is deferred.

**Was AC5 correctly left PENDING rather than substituted with the §4.4 synthetic proof?**
**No — this is the gap I would close.** The judgment call would be defensible if §4.4 were
speculative, but it is fully authored, uses real thresholds, and is explicitly recommended
by the runbook's own "To close this AC" line. Two considerations, weighed:
- *For substituting:* it exercises the same predicate, costs ~10 minutes, and is not
  blocked. The precedent is already set within this very issue — AC2 and AC3 were verified
  with synthetic backdated rows and nobody considers that a weaker result, because
  thresholds are per-run snapshots (D8).
- *Against substituting:* AC5 has a second clause the synthetic proof cannot satisfy —
  the cold-start gap must come from a real invocation. So §4.4 closes AC5's *interlock*
  half only.
The right outcome is therefore not "substitute and mark PASS" but **split AC5**: run §4.4
and mark the interlock half verified, keep the cold-start measurement pending, and attribute
that remainder to whichever is actually true — #98, or simply "not yet measured". Marking the
whole AC PENDING under a single blocker attributes more to #98 than #98 causes, and the
practical consequence is that the reaper's most safety-critical property stays unproven
while a fix for an unrelated defect is scoped.

**How material is the "reaper never verified to refrain" finding?**
Material, but **overstated as written — I'd rank it MED, not HIGH.** Three corrections from
reading the DDL directly:
1. **The reaper has demonstrably refrained.** Real run `f63ac9f3-…` sat in `running` for
   ~61 minutes with real thresholds and zero reaper events until 12.3s past its 3720s
   boundary. That is not a within-grace synthetic — it is the strongest possible form of
   "did not fire early", on a real row, for 62 minutes. The claim that "nothing confirms
   it REFRAINS" does not survive that observation.
2. **Three of the catalogued refrain cases are settled by inspection.** `started_at IS NULL`
   is excluded by an explicit `started_at is not null` predicate (line 270); a future-dated
   `started_at` makes `now() > started_at + interval` false; already-terminal rows are
   excluded by the `status =` predicate. `v_runs` degrades identically — NULL comparison
   falls through to `else r.status`. These are EC-2/EC-3/EC-4. Grey-box inspection is
   legitimate evidence for guards this simple, and it is why my mode is grey-box.
3. **What genuinely remains unverified is narrower and different:** (a) that the
   **deployed** function matches this DDL — there is no migration runner, no checksum, no
   schema-diff step, so drift between file and database is undetectable, and issue #94 was
   itself an instance of exactly that class; and (b) **concurrency/idempotency** under
   overlapping ticks (`for update skip locked`, EC-5/EC-6), which inspection cannot settle
   and which has a nasty failure mode — a `seq` collision aborts the whole tick, so one bad
   row stalls reaping for every run.
So the finding should be re-pointed: the risk is not "we never checked that it refrains",
it is **"we have no regression detector, and the deployed artifact is unverifiable against
the source"**. That reframing raises the priority of the recommended Layer 2.5 harness
(which addresses both) and lowers the urgency of re-running EC-2/EC-3/EC-4 by hand.
`coverage_gate: PASS` is correctly scoped to the Python package and, as `TESTING.md` now
states explicitly, says nothing about this layer in either direction.

**Was the out-of-scope boundary respected?** **Yes, cleanly.** The full diff is 8 files:
one 7-line SQL change (comment removal), five documentation files, and three workstream
artifacts. No heartbeat detection, no cancellation mechanism, no `run_events` retention,
no panel or UI file. `heartbeat`/`cancel`/`retention` appear only in explanatory prose —
`last_heartbeat_at` is named as the future lever for tightening the stale window, which is
appropriate documentation of a deliberately-unused column, not scope creep. No application
code was modified, consistent with the PR body's claim.

## Quality Gates (independently re-run in this environment)

Re-run from `agents/dependency-update/app/dependencyUpdate/`, not taken on report:

- `make validate`: **all gates passed**
- Tests: **362 passed** (4 warnings, 1.42s)
- Coverage: **TOTAL 94%** (845 stmts / 48 miss / 234 branch / 19 brpart)
- `pip-audit . --strict`: **no known vulnerabilities**
- QA `coverage_gate`: **PASS** — correctly scoped to the 11 non-omitted Python modules of
  the `dependency-update` package. `main.py` and `agent_reporter.py` are coverage-omitted;
  the SQL layer, runbooks, and `workstream/` artifacts are outside the measured tree
  entirely. **This is valid evidence of no Python regression and is not evidence about
  anything issue #94 changed** — no application code was modified.

## Recommendations

Ordered by value per minute of effort.

| # | Action | Owner | Est. | Blocked by |
|---|--------|-------|------|------------|
| 1 | Commit `TESTING.md` (Drift #7) — otherwise the Layer 2.5 gap analysis is not in the merge | `developer` | 1 min | — |
| 2 | Close AC4's `queued`-half gap (Drift #1): re-run the §2.2 insert, query `v_runs` pre-tick, expect `queued \| failed_to_start` | operator | ~2 min | — |
| 3 | Run runbook §4.4 synthetic interlock proof; mark AC5's interlock half verified and keep only the cold-start measurement pending (Drift #3) | operator | ~10 min | — |
| 4 | Resolve the `Closes #94` conflict — preferably options 1 or 2 above | `developer` / user | 2 min | — |
| 5 | Run AC6 (runbook §5), using the §4.1 bare-payload form and the §4.0 pre-insert; **do not forget §5.5 restore** (Drift #4) | operator | ~15 min | — |
| 6 | Measure the cold-start gap via the §4.1 `date -u` method on any completing run; record against `grace_seconds=120`; close dep-update PRD open question 8 | operator | ~5 min | possibly #98 |
| 7 | Reconcile the GitHub issue checklist with the local task list; complete tasks 7.1-7.3 (Drift #5) | `github-ops` | 5 min | — |
| 8 | Remove or `.gitignore` `agents/dependency-update/invoke-84.json` (Drift #7) | `developer` | 1 min | — |
| 9 | File the Layer 2.5 harness issue (local Postgres + `pg_cron`, pgTAP or Python DB suite; port CT-1 including must-not-reap rows, CT-2, CT-3, EC-1..EC-6, EC-9; apply `001_schema.sql` clean so DDL drift fails CI) — addresses both the regression-detector and deployed-vs-source gaps | user / `product-engineer` | — | approval |
| 10 | Update `traceability-matrix-dep-update-agent.md` AC-36 with the partial `f63ac9f3-…` evidence (Drift #6) | `developer` | 3 min | — |

**No `product-engineer` spec escalation required.** The acceptance criteria were
unambiguous; the shortfall is in execution coverage and verdict precision, not in
requirement interpretation. Drift #1, #3, #4, and #5 route to
`activity-drift-reconciliation` for task-list and checklist write-back.

**On the reaper itself:** in every observed case — synthetic and real, firing and
refraining — it behaved exactly as specified. The four follow-up issues are all
defects elsewhere in the stack, correctly triaged out of #94's scope rather than
absorbed into it.
