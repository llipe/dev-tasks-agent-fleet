# Fidelity Report — S-185 (#367): Refusal checks and marked reply

**Fidelity: High** · **Highest drift impact: Minor** · Scope: story S-185 / issue #367, Draft PR #453, branch `story/S-185-refusal-checks` (head `82ab9c8`) → base `integration/bug-fix-agent-wave-a`.

Drift findings are advisory and **non-blocking** to PR readiness and issue completion. They route to `product-engineer`'s `activity-drift-reconciliation`.

## Changelog

| Version | Date | Summary | Author |
| ------- | ---- | ------- | ------ |
| 1.0 | 2026-10-24 | Audit Mode run for S-185 against PRD v2.1, spec v2.3 (§6, §8.2, §8.3, §8.6, §8.9, §9, §14), task list §6.0 (v2.0.6), decisions D-55, D-58, D-65 (amended), D-67, D-82, D-90–D-92, D-102, D-104, and test plan / traceability v2.1 (TC-185-*, CT-07/12/13/33/34, RT-13, RT-15, DF-33/34/38). | verifier |

## 1. Summary for stakeholders

When someone writes `/bug-fix` on an issue, the agent now checks, before doing any work, whether it should work on that issue at all.

It says no, and explains why in one short comment, when:

- the number is a pull request, not an issue;
- the issue is closed;
- a pull request for the issue is already open;
- another bug-fix run is still working on the issue;
- the run's settings are invalid.

The checks run in that order, and the agent stops at the first one that applies. The reply is fixed text for each reason. It never repeats anything from the issue or from the person who commented. A refusal adds no emoji reaction, claims nothing, and leaves any project board alone.

If posting the reply fails, the run still ends as "not applicable". If GitHub or the run database can't be reached, the run ends as failed with a clear error code. An outage is never read as "nothing in the way".

The agent also checks at the start that the GitHub App may write to issues. If it may not, the run fails at once without touching GitHub.

The developer flagged four places where the result differs from the literal plan. All four are reasonable:

- **Failed writes are not retried.** If GitHub fails while posting a comment, the agent does not post again, because the first attempt may already have gone through and a retry could post the comment twice. Reads and rate-limited requests are still retried.
- **"Retried 3 times" means 3 tries in total.** This matches the test plan's example. The spec's wording could be read as 4.
- **A run with no database record counts as finished.** The test plan already sets this rule.
- **The agent's own refusal note closes that run's claim.** This follows the story's acceptance criteria. Older wording in the spec says the opposite. In practice the case never comes up, because a run that refuses never claims first.

The audit also found three smaller gaps:

- **Pull requests from other repositories.** When the open pull request lives in another repository, the reply calls it `#M`. GitHub then links to the wrong pull request.
- **Rate-limit waits.** GitHub's "slow down" limits usually ask the agent to wait a minute. The agent waits at most 30 seconds, so in practice it gives up on these limits instead of retrying.
- **One GitHub error gets a different code.** A specific GraphQL error is reported as "request rejected", where the test plan expected "GitHub unavailable". Either way the run fails, and it never lets a duplicate pull request through.

Nothing is wired into the agent's main flow yet. That happens in S-190, and the panel link in the reply comes with S-188.

## 2. Per-AC results

