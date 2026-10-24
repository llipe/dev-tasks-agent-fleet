# Fidelity Report — S-188 (#370): Claim with the post-claim race check

**Fidelity: High** · **Highest drift impact: Minor** · Scope: S-188 / #370, Draft PR #454, `story/S-188-claim-race` (head `46b61ff`) → `integration/bug-fix-agent-wave-a` (head `6e0fa0a`, which includes the DF-33 write-back in #455)

- All 5 story ACs pass. 7 drift items were found, all Minor and all advisory. None blocks PR readiness or issue completion.
- **DF-38 recommendation:** decide the race-loss `DELETE` piece now and ratify the current behaviour (a non-404 fault ends `failed` with its D-67 code, and nothing is disposed). Leave the rest of DF-38 open for S-186 and S-194. See DF-188-03.
- Audit mode, verifier, 2026-10-24. Drift findings route to `product-engineer` (`activity-drift-reconciliation`).

---

## 1. Human-readable summary

**What changed.** When someone writes `/bug-fix` on an issue, the agent now takes the issue in two visible steps:

1. It posts a short comment saying "Bug-fix run *link* is working on this issue".
2. It adds an 👀 reaction to the `/bug-fix` comment.

It changes no labels and assigns no one.

Two `/bug-fix` comments can arrive almost at once. To handle that, each run then re-reads the issue and checks whether another active run posted its comment first. Comment numbers decide the order, so two comments in the same second still have one winner.

- **The run that came second** removes its own comment and stops quietly. It is recorded as "not applicable: another run is active".
- **The run that came first** becomes the owner. Only the owner may later post a result or move the issue on the project board.
- **If the check itself fails** (the run-status database is unreachable), the run stops as failed. It leaves its comment in place and touches nothing else, so it can never clean up after a run that actually owns the issue.

The panel link in the comment comes from a new setting. It is configured but not deployed yet, and it is due with the S-190 redeploy. Without the setting, the comment shows the run's id instead of a link.

**Why.** One issue must never get two competing fixes (PRD AC-3, AC-20, AC-24). The work also tidies one rule: there is now a single definition of "an issue has an open claim", which the refusal check and the race check share (DF-33).

**What is open.** All seven open points are small:

- three places where the written spec words a rule differently from the code;
- one decision the user still has to make (DF-38: what a failed removal of the losing comment means);
- one randomized test that was planned for this story but belongs later;
- two places where the paperwork needs a refresh.

---

## 2. Per-AC results

