# Fidelity Report — S-186 (#368): Markers, reactions and the idempotent disposition

**Fidelity: High** · **Highest drift impact: Minor** · Scope: story S-186 / issue #368, Draft PR #451, branch `story/S-186-markers-disposition` (head `eb268bb`) → base `integration/bug-fix-agent-wave-a`.

Drift findings are advisory and **non-blocking** to PR readiness and issue completion. They route to `product-engineer`'s `activity-drift-reconciliation`.

## Changelog

| Version | Date | Summary | Author |
| ------- | ---- | ------- | ------ |
| 1.0 | 2026-10-24 | Audit Mode run for S-186 against PRD v2.1, spec v2.2, task list §7.0, decisions D-53/D-65/D-80/D-81/D-85/D-93/D-104 (D-107/D-108 for scope), and test plan / traceability v2.0. | verifier |

## 1. Summary for stakeholders

This story adds the bookkeeping the bug-fix agent needs to leave clear, trustworthy signals on a GitHub issue.

Every comment the agent posts now starts with a hidden tag that says which run wrote it and why. The agent believes a tag only if GitHub reports that the fleet's own App posted it, so a person cannot fake one.

When a run stops without producing a fix, the agent posts one explanation comment and adds a 😕 reaction. The comment says why it stopped and what it tried. The agent leaves labels, assignees and the issue itself alone, so anyone can retry later.

If the explanation is already there, a second attempt writes nothing. If the run is shut down from outside, the agent tries to post the explanation within 10 seconds. It only does that when it is sure it owns the issue.

Text written by the AI model is cleaned before it is posted. Words like "Fixes #9" cannot close other issues, and "@name" cannot notify anyone.

Two things differ from the written plan, and both make the result safer or cheaper:

- **Cross-repository references.** A reference to an issue in another repository stays as written, for example `(ref o/r#1)`. The plan's literal rule would have rewritten it to `(ref #1)`, which points at the wrong issue.
- **Test double.** The tests use a small in-house stand-in for GitHub instead of the third-party `responses` library.

Nothing is wired into the agent's main flow yet. The claim and orchestration stories (S-188, S-190) do that.

## 2. Per-AC results

| AC-ID | Description | Codebase evidence | Workstream evidence | Test evidence | Result |
| ----- | ----------- | ----------------- | ------------------- | ------------- | ------ |
| S-186-AC1 | Build and parse `claim`, `disposition`, `refusal` (`reason=`), `pr`. The leading marker block is read from line 1 (D-80, D-104). | `markers.py:49-116`. There is an exact `fullmatch` grammar, a lowercase canonical UUID, and the six D-104 reasons. `parse_block` stops at the first non-marker line, a blank line included. CRLF is handled by `removesuffix("\r")`. | Task 7.1 and 7.4 are checked. Spec §8.3 matches. | `test_markers.py` covers TC-186-01/02/03/06/07/17 (36-hyphen, BOM, ZWSP, fence, look-alike hyphen). `test_markers_property.py` covers RT-02 (1)-(6). `test_markers_contract.py` covers CT-32, with byte-exact goldens, and `claim-crlf.md` keeps its CR bytes through `.gitattributes`. | Pass |
| S-186-AC2 | A marker is trusted only with `performed_via_github_app.id == App ID` and `user.type == "Bot"`. | `markers.py:133-144`. Both values must be `int` and bools are rejected. The login is never read. `trusted_markers` skips untrusted comments before parsing. The App id comes from the `github_installations` row: `credentials.py:44, 239`, kept on refresh. | Spec §8.3, D-53 and the issue's technical note match. | TC-186-04/05 cover a human author, another App, a `null` or absent App, `User`/`Organization`, `"123"` vs 123, `True` and float. CT-08 cases are in `test_markers.py`. `test_credentials.py` covers `app_id` resolution and refresh. | Pass |
| S-186-AC3 | Reactions `eyes`/`rocket`/`confused` on a comment id. A missing `trigger_comment_id` skips silently (D-93). | `issues.py:224-246`. A closed set of three reactions. `None` returns `skipped` with no HTTP call. A 4xx is logged and returns `failed`. A 5xx, 429 or transport error raises (D-67). | Task 7.6 is checked. | `test_issues.py::TestReactions` covers each reaction, a 200 for an existing reaction, a skip with no call, 404/422 not fatal, and a 5xx raising. `test_disposition.py::test_no_reaction_without_trigger_comment_id`. | Pass |
| S-186-AC4 | `neutralize.py` implements D-65: closing keyword + reference → `(ref #N)`, and `@` → `@` + U+200B. | `neutralize.py:30-57`. Closing keywords are case-insensitive with an optional colon. References are `#N`, `owner/repo#N`, an issue or pull URL, or `GH-N`. The function loops to a fixed point and is idempotent. `ZWSP` is verified as U+200B. | Spec §8.7 and D-65 say "→ `(ref #N)`", for `owner/repo#N` and URLs too. | `test_neutralize.py` and `test_neutralize_property.py` cover RT-12 (1)-(4) with an independently written oracle and 2000 examples. TC-186-16 asserts `(ref o/r#1)`. | Drift (DF-186-01, Intended) |
| S-186-AC5 | The diagnosis comment covers what was tried, why it stopped, and the diffstat on a cap. It has a `disposition` marker, neutralized model text and 😕. No label or assignee change. A no-op when a trusted disposition exists. | `disposition.py:85-141` builds the body: CRLF is normalized, then the text is scrubbed, neutralized, and `<!--` is defused. A fixed line after the marker means model text cannot join the block. Parts shrink to fit 65,536 UTF-16 units. `disposition.py:221-249`: a trusted-marker check, then one POST comment, 😕 and the board hook. The write surface in `issues.py` is GET/POST comments and POST reactions only: no PATCH, PUT, DELETE, labels or assignees. | Spec §8.8, D-85 and D-93 match. | TC-186-08 asserts the exact write list, and no `/labels`, `/assignees` or issue PATCH. TC-186-09 covers secrets. TC-186-10 covers size, CRLF and a reaction 4xx/5xx. TC-186-11 makes zero writes (same and fresh disposer). TC-186-12 shows a forged or other-run marker does not suppress. TC-186-16 covers neutralization and fake-marker inertness. RT-15 runs 1000 examples. | Pass |
| S-186-AC6 | The backstop disposes with a 10 s budget before `fail()`, only after confirmed ownership (D-81). | `signal_backstop.py:45, 81-120`. `DISPOSITION_BUDGET_SECONDS = 10.0`, and the disposition runs in a daemon thread with `done.wait(budget)`, then `fail()`. `disposition.py:184-188`: `backstop_action()` returns `None` before `confirm_ownership()`, and `dispose()` re-checks it. | Spec §8.6 step 3, §8.8 and FR-23 match. | TC-186-13 shows dispose, then `fail()`, with a real `os.kill(SIGTERM)` variant. TC-186-14 shows no calls when there is no disposer or ownership is unconfirmed, and that slow GitHub is abandoned at the budget while `fail()` still runs. | Pass (residual: DF-186-04) |

