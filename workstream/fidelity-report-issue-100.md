# Fidelity Report — Issue #100

## Header / Verdict

- **Overall fidelity verdict:** **High**
- **Highest drift impact present:** **None** (one Minor documentation-forward-reference nuance noted as observation, not drift)
- **Scope reference:** Issue #100 (`docs(agent): control plane must insert the queued runs row before invoking`) · Branch `issue/100-insert-before-invoke-contract` · Draft PR #105 · base `main`
- **Mode:** Audit (grey-box) · **AC coverage:** 3/3 covered · **Out-of-scope boundary:** Held
- **Reporting-never-kills-the-agent invariant:** Preserved

---

## Human-Readable Summary (what changed and why)

Issue #100 documented a trap discovered while verifying the reaper (#94): when someone
runs the agent by hand, the run could silently disappear. The reason is a division of
labor — the control plane is supposed to create the run record first, and the agent only
updates it. If nobody creates the record, the agent's update matches nothing, the database
politely says "OK" (HTTP 200) even though it changed zero rows, and the run vanishes with no
error anywhere. That cost real debugging time.

This work fixes that in three ways, and all three match what the issue asked for:

1. **The manual (README) now spells out the missing step.** Before you invoke the agent by
   hand, you must insert the "queued" row first. There's a ready-to-paste database command
   that creates the row and hands back the exact ID to use — so the two always match.
2. **The failure is now documented as a named symptom, with a diagnosis checklist.** If a run
   "goes invisible," the docs walk you straight to the cause (you skipped the insert) and the
   fix. It also clarifies a lookalike case — a run correctly marked `failed_to_start` by the
   reaper — so that correct behavior isn't misread as a bug.
3. **The agent now speaks up instead of staying silent.** When the agent's update genuinely
   matches zero rows, it prints a loud warning to the error log that names issue #100 and
   tells the operator what almost certainly went wrong. Crucially, it *warns and keeps going*
   — it never crashes the agent over a reporting problem. And if the check itself can't tell
   whether zero rows matched (e.g., the network hiccuped), it deliberately stays quiet to
   avoid crying wolf.

Nothing outside the request was built — in particular, no Phase 2 front-end/invocation route
was started, which the issue explicitly placed out of scope. The change was mirrored into
both copies of the reporting file byte-for-byte, honoring the "keep the vendored copy
identical" rule (D13). The full quality suite passes (434 tests, security audit clean).

---

## Per-AC Result Table

| AC-ID | Description | Codebase evidence | Workstream evidence | Test evidence | Result |
|-------|-------------|-------------------|---------------------|---------------|--------|
| AC-1 | README states the caller must insert the `queued` row before invoking, with a working example | `README.md` §Invocation → new "Prerequisite — insert the `queued` row before invoking (D1)" subsection with a runnable `INSERT … RETURNING id` and an explicit "row must exist first, run_ids must match exactly" note; stale older paragraph trimmed to point at it | Issue #100 Scope item 1; PRD D1 / spec §14 referenced verbatim | N/A (docs) — corroborated by direct read of delivered diff | **Pass** |
| AC-2 | The silent-no-op symptom and its diagnosis are documented | `README.md` new "Failure mode — run invisible (silent no-op)" subsection: cause (zero-match PATCH → HTTP 200), symptom (invisible in `runs`/`v_runs`, no error), fix, correct-reaper secondary symptom (`failed_to_start`, null `started_at`, not a bug), plus a 3-step "my run is invisible" checklist | Issue #100 Scope item 2; discovery traced to runbook `issue-94-reaper-verification.md` §4.0 | N/A (docs) | **Pass** |
| AC-3 | If the SDK change is adopted, a zero-match `start()` no longer passes silently | `agent_reporter.py`: new `_parse_content_range_count()` + `_SupabaseClient.update_expect_rows()` (`Prefer: return=headers-only,count=exact`, parses `Content-Range`); `RunReporter.start()` warns to stderr naming #100 **only on a confirmed `affected == 0`**, silent on `>=1`, silent on `None` (unknown). Mirrored byte-identically to `docs/reference/agent_reporter.py` (`diff -q` = identical) | Issue #100 Scope item 3 ("consider a defensive improvement… fail loudly or log a warning"); technical-guidelines §8 behavioral-property row + changelog 1.10 added | `tests/unit/test_agent_reporter_start.py` — 18 tests collected & **18 passed**: zero-row warns, match silent, unknown-count silent, `count=exact` header sent, 4xx→None without retry, transient→None never raises, `start()` never raises even on zero | **Pass** |

---

## Drift Catalog

No blocking drift. Items below are classified for completeness; all are **non-blocking to completion**.