Sources: **C** codebase (`claim.py`, `markers.py`, `refusal.py`, `issues.py`, `config.py`, `agentcore.json`); **W** `/workstream` (task list §9.0, spec v2.4, stories v2.3, test plan v2.2, matrix v2.1, decisions); **T** tests; **I** intent (PRD v2.1, the #370 body).

**Test run.** The audit exported the branch into a scratch directory and ran 12 relevant test files there: 987 passed and 2 failed. Both failures (`test_seed_max_runtime_seconds_equals_max_lifetime[migration|seed.sql]`) are artefacts of the export, which held only `agents/bug-fix` and not the repository's `supabase/` directory. They are not product defects. The developer reports the full agent gate green (2271 passed, coverage 98%, `claim.py` 100%).

| AC-ID | Description | Codebase evidence | Workstream evidence | Test evidence | Result |
| --- | --- | --- | --- | --- | --- |
| S-188-AC1 | Claim comment with the run link, then 👀 only when `trigger_comment_id` is present; no label or assignee change (FR-7, FR-8) | `Claimer.post()` POSTs `build_claim_body()` (line 1 is the `claim` marker, line 2 is `CLAIM_LINE`), then `_react()`. `IssuesClient.add_reaction(None, …)` makes no call. `claim.py` has no label or assignee call. | spec §8.6 step 1; task 9.2, 9.4 | `TestHappyClaim` (exact write order `POST comments` → `POST reactions` → `GET comments`); `TestManualInvoke`; TC-188-02, -03, -15 | **Pass** |
| S-188-AC2 | Post-check: a lower-id open claim (DF-33) of another non-terminal run → delete only this run's comment, `not_applicable`/`active_run`, no board call; a missing row counts as finished, an unknown status is a post-check failure | `race_winner()` → `refusal.active_claim_runs(before=own_cid)` → `markers.open_claims()`. `_withdraw()` DELETEs only `posted.comment_id`. `ClaimOutcome.result()` is `{reason: active_run, summary}`, with no board call. | spec §8.2, §8.6; D-54, D-104 amend.; tasks 9.1, 9.2 | `test_race.py` (TC-188-05, -06, -07, -16, CT-34); `TestLostRace`; RT-02 oracle (7) over 1000 examples | **Pass** (wording drift DF-188-01, DF-188-02, DF-188-03) |
| S-188-AC3 | Ownership gate: only a won race confirms ownership and runs the board hook; a post-check `SUPABASE_UNAVAILABLE` keeps the comment and ends `failed` with no disposition (D-81) | `post_check()` catches `SupabaseUnavailable` and `GitHubError` → `_failed(…)`, without reaching `_own()`. `_own()` calls `confirm_ownership()`, then `board_in_progress`. | spec §8.6 step 3; D-81 amend.; D-103 | `TestPostCheckFailure` (503, 401, connection error, timeout, unknown status, listing faults): `dispose()` → `not_owned`, `backstop_action()` → `None`, no 😕, no board; `TestBoardGate` (`v_runs` read before `board`, board after `ownership_confirmed`) | **Pass** |
| S-188-AC4 | PRD AC-3 end state | As AC1 | TC-188-08 | `test_the_end_state_matches_prd_ac_3` (issue facts byte-equal, no `/labels` or `/assignees` path); `test_no_label_or_assignee_request_on_any_path` (5 paths) | **Pass** (the live run, SC-LIVE-01, is for S-198) |
| S-188-AC5 | PRD AC-20: one owner, one withdrawal | `post()` and `post_check()` are separable for interleaving | TC-188-13; EC-09 | `TestTwoRuns` (both check orders, plus a shared trigger comment); `TestEdges` same-second reversed listing | **Pass** at L2 (live AC-20 is blocked by DF-29, outside this scope; RT-07 is not built, see DF-188-05) |
| Tech note (DF-33) | One open-claim definition in `markers.open_claims()`; `refusal.py` no longer duplicates it | `CLOSING_KINDS = {pr, disposition, refusal}`. The `refused` set in `open_claim_runs` is removed, and `refusal.py` no longer imports `trusted_markers`. Refusal (d) and the race check both go through `active_claim_runs()`. | spec v2.4 §8.2; story v2.3 tech note | `TestOpenClaims` (refusal closes its own run's claim, not another's, and an untrusted refusal does nothing); RT-02 oracles (3) and (6) updated; `test_refusal.py` green, unchanged | **Pass** (literal placement drift DF-188-01) |
| Tech note | `PANEL_BASE_URL` in `config.py` and `agentcore.json` builds the run link | `Config.panel_base_url`, `Config.run_link()`; env entry `https://dt-agent-fleet-panel.fly.dev` | task 9.3; the redeploy is task 11.6 via `/infra-engineer` (task-list note, line 47) | `test_config.py`, `test_agentcore_config.py` | **Pass**. Not deployed, which matches the task list: the redeploy belongs to 11.0. |

### Checks requested by the caller

| Check | Verdict | Evidence |
| --- | --- | --- |
| DF-33: single rule; `refusal.py` doesn't duplicate it | Holds. The marker half is only in `markers.open_claims()`. The status half is only in `refusal.active_claim_runs()`, and both callers share it. | DF-188-01 covers the wording mismatch |
| Claim order: comment, then 👀 only when the trigger is present | Holds | `TestHappyClaim`, `TestManualInvoke` |
| Race verdict by comment id; loser deletes only its own comment; `not_applicable`/`active_run`; no board call | Holds | `test_race.py::TestOrdering`, `TestLostRace`, `TestTwoRuns` |
| Post-check Supabase failure → `failed`, no disposition (D-81) | Holds | `TestPostCheckFailure` |
| Ownership confirmed only after a won race | Holds | `_own()` is the only caller of `confirm_ownership()`; `TestBoardGate` |
| D-93: no label or assignee writes | Holds | grep of `claim.py`; `test_no_label_or_assignee_request_on_any_path` |
| `PANEL_BASE_URL` in `config.py` and `agentcore.json`; not deployed | Holds; consistent with the task list | Task 11.6 "Redeploy through `/infra-engineer`" |
| (a) Non-404 `DELETE` fault on a lost race → `failed` | Matches D-67 as written; DF-38 undecided | DF-188-03 |
| (b) Claim POST with no comment id → `failed`/`GITHUB_REQUEST_REJECTED` | **No drift.** Spec §8.9 maps "a malformed response body" to `GITHUB_REQUEST_REJECTED`. No reaction is attempted, nothing is disposed, and the comment, which may have landed, stays as it would after a post-check failure. | `test_a_claim_answer_with_no_id_is_rejected_before_the_reaction` |
| (c) `PANEL_BASE_URL` optional; run id shown when missing | Minor drift against FR-7's wording | DF-188-04 |
| (d) RT-07 not built | Minor drift between the test plan and the task list | DF-188-05 |
| (e) Loser's 👀 stays (DF-32) | **No new drift.** It matches spec §8.6 as written and is pinned by `test_the_losers_eyes_stays_and_it_posts_no_reply` and `TestTwoRuns`. DF-32 itself is still open with `product-engineer`. | test plan §10.4 DF-32 |

---

## 3. Drift catalog

Every item below is **advisory and non-blocking** to PR #454 readiness and to the completion of #370.

| ID | Description | Impact | Intent | Evidence |
| --- | --- | --- | --- | --- |
| DF-188-01 | **The DF-33 rule is split across two functions.** Spec v2.4 §8.2 says "`markers.open_claims()` is the single implementation of this definition", where the definition includes the `v_runs` status. Story v2.3's tech note says S-188 moves "the `refusal` rule and the `v_runs` status resolution" into `markers.open_claims()`. The code puts the marker half in `markers.open_claims()` and the status half in `refusal.active_claim_runs()`. Both callers share both halves, so nothing is duplicated and the intent holds. Only the named location differs. The split keeps `markers.py` free of I/O, and the PR states it. TC-186-06 (`test_markers.py`) lists status cases that `open_claims()` can't take; those cases are covered in `test_race.py::TestStatusFaults` and `test_refusal.py` instead. | Minor | Intended | spec §8.2, §8.3; story S-188 tech note; D-81 and D-104 amendments; `refusal.py` `active_claim_runs`; PR #454 body "DF-33 decision" |
| DF-188-02 | **The race-loss `DELETE` is retried on a 5xx.** `IssuesClient.delete_comment()` passes `idempotent=True`, so a 5xx or a transport error gets 3 attempts. Four sources forbid that: spec §9, the D-67 amendment, TC-185-14 ("a 5xx or a transport error on a `POST`/`PATCH`/`PUT`/`DELETE` raises `GITHUB_UNAVAILABLE` after exactly one request") and `github_client.py`'s own module docstring all list `DELETE` as a write that is never retried on a 5xx. The behaviour is safe: a retry after a delete that already applied gets a 404, which reads as `already_gone`. The code documents the choice in its docstring, but the PR body doesn't flag it. | Minor | Intended | `issues.py` `delete_comment`; `test_claim.py` `[503, 503, 503] → GITHUB_UNAVAILABLE`; spec §9 "Writes"; `github_client.py` lines 12–15 |
| DF-188-03 | **DF-38, the race-loss `DELETE` piece.** A non-404 fault on the loser's `DELETE` ends `failed` with its D-67 code (`GITHUB_UNAVAILABLE` or `GITHUB_REQUEST_REJECTED`), with no disposition and no board call. A 404 counts as `already_gone`, and the run still ends `not_applicable`. This follows D-67 as written, but DF-38 explicitly leaves this case undecided, and spec §8.6 and §8.9 are silent on it. The PR body says the orphaned claim "blocks refusal (d) until the run is terminal". In practice the window closes as soon as the loser itself ends, because `failed` is terminal. From then on, refusal (d) ignores the orphan, and later claims have higher ids, so the winner's race check never sees it. | Minor | Undetermined | `claim.py` `_withdraw`; `test_another_delete_fault_ends_failed_with_no_disposition`; test plan DF-38; TC-185-14 best-effort list |
| DF-188-04 | **`PANEL_BASE_URL` is optional.** FR-7 and S-188-AC1 call for "a panel link" in the claim comment. With the variable unset, the comment names the run id in backticks instead, and an unusable link (not `https`, or containing whitespace) falls back the same way. Production config sets the variable, so the deployed agent meets FR-7. The fallback is a robustness choice that matches the refusal reply and the diagnosis. | Minor | Intended | `config.py` `run_link`; `claim.py` `build_claim_body`; `test_an_unusable_link_falls_back_to_the_run_id`; PRD FR-7 |
| DF-188-05 | **RT-07 is not built.** Test plan v2.2 §11 (execution order step 7: "S-188 (9.1, 9.2): TC-188-* and RT-07") and the matrix rows for S-188-AC2, S-188-AC5, PRD AC-3, AC-20 and AC-24 assign RT-07 (`test_claim_state_machine.py`) to S-188. Task list §9.0 has no RT-07 step, so the developer followed the task list. RT-07's invariants (2), (3) and (7) need the PR and disposition states, which S-190 and S-194 deliver. AC-20 is still covered by TC-188-13, TC-188-07 and RT-02 oracle (7). | Minor | Intended | test plan line "S-188 (9.1, 9.2): TC-188-* and RT-07"; matrix S-188-AC2/AC5; task list §9.0 |
| DF-188-06 | **The #370 issue body predates the DF-33 write-back.** Its Post-check AC still reads "no `pr` or `disposition` marker", without `refusal` and without the missing-row and unknown-status rules of stories v2.3. Its "Files to Create/Modify" list omits `markers.py`, `refusal.py` and `tests/unit/test_markers.py`. #455 updated the stories but posted nothing on #370. | Minor | Unintended | `gh issue view 370` body vs. stories v2.3 S-188 |
| DF-188-07 | **Bookkeeping.** (1) The task list's Relevant Files now lists `agents/bug-fix/app/bugFix/claim.py` twice: the new S-188 line, plus the pre-existing "Claim and race check" line. (2) The roadmap's bug-fix Wave A row (`docs/roadmap.md` line 11) lists S-185 and S-186 under "What's missing", and its Issues/PRs omits #451 and #453, although both stories are merged into `integration/bug-fix-agent-wave-a`. S-188 is correctly listed as missing. Under the roadmap rule, the planner refreshes the row. | Minor | Unintended | `workstream/tasks-prd-bug-fix-agent-plan.md` Relevant Files; `docs/roadmap.md` row 11; merges `af15c63` (#451), `3bcc61b` (#453) |

Not drift: flagged choice (b) and DF-32 (e); see §2.

---

## 4. Edge-case and randomized test outcomes

| Plan item | Outcome |
| --- | --- |
| EC-09 (same second; comment id decides) | Pass: `TestEdges::test_two_comments_in_the_same_second_are_ordered_by_id`; `test_race.py::TestOrdering` (ids above 2^31 compare numerically) |
| EC-06 / EC-51 (crash after the comment; AC-24) | Pass: `TestCrashAfterTheComment` (refused while `running`; proceeds after `timed_out`; orphan and 👀 kept; no deletion) |
| EC-20 (forged markers) | Pass: `TestForgedClaims` (human, another App, wrong user type; a forged closer doesn't close; a quoted marker below the block is ignored) |
| EC-37 (Supabase down in the post-check) | Pass: `TestPostCheckFailure` |
| EC-50 (reaction 4xx) | Pass: `TestEdges` 404, 422 and exhausted 5xx are logged; the claim stands |
| EC-54 (the loser's own 👀) | Pinned as expected (DF-32) |
| 9.5: the other run already terminal | Pass for `succeeded`, `failed`, `timed_out` and `canceled` |
| RT-02 (1000 examples) | Pass. Oracles (3) and (6) follow DF-33; the new oracle (7) checks the race verdict, including forged claims and closers. Seeds are under hypothesis' default derandomisation policy, so a replay uses the `@reproduce_failure` blob hypothesis prints. |
| RT-07 | Not built (DF-188-05) |

**Documentation structure.** `core/checks` doesn't exist in this repository, so the audit couldn't run `checkDocsStructure`. It reviewed the docs by hand:

- `agents/bug-fix/README.md` is accurate. Its capability table, layout, `PANEL_BASE_URL` row, markers section (DF-33 wording), `delete_comment()` note and new "Claim and race check" section all match the code, and the S-190 wiring note is correct.
- The `TESTING.md` bug-fix row is accurate: it adds `DELETE` to the double and states that `test_claim.py` reuses the PostgREST double.
- `docs/runbooks/` is not touched.

**Vocabulary conformance.** Nothing to report. The diff adds no TypeScript `export` declaration, and no Python public identifier uses the PRD glossary's forbidden synonyms for *claim* (`lock`, `take`, `checkout`). `docs/domain/ubiquitous-language.md` has no claim entry.

**Runbook coverage.** Not a finding. Task list §9.0 has one configuration step (9.3), which is below the threshold of three, and the PR changes no script or workflow.

**Roadmap mismatch.** See DF-188-07 (2). S-188 doesn't complete Wave A.

**Branch state.** `story/S-188-claim-race` forks from `adb4f85`, before #455. A trial merge into the current `integration/bug-fix-agent-wave-a` is clean.

---

## 5. Recommendations

| ID | Next step | Owner |
| --- | --- | --- |
| DF-188-01 | Accept the split. Amend spec §8.2 and §8.3, the S-188 tech note, and the D-81 and D-104 amendments to say: the marker half is `markers.open_claims()`, and the status half is `refusal.active_claim_runs()`, both shared by refusal (d) and the race check. Point TC-186-06's status cases at `test_race.py` and `test_refusal.py`. | `product-engineer` |
| DF-188-02 | Preferred: amend spec §9, the D-67 amendment and TC-185-14 to carve out the single-id `DELETE` as idempotent, where a retry is safe because a 404 means already gone. Then `developer` fixes the `github_client.py` module docstring to name the exception. The alternative is for `developer` to drop `idempotent=True`. | `product-engineer`, then `developer` (docstring) |
| DF-188-03 | **Decide the race-loss slice of DF-38 now, and ratify the current behaviour.** A non-404 `DELETE` fault ends `failed` with its D-67 code, nothing is disposed and the board is not touched. A 404 is `already_gone`, and the run ends `not_applicable`/`active_run`. Record it in spec §8.6 step 2 and §8.9, and in TC-185-14's best-effort list. The reasons are below the table. Leave DF-38's other parts open: 🚀 and the `pr` comment after the PR (S-194), and the diagnosis comment (S-186). | `product-engineer` (with @llipe) |
| DF-188-04 | Either no action is needed, or add one line to spec §8.3 and §8.6 (and FR-7's note): "Without `PANEL_BASE_URL`, the comment names the run id." | `product-engineer` |
| DF-188-05 | Re-home RT-07 to S-190 (orchestration), or to S-194 once the PR state exists. Update test plan §11 step 7 and the matrix rows. No S-188 code change is needed. | `product-engineer` |
| DF-188-06 | Regenerate the #370 body's AC and Files sections from stories v2.3, with a 📌 Decision comment that cites DF-33. | `product-engineer` (via `github-ops` conventions) |
| DF-188-07 | (1) Drop the duplicate `claim.py` line in Relevant Files. (2) Refresh the roadmap's Wave A row: S-185 and S-186 merged (#451, #453), with S-188 to follow once #454 merges. | (1) `developer` or `product-engineer`; (2) `planner` |

Why ratify the current behaviour for DF-188-03:

- It is D-67's default.
- A claim comment that couldn't be removed still tells the reader "working on this issue", and a `failed` run surfaces that to the operator through the webhook notifications.
- A sustained GitHub fault is exactly what the per-rule breaker should count.
- The orphaned claim does no harm: it stops counting the moment the loser ends, and it can never outrank the winner.

The case for deciding now: S-190 wires these outcomes into `main.py`, so leaving the slice open hands an unratified choice to the next story.

`verifier` applies none of these changes.

---

## 6. Reconciliation

`product-engineer` write-back, confirmed by @llipe 2026-10-24 (same PR as D-112 / OQ-1).

| Finding | Route |
| --- | --- |
| DF-188-01, DF-188-02, DF-188-05 | Spec v2.5 / test plan v2.3 (also stories v2.4, matrix v2.2, D-67 amendment). The `github_client.py` docstring fix for DF-188-02 is a small code follow-up. |
| DF-188-03 | DF-38 race-loss part decided: a non-404 `DELETE` fault ends `failed` with its D-67 code, no disposition, no board call; a 404 ends `not_applicable`/`active_run` (spec v2.5 §8.6, §8.9; D-54 amendment; TC-185-14) |
| DF-188-04 | Accepted as is |
| DF-188-06 | The #370 body is refreshed by the planner |
| DF-188-07 | Planner bookkeeping |

Non-blocking: ran after the #454 merge.

---

## Output contract

- Mode / phase: Audit / Phase 4 complete.
- Sources:
  - #370;
  - task list §9.0 (story branch);
  - spec v2.4, stories v2.3, test plan v2.2, matrix v2.1 and decisions, all from `origin/integration/bug-fix-agent-wave-a`;
  - PRD v2.1;
  - PR #454 diff `origin/integration/bug-fix-agent-wave-a...origin/story/S-188-claim-race`.
- Artifact: `workstream/fidelity-report-S-188.md` (not committed, as instructed).
- GitHub publication: not posted by this run. The caller (planner) publishes the header and verdict to #370 or PR #454.
- AC coverage: 5 of 5 story ACs have per-AC results, and none is uncovered. The live AC-3 and AC-20 evidence is for S-198.
- Verdict: Fidelity High; highest drift impact Minor.
- Blocking gaps: none.