| AC-ID | Description | Codebase evidence | Workstream evidence | Test evidence | Result |
| ----- | ----------- | ----------------- | ------------------- | ------------- | ------ |
| S-185-AC1 | Preflight: missing `issues: write` → `failed`/`GITHUB_PERMISSION_MISSING` (D-58); a `params.py` error → refusal `invalid_params` (D-82). | `credentials.py`: `mint_installation` returns `MintedToken(token, permissions)`, and a malformed `permissions` object becomes an empty read-only map, which fails closed. `has_issues_write` is true only for `== "write"`. `refusal.py:425`: the check runs before any `IssuesClient` exists, so it makes zero GitHub calls, and it precedes params (spec §8.2 order). `ParamsError` → `invalid_params` naming the key from the closed set (`SCHEMA_KEYS` + `params`). No usable `issue_number` → no write (DF-34 pin). | Tasks 6.2, 6.4 checked. Spec §8.2 preflight 1–2 and §6 row 1 match. | `test_permissions.py` (TC-185-01; CT-07 cases: read, absent, extra keys). `test_refusal.py::TestPermission` (TC-185-02, zero calls, precedes params). `TestCredentials` (TC-185-12). `TestInvalidParams` (TC-185-13, both branches). | Pass |
| S-185-AC2 | Refusal checks in order, first match wins: `pull_request`, `closed`, `linked_pr`, `active_run`. | `refusal.py:136-155` `decide()`: the order is exact; `linked_pr` and `active_run` are lazy thunks, so a later check never runs after a match. A fault propagates instead of becoming a verdict. `issues.py`: `IssueFacts` has `state` and `is_pull_request` only, with no labels. `linked_pr`: GraphQL `closedByPullRequestsReferences(includeClosedPrs:false)`, keeping `state == OPEN`, then open pulls with `head.ref.startswith("issue/<N>-")`, forks included and paged once per client. `active_run`: `open_claim_runs` (trusted claims minus `pr`/`disposition` via `markers.open_claims`, minus trusted `refusal`, minus own run), then `v_runs.effective_status ∈ {queued, running}`. | Tasks 6.1, 6.5, 6.6, 6.7 checked. Spec §8.2 table; D-55, D-92. | `unit/test_refusal.py` TC-185-16 (both closed and a PR; checks run in order; a fault propagates). `component/test_refusal.py`: TC-185-18 (PR open or closed, 404 → `invalid_params` with no write), TC-185-19 (prefix table, fork, deleted fork, closed-unmerged, GraphQL paging, open pulls paged once), TC-185-20 (non-terminal refuses; terminal proceeds; untrusted ignored; refusal is never a claim; own claim excluded). | Pass (see DF-185-04, DF-185-07) |
| S-185-AC3 | Exactly one comment: line 1 `<!-- agent-fleet:bug-fix:refusal run_id=<uuid> reason=<code> -->`, fixed text per code, run link, no model text, no reaction (D-104). | `refusal.py` `REPLY_TEXT`, `reply_line`, `build_reply`: the marker is built by `markers.build`; the variable parts are validated against closed sets (`#M` a positive int, `repo_gate` item, `invalid_params` key). The run link must match `https://\S+`, otherwise the backticked run id. The `refuse()` path makes one `post_comment` and no reaction call. | Spec §8.2 Reply; D-104. `PANEL_BASE_URL` is task 9.3 (S-188), so the run-id fallback is expected until then. | `unit/test_refusal.py` TC-185-17 (snapshot per code, line 1 round-trips, unsafe link fallback, closed sets). `component/test_refusal.py::TestEachRefusalWritesOnce` (TC-185-09: exactly one write, the marked POST). RT-15 `test_comment_bodies_property.py` (1000 examples). | Pass |
| S-185-AC4 | `succeeded`/`not_applicable` with `result.reason = <code>`; no claim and no board call (D-92, D-102). | `CheckOutcome.result()` → `{reason, summary}` with no `board` key. `report()` → `run.succeed("not_applicable", …)`. `refusal.py` imports no `claim` or `projects` module, and every GitHub request uses the installation token. | Spec §8.2, §8.9; FR-32. | TC-185-23 `test_no_claim_and_no_board_touch` (no PAT, no Projects query, no board metrics). `TestReport`. | Pass |
| S-185-AC5 | A reply-post failure is logged and the outcome is unchanged. Exhausted GitHub retries → `GITHUB_UNAVAILABLE`; a Supabase read failure in `active_run` → `SUPABASE_UNAVAILABLE` (D-67). | `refusal.py:441`: a broad `except` around the POST → `run.warn` plus a log; the outcome stays `not_applicable`; a reporter failure is swallowed. `github_client.request`: 3 attempts; reads retry transport errors, 5xx and rate limits; writes retry rate limits only. Any other 4xx → `GITHUB_REQUEST_REJECTED`. `RunStatusReader`: any transport error, non-2xx, non-JSON or malformed row → `SupabaseUnavailable`. Faults write nothing. | Task 6.3 checked. Spec §8.9 rows; §9 "retried 3 times". | TC-185-21 (`TestReplyFailure`: 403, 422, 502, 429, timeout). TC-185-11 (`TestGitHubFaults`: 5xx ×3 per route → `GITHUB_UNAVAILABLE`; 2×5xx then success). TC-185-14 (`unit/test_github_client.py`: reads, writes, GraphQL, the token never in messages). TC-185-22 (`TestSupabaseUnavailable`). | Pass (see DF-185-01, -02, -05, -06) |
| BR (D-90, D-91) | Labels never affect the checks; the commenter is not checked. | `IssueFacts` carries no labels; no `/labels`, `/collaborators`, `/orgs/*/members` or `/user` path exists in `issues.py` or `github_client.py`. | Spec §7; D-90, D-91. | TC-185-24 `TestNoCommenterCheck`. TC-185-25 `TestLabelsHaveNoEffect`. RT-13 `test_label_invariance.py` (200 examples, replay via `--hypothesis-seed`). | Pass |