| # | Description | Impact | Intent | Evidence source(s) |
|---|-------------|--------|--------|--------------------|
| D-1 | Issue #100 Scope item 3 was phrased optionally ("*Consider* a defensive improvement… fail loudly **or** log a warning"). The team adopted the softer of the two offered options — **warn-and-continue**, not fail-loud-and-abort. This is an in-bounds design choice explicitly permitted by the AC ("**If** the SDK change is adopted") and is the correct one given the "reporting never kills the agent" invariant (§8). | Minor | **Intended** | Issue #100 body (AC3 wording); `agent_reporter.py` `start()`; technical-guidelines §8 / changelog 1.10 |
| D-2 | `agent_reporter.py` is excluded from the coverage report, so the 18 new tests' lines are **not credited** in the 94% figure. Tests genuinely exist and pass (verified independently); this is a metric-attribution gap, not a coverage gap. Matches the qa-engineer caveat. | Minor | **Intended** (pre-existing D13 coverage-omit policy; consistent with prior stated gap that `agent_reporter.py` has no credited coverage) | `make validate` coverage table (file absent); `pytest` run of the new file (18 passed) |
| D-3 | Observation (not drift): the README trims the old CLI-note paragraph to forward-reference the new "Prerequisite" subsection, which sits **above** it in the file. Forward/backward reference is internally consistent (the new subsection precedes the CLI note), so no dangling reference. | Minor | **Intended** | `README.md` diff (both hunks read together) |

---

## Focused Findings on the Two Explicit Audit Questions

**1. Did the out-of-scope boundary hold?** **Yes.** The single out-of-scope item — building the
Phase 2 front-end invocation route — is absent. A workspace search for a Next.js `route.ts`,
`app/api/agents`, or a front-end `InvokeAgentRuntime` call surfaced only pre-existing CDK
(`agentcore/cdk/…`) and prototype (`docs/prototype/…`) files, none touched by this diff. The
delivered change set is confined to docs (README, technical-guidelines), the two `agent_reporter.py`
copies, one new unit-test file, and the workstream task list.

**2. Does warn-and-continue preserve "reporting never kills the agent"?** **Yes — verified, not
assumed.** `start()` on `affected == 0` calls `print(..., file=sys.stderr)` and falls through to
the normal `_attach_logging()` / `self.log("Ejecución iniciada.")` path — there is **no `raise`,
`sys.exit`, or exception** on the zero-row branch. `update_expect_rows()` itself catches every
exception (`except Exception`), returns `None` on failure, and never propagates. The test
`test_start_never_raises_even_on_zero` asserts this directly. This is strictly consistent with the
existing §8 invariant ("reporting never kills the agent") and with the sibling `_request`/`update`
retry-then-stderr behavior. The decision to warn **only** on a *confirmed* zero (and stay silent on
an unknown `None` count) is the correct guard against false alarms when a request fails or the
`Content-Range` header is absent.

---

## Evidence Corroboration (independently executed, not trusted)

- **D13 byte-identical mirror:** `diff -q agents/dependency-update/app/dependencyUpdate/agent_reporter.py docs/reference/agent_reporter.py` → **identical**.
- **New tests:** `pytest tests/unit/test_agent_reporter_start.py` → **18 passed** (10 functions, parametrization expands to 18 — the "18 tests" claim is accurate).
- **Aggregate gate:** `make validate` from `agents/dependency-update/app/dependencyUpdate/` → **434 passed**, TOTAL **94%** branch coverage, `pip-audit . --strict` → "No known vulnerabilities found", "validate: all gates passed".
- **Coverage-omit caveat:** `agent_reporter.py` does not appear in the coverage table — corroborates the qa-engineer note that the new SDK lines are not credited in the 94% (tests pass regardless).
- **Source-of-truth AC text:** fetched live via `gh issue view 100` — the delivered ACs match the issue body exactly.

---

## Recommendations (per item — no change applied by this audit)

| Item | Recommendation |
|------|----------------|
| D-1 (warn vs. fail) | **No action needed.** Warn-and-continue is the correct reading of AC3 under the §8 invariant. |
| D-2 (coverage attribution) | **No action needed for this issue.** If credited coverage of `agent_reporter.py` is ever wanted, that is a separate, pre-existing testing-gap item owned by `qa-engineer` — not #100 drift. |
| D-3 (README structure) | **No action needed.** Internal references are consistent. |
| AC3 live behavior | Optional (not required for #100 completion): the zero-row warning path is unit-verified against mocked PostgREST; a future live smoke against a real Supabase instance would confirm the `Content-Range`/`count=exact` header contract end-to-end. Track under existing infra-verification issues if desired; **does not block** #100. |

**Note:** This audit is additive and non-blocking. It does not gate PR #105 or issue #100
completion, and it does not replace the existing quality gates (all of which passed). Any drift
routing is handled by `product-engineer`'s `activity-drift-reconciliation` flow — this report does
not write back into the task list, issue checklist, or PRD/spec.
