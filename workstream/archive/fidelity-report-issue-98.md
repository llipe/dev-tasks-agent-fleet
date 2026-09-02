# Fidelity Report — Issue #98: run dies during `validate` step without reporting terminal status

<!-- Verdict-first: do not move this block below the fold. -->

## 1. Header / Verdict

| Field | Value |
| --- | --- |
| **Overall fidelity** | **High** |
| **Highest drift impact present** | **Minor** |
| **Scope** | Issue [#98](https://github.com/llipe/dev-tasks-agent-fleet/issues/98) · branch `issue/98-validate-step-heartbeat-terminal-report` · PR **#103** (draft) |
| **Mode** | Audit (grey-box) |
| **Audited against** | refinement AC1–AC6, `test-plan-issue-98.md`, `traceability-matrix-issue-98.md`, `tasks-issue-98-…md`, delivered code under `agents/dependency-update/` |
| **AC result** | 6 / 6 **Pass** (AC2 & AC3 pass on pre-deploy proxies; their **live** verification is **Blocked** on an AgentCore redeploy — a known, documented constraint, not a defect) |
| **Quality gates** | `make validate` green; **416** pytest pass (34 net-new for #98); `pip-audit` clean; coverage 93% (`heartbeat` 94%, `config` 96%, `signal_backstop` 91%; `main.py` coverage-omitted by repo convention); `coverage_gate = PASS` |
| **Drift** | 1 item — Minor / Intended / non-blocking (see §4). No Critical or Major drift. |

> **This audit is additive and non-blocking.** It does not gate PR/issue completion and does not replace the existing quality gates. The single Minor drift item below does **not** block completion.

---

## 2. Human-readable summary — what changed and why

A dependency-update run used to be able to **die silently in the middle of its test step and never say what happened**. The program only "spoke" to its host at the very start and the very end of a job; while it ran the (potentially many-minute) test suite it went quiet. The hosting platform (AWS AgentCore) interprets a long silence as "this job is stuck" and shuts the container down — so the run vanished with no result, and only a background cleanup job later marked it as timed-out about an hour later.

The fix makes the program **send a small "still working" signal (a heartbeat) every couple of minutes** while it runs a long step, so the host never mistakes a busy job for a stuck one. Two steps that can run long — the test/validate step and the AI fix step — now run this way. The final result is always sent last and is unchanged in shape, so whatever reads the result is unaffected.

Alongside that, the team **lined up all the timers** that govern how long things may run (per-command, test suite, container idle, container lifetime, and the cleanup threshold) so that no inner timer can outlast an outer one — the exact mismatch that caused the original failure (the test timer was allowed to run twice as long as the container's idle limit). A start-up self-check now refuses to run at all if these timers are ever misconfigured again, instead of failing mysteriously mid-job. The container's idle limit was also raised (5 → 15 minutes) as a belt-and-suspenders measure.

Finally, if the container is asked to stop *gracefully*, the program now makes a **best-effort attempt to record a final status** before exiting (with any secrets scrubbed from the message). If it is force-killed outright, that can't be intercepted by anyone — and the docs now state plainly that the background reaper is the only safety net in that case.

**Two things are genuinely proven only after a redeploy.** Whether a real >5-minute test run and a real >20-minute AI-fix run survive on the live platform can only be confirmed once the updated container is deployed. Until then, they are proven by an automated test that drives the real entry point with a deliberately slow step and confirms heartbeats are emitted and a proper final status is written. This limitation was declared up front and is tracked in the task list — it is expected, not a gap the delivery tried to hide.

---

## 3. Per-AC result table

| AC | Description | Codebase evidence | Workstream evidence | Test evidence | Result |
| --- | --- | --- | --- | --- | --- |
| **AC1** | Root cause recorded with evidence (CloudWatch silence, `__exit__` contract, clock inconsistency), referenced from #94 runbook | Clarified `update`-step log in `main.py` characterizing the EC-9 anomaly ("see issue #98 EC-9") | `technical-guidelines.md` §8 (all three strands) + changelog 1.8; `issue-94-reaper-verification.md` Known-limitations §1 cross-reference | Doc review; EC-9 characterization | **Pass** |
| **AC2** | A `validate` step whose test run exceeds 5 min completes without container reclamation | `validate` wrapped in `run_with_heartbeat` (worker thread + live heartbeat yields), `main.py`; `agentcore.json` idle 300→900 | tasks 1.4/1.7/1.8/1.21; pending-manual-config redeploy note | `TestEntrypointHeartbeatWiring` (real `main.invoke`, ≥1 heartbeat + terminal-last + agent `succeed`); EC-6 bound; RT-1 (40 iters) | **Pass** (pre-deploy proxy) · live **Blocked** (redeploy, task 1.21) |
| **AC3** | An `llm_fix` run >20 min reaches an agent-written terminal status (not reaper `timed_out`) | `llm_fix` step also wrapped in `run_with_heartbeat`, `main.py` | tasks 1.4/1.22; ADR-004 / runbook note that #98 blocks #94 AC5 | Same component harness drives llm_fix path to agent-written terminal; EC-8 via clock invariant | **Pass** (pre-deploy proxy) · live **Blocked** (redeploy, task 1.22) |
| **AC4** | `TEST_TIMEOUT`, `TOOL_COMMAND_TIMEOUT`, `idleRuntimeSessionTimeout`, `maxLifetime`, `max_runtime`/`grace` mutually consistent + documented | `config.assert_clock_invariant()` (pure, ordered) + constants; called fail-fast at entrypoint start in `main.py`; `agentcore.json` idle=900/life=3600 match | `technical-guidelines.md` §8 single-source-of-truth block; pending-manual-config env-var table | `test_clock_invariant.py`: shipped-config consistency, per-relation rejection (SC-4), EC-2, RT-2 (300 iters) | **Pass** |
| **AC5** | Heartbeat chunks distinguishable from terminal payload; terminal stays last; consumer parsing unaffected | `heartbeat.py` chunk contract (`heartbeat_chunk`/`terminal_chunk`/`is_*`/`read_terminal_payload`); `run_with_heartbeat` yields `HeartbeatResult` last | tasks 1.5/1.18; §8 doc of chunk shapes | `test_heartbeat.py` CT-1/CT-2/CT-3 + RT-1 + RT-3 (500 iters); component consumer-parse assertion | **Pass** (see §4 Minor drift) |
| **AC6** | Best-effort terminal flush on interceptable signal; SIGKILL documented reaper-only | `signal_backstop.py` (SIGTERM handler, never-raises, scrubbed, terminal-guard); installed after `RunReporter` in `main.py` | task 1.11; `technical-guidelines.md` §8 "Abrupt-termination backstop" | `test_signal_backstop.py` (7 cases incl. EC-7 scrub, off-main-thread no-op); EC-5 via `test_heartbeat.py` | **Pass** |

---

## 4. Drift catalog

> All drift below is **non-blocking to completion** per the verifier operating rules and the `implement` closing checklist.

### D-1 — Top-level exception handlers emit the terminal chunk as a raw literal instead of calling `terminal_chunk()`

| Field | Value |
| --- | --- |
| **Description** | The delivery summary states "all terminal yields go through `terminal_chunk`". Five terminal yields — the top-level `except CredentialError / ToolchainError / UpdaterError / PullRequestError / Exception` handlers in `main.py` (lines ~889–915) — instead `yield {"event": {"contentBlockDelta": {"delta": {"text": json.dumps(result)}}}}` directly. The in-`with`-block terminal yields *do* use `terminal_chunk()`. |
| **Impact class** | **Minor** |
| **Intent class** | **Intended** (pre-existing error-path shape retained verbatim; not a regression introduced by this change) |
| **Why it does not affect any AC** | The literal is byte-identical to `terminal_chunk()`'s output, so `is_terminal_chunk()` and `read_terminal_payload()` still classify and read it correctly (AC5 contract holds). These handlers fire *outside* the `with RunReporter` / heartbeat scope, so no heartbeat is ever active when they run — the terminal chunk is trivially the last and only stream item. No behavioral divergence. |
| **Evidence source(s)** | `main.py` §exception handlers; `heartbeat.terminal_chunk` / `is_terminal_chunk`; `test_heartbeat.py::TestChunkContract` |
| **Non-blocking note** | Does not block PR/issue completion. |

No Critical or Major drift was found. No spec-level ambiguity requiring `product-engineer` escalation was found.

---

## 5. Edge-case and randomized test outcomes

| Test-plan item | Outcome | Evidence |
| --- | --- | --- |
| SC-3 (silent-death regression) | Pass | component `TestEntrypointHeartbeatWiring` — ≥1 interim heartbeat + terminal last (fails on pre-fix zero-chunk behavior) |
| SC-4 (clock inconsistency rejected) | Pass | `test_clock_invariant.py::TestInvariantRejectsInconsistency` |
| SC-5 (consumer parses terminal despite heartbeats) | Pass | `test_heartbeat.py::TestConsumerParser` + component |
| SC-7 (SIGTERM best-effort) | Pass | `test_signal_backstop.py` |
| CT-1 / CT-2 / CT-3 (chunk shape / schema / ordering) | Pass | `test_heartbeat.py::TestChunkContract` + `TestRunWithHeartbeat` |
| CT-4 (no DB migration / free-form `error_code`) | Pass | no schema change delivered; new `SIGNAL_TERMINATION` code is free-form text |
| EC-1 (duration at idle boundary) | Pass (proxied) | covered by clock invariant + heartbeat cadence; exact-boundary live check folded into AC2 live (Blocked) |
| EC-2 (interval ≥ idle rejected) | Pass | `test_clock_invariant.py::test_heartbeat_at_or_above_idle_bound_is_rejected` |
| EC-3 / EC-4 (audit_only + early-return branches, no orphan heartbeat) | Pass | `audit_only` returns before any `run_with_heartbeat`; no-changes/mandate/validation-failed branches yield single terminal chunk (`main.py`) |
| EC-5 (exception mid-heartbeated step) | Pass | `test_heartbeat.py::test_exception_is_captured_and_stops_heartbeats`; `main.py` re-raises `HeartbeatResult.error` so `__exit__` writes `failed` |
| EC-6 (no flood) | Pass | `test_heartbeat.py::test_heartbeat_count_is_bounded_by_duration_over_interval` |
| EC-7 (secret scrub on flush) | Pass | `test_signal_backstop.py::test_scrubs_secrets_from_message` |
| EC-8 (heartbeat vs reaper coherence) | Pass | clock invariant `MAX_LIFETIME(3600) ≤ REAPER_THRESHOLD(3720)` |
| EC-9 (`0 packages changed` yet proceeds to `validate`) | Pass (characterized) | `main.py` `update`-step log rewritten to explain working-tree-vs-lockfile mismatch, tagged "issue #98 EC-9" |
| RT-1 (terminal-last property) | Pass | `test_heartbeat.py::TestTerminalLastProperty` (seed `98_hb_0831`, 40 iters) |
| RT-2 (heartbeat < idle property) | Pass | `test_clock_invariant.py::TestClockInvariantProperty` (seed `98_0831`, 300 iters) |
| RT-3 (parser fuzz) | Pass | `test_heartbeat.py::test_fuzz_random_heartbeat_arrangements_never_mislead_parser` (seed `98_fuzz_0831`, 500 iters) |
| SC-1 (live >5 min validate) | **Blocked** | requires AgentCore redeploy (task 1.21/1.26) |
| SC-2 (live >20 min llm_fix) | **Blocked** | requires AgentCore redeploy (task 1.22/1.26) |

No randomized test failed; no failure triage / minimization was required.

---

## 6. Recommendations

| Item | Recommended next step | Owner |
| --- | --- | --- |
| **D-1** (exception handlers bypass `terminal_chunk()`) | Optional tidy-up — replace the 5 raw literals with `terminal_chunk(json.dumps(result))` for single-source consistency. Cosmetic; **no action required** for this issue. | `developer` (optional) |
| **AC2 / AC3 live verification** | Execute the AgentCore redeploy (pending-manual-config Step 7 / task 1.26) then run one >5 min `validate` and one >20 min `llm_fix`, capturing CloudWatch + Supabase `runs` evidence. This also unblocks #94 AC5 (#101). | operator / `developer` |
| **AC1 idle-semantics open question** | The refinement's open question (invocation-idle vs stream-output-idle for `idleRuntimeSessionTimeout`) is mitigated by the 300→900 raise but not yet empirically confirmed; confirm during the live run above. | operator |
| Everything else | **No action needed** — delivered behavior matches requested intent. | — |

---

## Output Contract

- **Mode / phase:** Audit Mode · Phase 4 (Reporting & Publication)
- **Source artifact:** `workstream/issue-98-validate-step-no-terminal-report-refinement.md` (AC1–AC6)
- **Output files:** `workstream/fidelity-report-issue-98.md` (this file); `workstream/traceability-matrix-issue-98.md` (Observed-Result + Pass/Fail/Drift populated)
- **GitHub publication:** header/verdict + per-AC table below is ready to post to PR #103 / issue #98 (caller to post; verifier does not push).
- **AC coverage status:** 6 / 6 covered; 6 / 6 Pass (AC2/AC3 live verification Blocked on redeploy — documented constraint)
- **Overall fidelity verdict:** High · **Highest drift impact:** Minor
- **Blocking gaps:** none (audit is non-blocking; live AC2/AC3 verification is a tracked post-deploy step, not an audit gap)