AC coverage: 6 of 6 story ACs have evidence from all four sources. The PRD AC-11 and FR-22/FR-23 behaviour is delivered at module level, and end-to-end wiring is S-188/S-190.

## 3. Drift catalog

| ID | Description | Impact | Intent | Evidence | Owner |
| -- | ----------- | ------ | ------ | -------- | ----- |
| DF-186-01 | The neutralizer emits `(ref <reference as written>)`, for example `(ref o/r#1)` or `(ref https://github.com/o/r/issues/5)`. D-65, spec §8.7 (it explicitly lists `owner/repo#N` and URLs → `(ref #N)`), S-186-AC4, S-194-AC3 and test plan TC-186-16 all say `(ref #N)`. For `#N` the output is exactly `(ref #N)`. The literal rule would turn a cross-repository reference into a local `#N` that points at the wrong issue. The deviation keeps D-65's purpose, which is that nothing is closed on merge. The implementation also accepts `GH-N`, which is wider than the spec. | Minor | Intended | `neutralize.py:10-14, 53`; `test_neutralize.py:39-42`; `test_disposition.py:296`; README "Markers and disposition". Developer-flagged. | `product-engineer`: amend D-65, spec §8.7, S-186-AC4, S-194-AC3 and TC-186-16 to "`(ref <reference as written>)`; `#N` → `(ref #N)`". No code change. |
| DF-186-02 | The L2 tests use an in-memory `requests.Session` double (`tests/component/fake_github.py`), not `responses` as spec §14 and test plan §L2 / RT-13 state. Real URL, header and JSON construction and the error mapping are exercised. Real `requests.Response` semantics (Link-header parsing into `.links`, a case-insensitive header dict) are not, because the fake supplies `.links` directly. No sibling agent uses `responses` (`code-review` uses its own `StubTransport`), and `TESTING.md` documents the double accurately. Downstream stories (S-185, S-188, S-199 with Projects GraphQL) are planned against `responses`, so the harness choice should be made once. | Minor | Intended | `fake_github.py:1-8, 37-53`; `TESTING.md` bug-fix row; spec §14 L2 row; test plan line 83 and RT-13. Developer-flagged. | `product-engineer`: decide on one L2 GitHub harness. Either amend spec §14 and the test plan to "a `requests.Session`-boundary double", or ask `developer` to adopt `responses` from S-185 on. |
| DF-186-03 | Property-test budgets are below plan. RT-02 runs `max_examples=300` against the planned 1000. RT-12's input is at most 25 pieces of up to 40 characters, against the planned 0–20,000 characters. RT-12 (2000) and RT-15 (1000) meet their iteration counts. | Minor | Undetermined | `test_markers_property.py:45, 54, 63, 92`; `test_neutralize_property.py:35-45`; test plan RT-02 and RT-12. | `developer`: raise RT-02 to 1000 and add a long-text strategy to RT-12, or `product-engineer` lowers the plan budget. |
| DF-186-04 | Suppose SIGTERM lands while the `finally`-path disposition is in flight on the main thread. The Python handler also runs on the main thread, so the in-flight disposition is suspended. The backstop worker sees `_busy` and returns `in_progress` at once. `fail()` and the re-raised SIGTERM then end the process, so neither path completes. There is no double post (spec goal met), but possibly no diagnosis either. Recovery is the reaper plus a later `/bug-fix` (D-94), and the claim comment stays visible. Also, the `fail()` detail always says "Disposition attempted before stopping." even when the result was `in_progress`, `already_disposed` or `not_owned`-equivalent. | Minor | Undetermined | `disposition.py:192-201, 227-228`; `signal_backstop.py:101-120, 152`; README states "nothing when … a disposition is already in flight". The final shape depends on S-190 wiring. | `product-engineer`: confirm this is acceptable under FR-23 and D-94, or have S-190 run the `finally` disposition off the main thread. Optional `developer` follow-up: report the result status in the `fail()` detail. |