**Other checks requested by the caller**

| Check | Result | Evidence |
| ----- | ------ | -------- |
| `Link`-header parser test (DF-186-02 condition) | Pass | `unit/test_github_client.py::TestLinkHeader` covers GitHub's four relations, garbage input, quoted and unquoted `rel`, a multi-valued `rel`, a real response header, the last page, and paging `IssuesClient` through real `Link` headers plus refusal of an off-resource `next`. `fake_github.py` hands the client pre-parsed `links`, as documented. |
| `main.py` wiring deferred to S-190; `PANEL_BASE_URL` to S-188 | Consistent | The task list puts `main.py` steps `preflight` → `refuse` in 11.4 (S-190), and `PANEL_BASE_URL` in 9.3 (S-188). `main.py` is untouched in the diff. The README states "Wiring it into `main.py` is S-190". |
| README (`agents/bug-fix/README.md`) | Accurate | The status table, layout, the "Refusal checks (S-185, spec §8.2)" section and the retry-policy paragraph match the code (3 attempts, write rule, 30 s cap, a missing `v_runs` row counts as terminal, labels and the commenter never read). |
| `TESTING.md` | Accurate | The `bug-fix` row names the GraphQL and fault-injecting double, `Link` parsing at L1, and the PostgREST `v_runs` double in `test_refusal.py`. The RT-13 budget (200) and the autouse no-sleep fixture in `tests/conftest.py` both exist. |
| Quality gates (re-run by verifier on an archive of `82ab9c8`) | Green for S-185 scope | 606/606 S-185-relevant tests pass. The full suite gives 1855 passed, 3 xfailed and 4 failed; all 4 failures come from the partial archive (repo-root `Makefile`/`supabase/seed.sql` absent), not from the code. `ruff check`, `ruff format --check` and `mypy` are clean. Coverage: `refusal.py` 100%, `credentials.py` 100%, `issues.py` 98%, `github_client.py` 95%, total 98%. |

## 3. Drift catalog

Every item below is **non-blocking** to PR readiness and issue completion.

