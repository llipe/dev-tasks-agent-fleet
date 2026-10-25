# Fidelity Report — S-190 (#372): Orchestration, outcome mapping, and reporting through the claim

> **Fidelity: High** · **Highest drift impact: Major** (DF-190-01, latent: it can't happen in Wave A, and becomes reachable when S-194 opens PRs) · **AC coverage:** AC1–AC4 Pass; AC5 **Pending IC** (tasks 11.6/11.7, run by the planner)
>
> Scope: story S-190, issue [#372](https://github.com/llipe/dev-tasks-agent-fleet/issues/372), Draft PR [#460](https://github.com/llipe/dev-tasks-agent-fleet/pull/460), `story/S-190-orchestration` @ `9c57bf8` → `integration/bug-fix-agent-wave-a` @ `6c9cb75` (includes #462). Mode: Audit (grey-box). Date: 2026-10-24.
>
> Drift is **non-blocking** to PR readiness and issue completion. Findings go to `product-engineer`'s `activity-drift-reconciliation`. This audit adds to the quality gates and replaces none of them.

## Changelog

| Version | Date | Summary | Author |
| ------- | ---- | ------- | ------ |
| 1.0 | 2026-10-24 | First Audit Mode run for S-190 against spec v2.6, stories v2.5, test plan v2.4 and PRD v2.1. | verifier |

## 1. Human-readable summary

**What changed.** The bug-fix agent no longer just answers "not yet implemented". A run now goes through four steps in order:

1. It checks its own credentials and the request.
2. It checks whether the issue can be worked on.
3. It copies the repository and checks that it meets the agent's requirements.
4. It claims the issue.

The fourth step, where the agent would try a fix, is turned off on purpose for now. So a run that gets the claim posts a short "stopped" note explaining that fixing isn't enabled yet, and ends as "needs review". Every way a run can end is now one of a small fixed set. Each comes with a plain-language reason, and only real faults count as failures. The panel link at the end of every comment now goes through one strict check.

**Why.** This finishes the first wave: an operator can start the agent and watch each decision in the panel before the fix loop is built.

**What still needs attention.**
- **Two Draft PRs for one issue (DF-190-01).** In the next wave, a slow second run could claim an issue after the first run has already opened its Draft PR, and open a second Draft PR. The product requirements forbid that. It can't happen today because no PR is opened yet. It needs a small spec change before the fix loop is turned on.
- **An unanswered 👀 (DF-190-02).** A run that fails right after claiming can leave a 👀 reaction with no follow-up.
- **Stale documents.** Some documents still describe the old placeholder, and the roadmap row is out of date.
- **The live check.** The real check on the deployed agent (tasks 11.6/11.7) is still to come.

## 2. Per-AC result table

| AC-ID | Description | Codebase evidence | Workstream evidence | Test evidence | Result |
| ----- | ----------- | ----------------- | ------------------- | ------------- | ------ |
| AC1 | `preflight` → `refuse` → `checkout` → `claim`, then `fix` only with `FIX_LOOP_ENABLED=1`; each a `run_steps` row with `run_events` | `main.py` `_steps()` builds the plan, and appends `fix` only when `cfg.fix_loop_enabled`. `_run_step()` opens and closes each `run_steps` row. `config.py` accepts only `0`/`1`; absent means off. `refusal.run_preflight()`/`run_refusals()` split the old single step | Spec §4 run sequence; tasks 11.4; TC-190-01/-02/-13 | `test_main.py::TestWaveAHappyPath` (step order and an event per step), `TestFixStep`, `TestRefusals`, `test_every_github_call_is_scoped_to_the_one_issue`; image smoke asserts the step names | **Pass** |
| AC2 | Outcome mapping per §8.9 for every Wave A path; `result.summary` on every `needs_review`/`not_applicable` | `outcomes.py`: `RunResult` validated on construction (non-empty summary, a reason on `not_applicable`/`needs_review`, closed outcome/reason/code sets), `counts_toward_breaker = status == failed`, `WAVE_A_ROWS` | Spec §8.9 v2.6; TC-190-03/-04/-05/-11/-12 | `test_outcomes.py` (one row per Wave A path, `TestSummary`, `TestBreaker`, `TestProducibleOutcomes`, static no-label/no-search scan); `test_main.py::TestFaults` | **Pass** (spec gaps DF-190-04, -05, -06) |
| AC3 | Heartbeat and signal backstop as in the siblings; `finally` path and backstop dispose only after confirmed ownership (D-81) | `run_with_heartbeat` around `execute()`. `install_termination_backstop(..., ctx.backstop_disposition)` gets `Disposer.backstop_action()`, which is `None` until `confirm_ownership()`. `_finally_dispose()` requires `ownership_confirmed` and no earlier attempt | Spec §8.6 step 3, §8.8; D-81, D-94; TC-190-06/-07/-08; RT-07 | `TestOwnershipGate` (SIGTERM in `checkout` → no write, `SIGNAL_TERMINATION` "ownership was not confirmed"; SIGTERM after confirm → exactly one disposition, then `fail()`; exception before or after ownership; never twice); `TestReporter` (flush failure, heartbeats); RT-07 200×30 | **Pass** (DF-190-07 on `capture_logging`) |
| AC4 | `runs.metrics.issue_number` and step timings | `RunContext.metrics()` → `issue_number`, `step_timings_ms` (non-negative int ms from a monotonic clock), and `gates_base` after checkout. Reported on every `RunResult.report()` path | Spec §13; FR-27; TC-190-09 | `TestMetrics` (happy path, refusal, fault, invalid issue → `None`) | **Pass** |
| AC5 | Deployed: a manual invoke on the fixture repo claims (marker, no reaction) and disposes "fix loop not yet enabled" | `agentcore.json` `FIX_LOOP_ENABLED=0`. The image smoke check imports `main` in the image (58/58, local arm64 build) | Tasks 11.6, 11.7 open by design; runbook "Wave A run" lists the expected result | `test_a_manual_invoke_makes_no_reaction` (L2 equivalent); no deployed evidence yet | **Pending IC** |

CI on head `9c57bf8`: every job green, including the bug-fix Python gate on 3.13 and 3.14. The developer's local run, recorded in task 11.9: 3020 passed, 5 xfailed, 97% coverage. `coverage_gate` is `SKIPPED(no-delegation)` in the developer's record, so the planner's `qa-engineer` still has to record it.

### Developer-flagged items, judged against the spec

| # | Item | Judgement |
| - | ---- | --------- |
| 1 | `capture_logging=False` | **Consistent with spec §12 item 6**, though not literally "as in the siblings" (they use the default `True`). The run_event warnings the spec asks for are emitted explicitly: no `v_runs` row and an unknown `effective_status` through `warn=` (`refusal.py:671`, `claim.py:260`), and the 404 "already gone" (`claim.py:285`). Nothing the spec requires as a run_event is lost. DF-190-07, Minor, Intended. |
| 2 | Missing repository fields → `failed`/`INVALID_PAYLOAD` at preflight, no GitHub call | **Acceptable, but the spec doesn't cover it.** These are payload fields (D-60), not params, so FR-26's "missing or invalid param → `not_applicable`" doesn't apply. `requires_repository=true` makes the path unreachable from the panel. §8.9 has no row for the entrypoint codes. DF-190-05. |
| 3 | `FIX_LOOP_ENABLED=1` with no fix runner → disposes "the fix step is not available in this build" | **Safe and non-breaker, but the spec doesn't cover it.** `default_runtime()` wires no runner, so if Wave B forgets to inject one, the S-194 flag flip produces exactly this disposition on every run. DF-190-04. |
| 4 | S-180 stub tests now cover only the entrypoint shell | **Intended.** S-190 supersedes TC-180-12's "not yet implemented", and `test_main.py` covers the real path. The test-plan row is stale. DF-190-10. |
| 5 | Some coverage tests written after the implementation | **Process-only, Minor.** The `[T]` commits (`d67d459` `test_outcomes.py`, `a2ce4e6` `test_main.py`) precede the `[I]` commits (`4c18a7f`, `daa192c`). `TestEdges`, `TestTokenSource` and the `test_credentials.py` additions landed with `daa192c`. No behavioral AC depends only on them. DF-190-11. |
| 6 | RT-07 finding: two Draft PRs possible in Wave B | **Confirmed by reading the code and the spec.** Major, Unintended spec gap. See DF-190-01 and §6. |
| 7 | DF-32 and DF-35 still open | **Correctly pinned, not resolved.** DF-32 is a strict xfail (`test_a_race_loser_with_its_own_trigger_gets_an_answer`). DF-35 is satisfied trivially in Wave A (there is no board client, so TC-189-21 sees zero calls), but it must be decided before S-199. Carried forward and not re-numbered. S-190 adds one related shape: DF-190-02. |

### Additional checks requested

| Check | Result |
| ----- | ------ |
| Step order; `fix` only with `FIX_LOOP_ENABLED=1` | Pass (AC1) |
| FR-5: no claim and no issue change before the refusal checks and repo gate | Pass. `test_no_issue_change_before_the_repo_gate` shows every call before the first write is a read. A refusal posts one marked reply only (TC-189-08 through `main`) |
| Only `failed` counts toward the breaker | Pass on the agent side (`counts_toward_breaker`, `TestBreaker`). DF-30 still holds: the webhook breaker never reads run outcomes, which is outside S-190 |
| `result.summary` on `needs_review` and `not_applicable` | Pass, enforced at construction; `result.reason` is also set (DF-190-06) |
| `runs.metrics.issue_number` and step timings | Pass (AC4) |
| SIGTERM: no disposition before a confirmed claim, a disposition after one | Pass at L2. The handler body is called directly, so installing the real signal handler on AgentCore (main thread) is not exercised, the same as in the siblings |
| One strict run-link validator | Pass. `run_link.py` is the only validator. The `_RUN_LINK` regexes in `claim.py`, `refusal.py`, `disposition.py` and `_PANEL_ORIGIN` in `config.py` are removed, and every builder calls `run_ref()`. One note: DF-190-12 |
| `agentcore.json` `FIX_LOOP_ENABLED=0` | Pass (`test_agentcore_config.py`) |
| Runbook "Wave A run": accurate and FR-49a-compliant | Accurate: the steps, both comment bodies, no reaction on a manual invoke, the `result` shape and the metrics all match the code. FR-49a is satisfied because the existing runbook is updated in the same PR. The runbook-coverage trigger is not met (two config/infra steps: 11.5 and 11.6). Small gaps: DF-190-09 |
| Docs drift (`technical-guidelines.md` §9, `product-context.md` §6) | Confirmed stale. DF-190-08 |
| `docs/roadmap.md` consistency | Mismatch. DF-190-03 |

## 3. Drift catalog

Every item is **non-blocking** to PR readiness and issue completion, and goes to `product-engineer` via `activity-drift-reconciliation` unless another route is named.

| ID | Description | Impact | Intent | Evidence | Route |
| -- | ----------- | ------ | ------ | -------- | ----- |
| DF-190-01 | **A late claim can win while another run's agent Draft PR is open, so two Draft PRs are possible.** Runs A and B both pass refusal (c) `linked_pr` and (d) `active_run` before either claims; B is still in `checkout`. A claims, wins and opens its Draft PR. Its trusted `pr` marker closes A's claim (DF-33), so when B claims, the §8.6 post-check (`refusal.active_claim_runs()` over `markers.open_claims()`) finds no open claim and B owns the issue. Nothing re-checks `linked_pr` after the claim, so B goes on to a second PR. This breaks PRD AC-20 ("never two Draft PRs") and RT-07 invariant (2). Not reachable in Wave A, which opens no PR. | Major | Unintended (spec gap) | `test_claim_state_machine.py::TestOwnedWhileAPrIsOpen` (strict xfail), `SHAPES["owned_while_pr_open"]`; spec §8.2 open-claim definition, §8.6 step 2; PRD AC-20; FR-35 makes the agent's own refusals the per-issue guard (G1/G5 lifted by D-107) | product-engineer (spec §8.6), then implemented in S-194 (#376). See §6 |
| DF-190-02 | **A post-check fault leaves an unanswered 👀.** Under D-81, a run whose post-check fails (`SUPABASE_UNAVAILABLE`, an unknown status, a non-404 `DELETE` fault) disposes nothing, so the 👀 on its trigger comment gets no 🚀 or 😕. RT-07 invariant (7) in the code adds this as a third exemption, which test plan §RT-07 doesn't list (it lists only "killed outright" and DF-32). This conflicts with PRD §14 "zero `/bug-fix` comments left without a visible answer, apart from runs killed outright". | Minor | Undetermined | `TestUnansweredEyes::test_a_post_check_fault_leaves_the_eyes_unanswered_by_design`; test plan RT-07 oracle (7); PRD §14 | product-engineer: reconcile together with DF-32. The options are the same: remove our own 👀, or add it only after the post-check |
| DF-190-03 | **Roadmap Wave A row is stale.** "What's missing" still lists S-186, S-185, S-188 and S-189, which are merged (PRs #451, #453, #454, #458), and "Issues/PRs" doesn't name those PRs. Status `In progress` is correct while 11.6/11.7 are open. | Minor | Unintended | `docs/roadmap.md` line 11; `gh pr list --base integration/bug-fix-agent-wave-a` | product-engineer / planner (roadmap-mismatch, advisory). Update in the consolidated PR |
| DF-190-04 | **`FIX_LOOP_ENABLED=1` with no runner is not specified, and no production runner is wired.** The behavior is safe (claim, a "not available in this build" disposition, `needs_review`, no breaker). But `main.default_runtime()` returns `Runtime()` with `fix_runner=None`, and nothing in Wave B's task list says to wire it. | Minor | Intended | `main.py` `_fix()`, `Runtime.fix_runner`, `default_runtime()`; story S-194 "`FIX_LOOP_ENABLED=1` … deployed" | product-engineer: add a S-191/S-194 task to wire `Runtime.fix_runner`, plus an image-smoke assertion that the deployed build has a runner when the flag is `1`. Optional: make `1` without a runner a `CONFIG_INVALID` instead |
| DF-190-05 | **Spec §8.9 doesn't list the entrypoint's own codes, and their shapes are inconsistent.** `CONFIG_INVALID`, `INVALID_PAYLOAD` (the pre-run chunk and the new preflight check), `PROBE_REFUSED` and `SIGNAL_TERMINATION` are in `outcomes.ERROR_CODES` but have no §8.9 row. The pre-run chunks, `PROBE_REFUSED` and the backstop's `fail(..., outcome="not_applicable")` carry `outcome: not_applicable` on a `failed` status, which `RunResult` itself forbids. Pre-run faults (config, payload without `run_id`, Supabase key) also never reach Supabase, so the reaper reports them as `timed_out`. | Minor | Undetermined | `outcomes.py` `ERROR_CODES`; `main.py` `_result()`, `_preflight()`; `signal_backstop.report_abrupt_termination`; spec §8.9 | product-engineer: add an "entrypoint" row group to §8.9 and decide the shape of a `failed` outcome |
| DF-190-06 | **`result.reason` on `needs_review` is new vocabulary.** The spec defines `result.reason = <code>` only for refusals (§8.2). The code also sets `fix_loop_disabled`, `fix_unavailable` and (Wave B) runner reasons on `needs_review`. Useful, and stated in the runbook, but not in the spec. | Minor | Intended | `outcomes.FIX_LOOP_DISABLED_REASON`; runbook "Wave A run" `result` | product-engineer: write back into §8.9 and §13 |
| DF-190-07 | **The reporter runs with `capture_logging=False`, which differs from the siblings.** FR-25 and S-190-AC3 say "as in the siblings". This is a deliberate hardening for scrubbing (spec §12 item 6), and every warning the spec requires as a `run_event` is emitted explicitly. | Minor | Intended | `main.py:652`; `agents/bug-fix/README.md:186`; the `warn=` call sites above | product-engineer: one line in spec §9 ("The reporter is unchanged") or §13. No code action |
| DF-190-08 | **Foundation docs still describe the stub.** `docs/technical-guidelines.md` §9 bug-fix row: "Wave A: S-180, S-181, S-182, S-184 done … the entrypoint still reports `started` and ends `succeeded`/`not_applicable` with 'not yet implemented'", plus changelog 1.57. `docs/product-context.md` §6: "The entrypoint is still a stub that ends `not_applicable`". Both were already stale for S-185 to S-189. The repo also still uses the pre-rename names (`docs/tech.md` and `docs/product.md` are absent). | Minor | Unintended | `docs/technical-guidelines.md:513`; `docs/product-context.md:55` | technical-writer, after 11.7 so the update can cite deployed evidence. Propose `dev-tasks migrate docs` |
| DF-190-09 | **Runbook "Wave A run" has small gaps.** It doesn't name the fixture repo (the smoke invoke uses `llipe/bug-fix-smoke`; 11.7 says "the fixture repo"). The front-matter `last_verified` (2026-10-24) and the `docs/runbooks/README.md` index row ("S-181 deploy, S-182 probe, S-184 seed row") weren't refreshed for S-190. The section hasn't been verified, because 11.7 hasn't run. The content otherwise matches the code. | Minor | Unintended | `docs/runbooks/bug-fix-agent.md` §Verification; `docs/runbooks/README.md:14` | technical-writer / planner at 11.7: name the repo, bump `last_verified` and the index row with the 11.7 evidence |
| DF-190-10 | **Test plan TC-180-12 still expects "not yet implemented".** `test_main_stub.py` now asserts the shell around a fake `execute()`. | Minor | Intended | test plan v2.4 TC-180-12; `tests/unit/test_main_stub.py` docstring | product-engineer: test-plan write-back (TC-180-12 superseded by TC-190-01/-02) |
| DF-190-11 | **Some tests came after the implementation.** `TestEdges` and `TestTokenSource` in `test_main.py`, plus the `test_credentials.py` additions, landed with the `[I]` commit `daa192c`. The `[T]` tasks 11.1 and 11.2 were committed first. | Minor | Intended | `git log` `d67d459`, `a2ce4e6` before `4c18a7f`, `daa192c` | No action. Noted for the planner's test-first check |
| DF-190-12 | **The run-link host check holds by convention.** No caller of `run_ref()` passes `origin`, so `is_valid_run_link` only compares a link with its own origin. A `RunLink("https://other.example", rid)` would pass. Safe today because only `Config.run_link()` builds one, but it's not enforced at the builders. | Minor | Intended | `run_link.py` `is_valid_run_link`, `run_ref`; `claim.py:76`, `refusal.py:264`, `disposition.py:139` | developer (optional hardening): pass the configured origin from the builders, or add a static test that `RunLink(` is constructed only in `run_link.py`/`config.py` |

**Carried forward and not re-numbered:**
- **DF-32** (a race loser's own 👀 is unanswered): open, pinned as a strict xfail.
- **DF-35** (where the board look-up sits): open. It is vacuous in Wave A and must be decided before S-199.
- **DF-30** (the webhook breaker never reads outcomes): open, outside this story.

## 4. Edge-case and randomized test outcomes

- **RT-07** (`test_claim_state_machine.py`): 200 walks × 30 steps through `main.wire_claim()`, the production wiring. Replay: `make test PYTEST_ADDOPTS="--hypothesis-seed=<seed> -k test_claim_state_machine"`. Invariants (1) and (3)–(6) hold. (8) is narrowed to "no board call" because Wave A has no board client. Three shapes are pinned as reproducible: DF-32 (strict xfail), DF-190-01 (strict xfail, a deterministic minimized sequence of five steps: two triggers, A claims and wins, A opens a PR, B claims and wins), and DF-190-02 (by design). There are no non-reproducing failures, so no retry budget was used.
- **TC-189-08 / TC-189-21** through `main`: one marked `repo_gate` reply per missing item, and zero board calls.
- **TC-190-13**: every GitHub URL is scoped to issue N on every terminal path.
- **Documentation structure**: not run. This repository has no `core/checks` (`checkDocsStructure`). The manual observations are in DF-190-09.
- **Vocabulary conformance**: not run, for the same reason. The diff is Python only and has no TypeScript `export` declarations, so `checkExportedIdentifiers` would report nothing.

## 5. Recommendations

| Item | Next step |
| ---- | --------- |
| DF-190-01 | Spec §8.6 amendment by product-engineer, implemented in S-194 (#376) before `FIX_LOOP_ENABLED=1` (§6) |
| DF-190-02 | Decide with DF-32 in the same reconciliation |
| DF-190-03 | The planner updates the Wave A row in the consolidated PR |
| DF-190-04 | Add a "wire `Runtime.fix_runner`" task to S-191/S-194, plus an image-smoke check |
| DF-190-05, -06, -07 | Spec write-back: §8.9 entrypoint rows, the `needs_review` reason, the reporter note |
| DF-190-08, -09 | technical-writer, after 11.7 |
| DF-190-10 | Test-plan write-back |
| DF-190-11 | No action needed |
| DF-190-12 | Optional developer hardening |
| AC5 | Planner runs 11.6 (`/infra-engineer` redeploy) and 11.7, then re-runs this audit or appends the IC evidence |

## 6. RT-07 finding: impact, owner and spec fix

**Impact.** It is Major because, once reachable, it breaks a PRD acceptance criterion (AC-20) and the "one bug-fix run per issue" business rule. With the trigger's G1/G5 lifted for `issue` scope (D-107, FR-35), nothing upstream stops it. The window opens when one run's whole path from claim to Draft PR (fix, validate, red-to-green) finishes while another run is still between its refusal check and its claim, which means it is still in `checkout` (clone, install, base gates). Two quick `/bug-fix` comments on a repo with a slow install, or a re-trigger by someone impatient, can produce it. The cost is a second Draft PR on another `issue/<N>-…` branch, about double the model spend, and a reviewer having to pick one. It isn't a security issue, since both PRs stay Draft and a human merges. It is latent today: Wave A opens no PR.

**Owner.** S-194 (#376), "Draft PR, artifact, and fix-loop enablement". It is the story that makes the shape reachable and flips `FIX_LOOP_ENABLED=1`, so the fix gates the flip. The spec decision belongs to `product-engineer` (drift reconciliation, confirmed by @llipe). The code change sits in `claim.py` (S-188's module), but it is S-194's work, and S-194's AC list should take it on together with removing the strict xfail. S-198 (live AC-20) is the end-to-end check.

**Recommended spec fix (§8.6 step 2, with §8.2 and §8.9 to match).**
1. **Post-check.** After the open-claim read, the post-check re-runs refusal (c) `linked_pr` through the same detection as §8.2: an open closing-reference PR, or an open PR whose head starts with `issue/<N>-`. If one exists, the run withdraws its own claim comment under the existing withdrawal-fault rules (a 404 is "already gone"; any other fault is `failed` with its D-67 code) and ends `succeeded`/`not_applicable` with reason `linked_pr`. A fault on the re-check fails closed with its D-67 code and never counts as "no linked PR". Ownership is confirmed only when both reads pass. This costs one GraphQL query and one paged `pulls` read, and closes the window at its source, before any model spend.
2. **Defense in depth, in S-194.** Repeat the same `linked_pr` check immediately before `git push`/`gh pr create`. If it finds a PR, the run takes the disposition path (`needs_review`, "another bug-fix PR was opened for this issue while this run worked"), because ownership is already confirmed at that point.
3. **Do not change the DF-33 rule that a `pr` marker closes a claim.** Keeping a successful run's claim "open" until its PR closes would cause problems of its own: a stranded block, and a dependence on the PR's state. Checking for the linked PR is the right signal.

`TestOwnedWhileAPrIsOpen` then turns from a strict xfail into a passing test, and RT-07 invariant (2) can drop the "record the shape" workaround.

## 7. Output contract

- **Mode / phase:** Audit, Phase 4 complete (report written).
- **Sources:** issue #372, the task list §11.0 (story branch), spec v2.6, stories v2.5, test plan v2.4, decisions D-20/D-61/D-67/D-81/D-94/D-112, PRD v2.1 (integration branch @ `6c9cb75`), and the PR #460 diff.
- **Artifact:** `/Users/felipemallea/Repos/dev-tasks-agent-fleet/workstream/fidelity-report-S-190.md` (not committed, as instructed).
- **GitHub publication:** not done. The caller asked for read-only, so the planner should post this header and verdict on #372/#460 and link the file once committed.
- **AC coverage:** AC1–AC4 covered and Pass; AC5 Pending IC.
- **Verdict:** Fidelity High. Highest drift: Major (DF-190-01, latent).
- **Blocking gaps:** none. AC5's deployed evidence (11.6/11.7) and `coverage_gate` from `qa-engineer` are still outstanding.