No Critical or Major drift.

### Explicit checks requested

- **Marker trust.** The App id must be an `int`, bools are rejected, and `user.type == "Bot"` is required. Only the leading block is read, and a marker after a blank line, inside a fence or after text is inert. **Pass.**
- **No label or assignee writes, and no issue edits (D-93).** The module surface has no such call, and TC-186-08 asserts it. **Pass.**
- **No reaction without `trigger_comment_id`.** It returns `skipped` before any HTTP call. **Pass.**
- **Backstop.** It runs only after `confirm_ownership()`, with a 10 s budget, and `fail()` always runs, including after timeouts and raising getters. **Pass**, with the DF-186-04 residual.
- **Token handling.** `IssuesClient` takes the installation token as a string or callable. No new module references the Projects PAT. Errors carry method, path and status only, and transport exceptions are raised `from None`. Event text is scrubbed. **Pass.** Binding the client to the App token, never the PAT, is a wiring concern for S-188/S-190.
- **Truncation and CRLF.** Comments are cut to 65,536 UTF-16 units, so emoji count as two. The disposition shrinks `tried`, then `diffstat`, then `why`, so the marker, the sections and the retry line survive. Inputs are CRLF-normalized and the parser accepts CRLF. **Pass.**
- **README.md and TESTING.md.** Both are accurate against the code: signatures, the 10 s budget, the `(ref <reference>)` wording, the fake-GitHub harness and the marker goldens. `TESTING.md`'s harness statement diverges from spec §14 (DF-186-02).
- **Roadmap.** The Wave A row is `In progress` and lists S-186 as missing until it merges. This is consistent, and no roadmap-mismatch finding applies.
- **D-107/D-108 scope.** The trigger-side 👎 and the guardrail scope are correctly absent from S-186. Its reaction set is `eyes`, `rocket` and `confused` only. 👎 belongs to the panel in S-200.

## 4. Edge-case and randomized outcomes

- **Gates (local, agent venv).** `lint`, `format-check`, `typecheck` and `audit` (pip-audit clean) pass. S-186 tests: 291 passed. Full suite: 1135 passed, 3 xfailed, coverage 97.89% (floor 90).
- **Local failure (environmental, out of scope).** `test_sandbox_proc.py::TestTimeoutReal::test_sigterm_ignored_child_is_killed_after_grace` fails 3 of 3 runs on macOS (`exit_code -15 != -9`). It is S-182 code, untouched by this diff. The CI job "Python quality gate (bug-fix, 3.13/3.14)" passes on PR #451. Classified as platform-environmental and inconclusive for S-186.
- **Edge matrix.** CRLF bodies, a diagnosis truncated to 65,536 characters, and a reaction 4xx logged and not fatal are all exercised (TC-186-10, TC-186-15).
- **Randomized tactics.** RT-02, RT-12 and RT-15 pass. Replay with `make test PYTEST_ADDOPTS="--hypothesis-seed=<seed> -k <test>"`. Budgets are covered in DF-186-03.
- **Documentation structure.** `core/checks` (`checkDocsStructure`) does not exist in this repository, so the check was not run. The diff changes no runbook or docs index.
- **Vocabulary conformance.** `docs/domain/ubiquitous-language.md` defines no terms, so there are no forbidden synonyms. The diff adds no `export` declarations, so there are no findings.
- **Runbook coverage.** Task 7.0 has no configuration, environment, tooling, credential or data steps, so the trigger is not met.

## 5. Recommendations

| Finding | Next step |
| ------- | --------- |
| DF-186-01 | `product-engineer`: write back the reference-as-written rule to D-65, spec §8.7, S-186-AC4, S-194-AC3 and TC-186-16. No code action. |
| DF-186-02 | `product-engineer`: decide on one L2 GitHub harness before S-185/S-188 start, and update spec §14 and the test plan, or have `developer` adopt `responses`. |
| DF-186-03 | `developer`: raise RT-02 to 1000 examples and add a long-text RT-12 strategy, or `product-engineer` lowers the plan budget. |
| DF-186-04 | `product-engineer`: accept the gap under D-94, or require S-190 to run the `finally` disposition off the main thread. `developer` may report the disposition result in the `fail()` detail. |

Status: complete, not blocked. This report is left uncommitted at the caller's request. Publishing it to #368 / PR #451 is left to the caller.