| ID | Description | Impact | Intent | Evidence | Route |
| -- | ----------- | ------ | ------ | -------- | ----- |
| DF-185-01 | **Developer deviation 1: writes are not retried on 5xx or a transport error, only on rate limits.** Spec §9, task 6.3 and TC-185-14 say "5xx and secondary rate limits retried 3 times" with no read/write split. D-67 only names the code on exhaustion. **Judgement: sound.** A `POST /comments` that answered 5xx may have been applied, and a blind retry would double-post a refusal, claim or diagnosis. A rate limit is refused before it is applied, so retrying it is safe. Behaviour for S-185: a reply 5xx → logged, outcome unchanged (TC-185-21 holds). Downstream note for S-188: a claim POST 5xx ends `GITHUB_UNAVAILABLE` immediately, possibly leaving a landed claim; the run is then terminal, so refusal (d) is unaffected. | Minor | Intended | `github_client.py:279,295` (`retry_faults` false for writes); `test_github_client.py::TestWrites`; README retry paragraph | `product-engineer`: write the read/write split into spec §9 and TC-185-14/CT-13 |
| DF-185-02 | **Developer deviation 2: "retried 3 times" is implemented as 3 attempts in total.** TC-185-11 ("5xx ×3 → … then `GITHUB_UNAVAILABLE`") supports 3 attempts; spec §9 "retried 3 times" and CT-13 "at most 3 retries" literally read as 4 attempts. The difference is one extra try (about 3 s of backoff). **Judgement: acceptable; the wording is the gap.** | Minor | Intended | `github_client.py` `MAX_ATTEMPTS = 3`; `TestGitHubFaults::test_5xx_three_times…` asserts 3 hits | `product-engineer`: say "3 attempts" in spec §9, TC-185-14 and CT-13 |
| DF-185-03 | **Developer deviation 3: a claim whose run has no `v_runs` row counts as finished, with a warning.** Spec §8.2 is silent, but the test plan's CT-34 pins it: "An unknown `run_id` returns no row (pinned: treated as terminal)". Treating it as active would block the issue forever (D-94 intent). **Judgement: conforms to the plan.** One small gap: the warning goes to the Python log only, not to a `run_event` (`has_active_run` has no reporter), so the panel does not show it. | Minor | Intended | `refusal.py:311`; CT-34; `TestActiveRun::test_a_claim_with_no_v_runs_row_is_not_active` | `developer` (optional): emit the warning as a `run_event` when S-190 wires the reporter. `product-engineer`: lift the CT-34 pin into spec §8.2 |
| DF-185-04 | **Developer deviation 4: a trusted `refusal` marker for a claim's own run closes that claim, layered in `refusal.py` on top of `markers.open_claims()`.** This matches S-185-AC2, the issue body and TC-185-20 ("no `pr`, `disposition` or `refusal`"). It contradicts spec §8.3 ("refusal … never opens one"; only `pr`/`disposition` close), spec §8.6/S-188-AC2/task 9.1 ("no `pr` or `disposition`"), and the `markers.py` docstring ("A `refusal` never opens **or closes** a claim"). This is the still-open **DF-33**, and the traceability pin there ("`pr` and `disposition` close a claim") does not mention refusal. **Practical effect: none today.** Spec §4 puts `repo_gate` before the claim, and a lost race withdraws without a refusal reply, so a run never holds both a claim and its own refusal. **On placement:** do **not** move it into `markers.open_claims()` yet. That function is S-188's race-check input, and S-188's contract (§8.6, AC2, 9.1) excludes refusal, so moving it would silently change another story's behaviour. Once DF-33 is reconciled to one definition, it belongs in `markers.py` as the single source both callers use (one implementation, two callers), and the stale docstring goes. | Minor | Intended | `refusal.py:211-227`; `markers.py:22-24, 159-163`; `unit/test_refusal.py::test_a_trusted_refusal_for_the_same_run_closes_its_claim`; test plan DF-33 | `product-engineer`: resolve DF-33 (one open-claim definition across §8.2, §8.3, §8.6, S-185-AC2, S-188-AC2). Then `developer` (S-188): move the rule into `markers.open_claims()` and fix its docstring |
| DF-185-05 | **GraphQL `errors[]` and other non-transient read faults map to `GITHUB_REQUEST_REJECTED` with no retry.** CT-33 and EC-14 expect "retry, then `GITHUB_UNAVAILABLE`" for an `errors[]`/`data: null` response on the linked-PR query. Spec §8.9 defines `GITHUB_REQUEST_REJECTED` as "unexpected 4xx on a **write**", but it is also used for read 4xx (e.g. a 403 on `/pulls`), malformed read bodies and an off-resource `next` link. **Safety holds:** every case ends `failed` and is breaker-counted, never `not_applicable` and never "no linked PR". Only the code and the retry differ. The component test asserts the current mapping, so this was a choice, but it is not documented against CT-33. | Minor | Undetermined | `github_client.py:354`; `issues.py` `_closing_connection`; `TestGitHubFaults::test_graphql_errors_are_rejected_not_read_as_unlinked`; CT-33, EC-14; spec §8.9 | `product-engineer`: decide the code for non-transient **read** faults, then update spec §8.9 or CT-33/EC-14. Or `developer`: align with CT-33 |
| DF-185-06 | **Secondary rate limits are effectively not retried.** `MAX_WAIT_SECONDS = 30` gives up at once on any `Retry-After` over 30 s. GitHub's secondary limits typically send `Retry-After: 60`, and with no header, its guidance is to wait at least a minute; the client then backs off only 1 s and 2 s, so the retries are likely limited again. Spec §9 and TC-185-11 say secondary limits are "retried 3 times" and "`Retry-After` is honoured". The tests use only 3 s and 7 s. The 30 s cap is a deliberate run-budget guard (documented), but its interaction with secondary limits is not flagged. The outcome is still the correct `GITHUB_UNAVAILABLE`, only earlier. | Minor | Undetermined | `github_client.py:61, 287`; `test_github_client.py::test_secondary_rate_limit_403…` (7 s), `test_a_retry_after_beyond_the_cap…` | `product-engineer`: decide the cap against the run budget (e.g. allow about 60–90 s for secondary limits). Then `developer` adjusts and adds a 60 s case |
| DF-185-07 | **A cross-repository closing reference is named as a bare `#M`.** `closedByPullRequestsReferences` returns PRs from other repositories too, but the query selects only `number state`. The reply "pull request #M is already open for #N" auto-links to **this** repo's `#M`, which is a wrong link in the App's voice. `min(found)` also compares numbers across repositories. The refusal decision itself is correct (D-55 counts any open closing PR). CT-33 asks for "same repo and cross-repo" coverage; there is no cross-repo test. | Minor | Unintended | `issues.py:90, 316`; `refusal.py` `REPLY_TEXT["linked_pr"]`; CT-33 | `developer`: also select `repository { nameWithOwner }` and render `owner/repo#M` for a cross-repo PR (still a closed, validated set), preferring a same-repo PR; add the CT-33 cross-repo case |
| DF-185-08 | **Planned contract-test files are absent.** The test plan's S-185 execution order lists CT-07, CT-12, CT-13, CT-33 and CT-34. CT-07/12/33 are mapped to `tests/unit/test_github_contract.py` **(new)**, CT-13 to `tests/component/test_github_retry.py` **(new)** at L2, and CT-34 to `panel/tests/integration/bug-fix-runs-read.test.ts` **(new)** at L2.5. None were created. The behaviour is mostly covered elsewhere: CT-07 in `test_permissions.py`, CT-12 in `test_refusal.py::TestLinkedPr`, and CT-13 at L1 in `test_github_client.py`. Two gaps remain: CT-33's cross-repo case (DF-185-07), and CT-34's real `v_runs.effective_status` read against local Supabase, which no test covers. That read is the AC-24 evidence that a stale `running` row reads as `timed_out`; the agent side only uses a PostgREST double. | Minor | Undetermined | Test plan §5 rows CT-07/12/13/33/34 and execution order item 6; diff file list | `product-engineer`: update the traceability file mapping or reassign CT-34 to S-188/S-198. `developer` or `qa-engineer`: add CT-34 if it stays with S-185 |
| DF-185-09 | **Task 6.9 evidence is partial.** 6.9 is checked but lists `make validate` and "record `coverage_gate`". The note records the agent gate only (no repo-wide `make validate`) and `coverage_gate: SKIPPED(no-delegation)`, deferred to the planner's `qa-engineer`. This is the normal planner hand-off, but the checkbox overstates it. The verifier's re-run agrees with the agent-gate result. | Minor | Intended | `tasks-prd-bug-fix-agent-plan.md` 6.9 note | `planner`: record `make validate` and `coverage_gate` at the story gate |

### Observations (not drift)

- **Decision order and short-circuiting** are exact, and the unit tests prove that a later check never runs after a match. `invalid_params` is decided in preflight, before the issue is fetched, and a `GET /issues/{n}` 404 is `invalid_params` with no write (DF-34 pin).
- **The `get_paged` page cap** (100 pages, about 10,000 comments or open PRs) stops silently by design. On an issue past that size, a later claim marker could be missed (fail-open). This is unreachable in practice, so no action is needed. A `run_event` at the cap would make it visible.
- **`refresh_if_stale`** carries the old token's `permissions` forward. The preflight runs once at run start, so this does not matter for S-185.
- **Roadmap** (`docs/roadmap.md`, Wave A row): `In progress`, with S-185 listed under "What's missing". This is consistent with S-185 being unmerged. Outside this audit's scope: S-186 (PR #451) merged into the integration branch, but the row still lists S-186 as missing and omits #451. The `planner` should refresh the row at the next roadmap update. This is not a finding against S-185.
- **Runbook coverage (FR-49b/FR-49a):** no finding. No new script or workflow, and no three or more configuration, environment or credential steps in §6.0.
- **Documentation structure / vocabulary conformance:** not run. The repository has no `core/checks` module (`checkDocsStructure`, `checkExportedIdentifiers`) on this branch, and the diff touches no `docs/` files.

## 4. Edge-case and randomized test outcomes

| Item | Outcome |
| ---- | ------- |
| Both closed and a PR → `pull_request` first | Pass (TC-185-16, TC-185-18) |
| Linked PR from a fork; deleted-fork `null` head repo | Pass (TC-185-19) |
| Untrusted / forged claim ignored; forged closing marker does not close a trusted claim | Pass (TC-185-20, unit `open_claim_runs`) |
| Terminal claim (`succeeded`, `failed`, `timed_out`, `canceled`, `failed_to_start`) proceeds | Pass (TC-185-20) |
| Reply-post failure (403/422/5xx/429/timeout), reporter failure | Pass (TC-185-21) |
| RT-13 label invariance, 200 examples | Pass; replay `make test PYTEST_ADDOPTS="--hypothesis-seed=<seed> -k test_label_invariance"` |
| RT-15 refusal bodies, 1000 examples | Pass |
| CT-33 cross-repo closing reference | Not covered (DF-185-07) |
| CT-34 `v_runs` against local Supabase | Not covered (DF-185-08) |

## 5. Recommendations

| Item | Next step |
| ---- | --------- |
| DF-185-01, -02, -03 | `product-engineer`: wording write-back to spec §9/§8.2, TC-185-14, CT-13. No code change. |
| DF-185-04 | `product-engineer`: resolve DF-33. Then `developer` (S-188): put the single rule in `markers.open_claims()` and fix the docstring. |
| DF-185-05, -06 | `product-engineer`: decide the read-fault code and the secondary-limit wait cap. Then `developer` if either changes. |
| DF-185-07 | `developer`: render cross-repo PRs as `owner/repo#M`, prefer same-repo, add the CT-33 cross-repo test. |
| DF-185-08 | `product-engineer`: remap or reassign CT-07/12/13/33/34 in the traceability matrix; add CT-34 where it lands. |
| DF-185-09 | `planner`: record `make validate` and `coverage_gate` at the story gate. |
