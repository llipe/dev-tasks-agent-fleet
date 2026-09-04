# Fidelity Report — Story S-107 (Agents Dashboard, issue #120)

## Header / Verdict

- **Overall fidelity: High**
- **Highest drift impact present: Minor**
- **Scope:** S-107 "Agents Dashboard with three-variant density toggle" · issue #120 · branch `story/S-107-agents-dashboard` · draft PR #139
- **Mode:** Audit (grey-box) · sources cross-checked: codebase implementation, `/workstream` artifacts, test suite (run live), PRD/spec/DESIGN intent
- **Gate note:** This audit is **additive and non-blocking**. It does not gate PR #139 or issue #120, and it does not replace `test`/`lint`/`format:check`/`typecheck`/`audit`. All drift below is classified **Intended** — no code fix is required for any item.

---

## Human-Readable Summary (for the PR/issue)

S-107 delivers the Agents Dashboard as specified, and the delivery is faithful to the story, the spec, and the Nocturne design contract. All eight acceptance criteria are met, and the one requirement most likely to be silently wrong — that every displayed status, including the aggregate breakdown, is the *effective* status rather than the raw database status — is implemented correctly and proven live against the local database: a run that has blown past its timeout but hasn't been reaped yet is counted as `timed_out`, never as `running`.

The dashboard reads the database exactly twice no matter how many agents exist (never once-per-agent), and it counts an agent with more than 1,000 runs truthfully instead of stopping at the database's 1,000-row page limit — both verified against a real seeded database, not just asserted in code. The three layout variants (dense rows, cards, ledger) all render from that single read; switching between them is a pure presentation swap that provably never refetches or navigates. The chosen density survives a page reload; the filter deliberately does not, so a stray filter can't hide agents on the next visit. The two "empty" situations — no agents configured vs. a filter that matches nothing — read differently, so an operator who filters and sees nothing is never misled into thinking the fleet disappeared.

Three deliberate deviations are worth naming so nobody re-flags them later as defects, and all three were pre-decided and recorded:

1. **Time-range chips (7d/30d/all) were not built** — only the implicit "all" window ships. This is the escape hatch the story's own Business Rules grant ("if the aggregate cost is non-trivial, ship 'all' only and record the reduction"). Building client-side chips would misreport counts, and server-side chips would need a URL write that reintroduces the forbidden refetch.
2. **1024px "no horizontal scroll" is not automatically tested** — jsdom has no layout engine, so it rests on token-driven CSS plus manual comparison, with the browser-level check deferred to the S-114 Playwright suite. This is exactly what test-plan gap G7 prescribes.
3. **The agent's slug is displayed as plain text, not as a second link** to run history, and the ledger variant reaches run history by keyboard rather than by a per-row link. The story wording ("name/slug links") is satisfied by the name link; this is a presentation reading, not a missing feature.

Verification was run live: the S-107 unit suites (dashboard 18, density-state 16, summary-view 9) and the Layer 2.5 dashboard-query suite (CT-1, CT-7, CT-8, plus the seeded-shape check) all pass against a reachable local Supabase. One honest caveat: the Layer 2.5 suite only runs when a service-role key is exported — the default `make validate` on a machine without that key skips it green. That is the known G2 harness hole, not a defect in S-107, and the PR should state (as it does) that the suite *ran live* for this delivery.

---

## Per-AC Result Table

| AC | Description | Codebase evidence | Workstream evidence | Test evidence | Result |
| --- | --- | --- | --- | --- | --- |
| AC-107.1 | `/` lists every `is_enabled` agent with dot, name, slug, description, run count, breakdown, last-run time + outcome | `queries.getEnabledAgents` (`.eq("is_enabled", true)`); `DenseRows`/`AgentCards`/`Ledger` render all fields; `page.tsx` server component | Story S-107 AC1; test-plan CT-1/CT-7 | `dashboard.test.ts` (shaper), `dashboard.test.tsx` (render), `dashboard-query.test.ts` seeded-shape (**ran live**) | **Pass** |
| AC-107.2 | Three §5.1 variants render from the same data; dense default | `DashboardClient` swaps `DenseRows`/`AgentCards`/`Ledger` on one `agents` prop; no per-variant fetch | Story AC2; CT-2, EC-8, EC-10 | `dashboard.test.tsx` variant + no-refetch (mock `next/navigation`, assert push/replace/refresh never called) | **Pass** |
| AC-107.3 | Density persists client-side, survives reload | `density-state.ts` (`localStorage`, closed `{dense,cards,ledger}` vocabulary, default `dense`); `DashboardClient` reconciles in mount effect | Story AC3 (PRD AC9); CT-4, CT-5, EC-5, EC-12, EC-24 | `density-state.test.ts` (16), component persistence-on-mount | **Pass** |
| AC-107.4 | Displayed status derives from `v_runs.effective_status`, **incl. aggregate breakdown** | `dashboard.ts` derives every run + `lastRun` + `breakdown`/`legend` via `effectiveStatus`; never reads raw `.status` for display | Story AC4 (FR11a); CT-1, CT-2, CT-3, EC-4, EC-23 | `dashboard-query.test.ts` CT-1 stale→`timed_out` in breakdown (**ran live**); `token-discipline`/CT-3 no third SD4 copy | **Pass** |
| AC-107.5 | Name/slug links to run history; Invoke action links to invoke route | `DenseRows`/`AgentCards`: name → `<Link href={/agents/${slug}}>`; Invoke → `<Link>` when route available, disabled `<Button>` while `INVOKE_ROUTE_AVAILABLE=false` (S-113) | Story AC5; Technical Notes (Invoke inert until S-113); EC-13 | `dashboard.test.tsx` link + disabled-invoke assertions | **Pass (with Minor drift D3)** |
| AC-107.6 | Empty state legible; no-match distinct from "no agents", no `NaN` | `DashboardClient` `EmptyNoAgents` vs `EmptyNoMatch` (names the query); zero-run agents render "no runs yet", not `NaN` | Story AC6; EC-19, EC-25 | `dashboard.test.tsx` both empty states; distinct-copy assertion | **Pass** |
| AC-107.7 | Ledger `Up`/`Down` clamped roving tabindex, `Enter`=Invoke target, `/` focuses filter | `Ledger.tsx`: roving `tabIndex`, clamp `Math.min/Math.max` (no wrap), `Enter`→`activate`→`invokeHref` (inert when null), `/`→`onFocusFilter` | Story AC7 (escape hatch withdrawn, v1.2); test-plan G4 resolved; EC-26, task 2.13a coupling guard | `dashboard.test.tsx` per-key + hint/behavior coupling | **Pass** |
| AC-107.8 | Filter input in all three variants; name+slug, case-insensitive; never refetch/navigate; not persisted | `AgentFilter` in shared header (`DashboardClient`); `matchesQuery` literal `String.includes` (no `RegExp`); transient `useState`, never written to storage | Story AC8 (added v1.2); Business Rules (transient, name+slug only); EC-25, EC-26 | `dashboard.test.ts` predicate (metachars literal), `dashboard.test.tsx` filter-in-all-variants + no-navigation | **Pass** |

**AC coverage: 8 / 8 covered. No uncovered AC. No blocking gap.**

---

## Drift Catalog

All drift is **Intended** and **non-blocking to completion**. No `developer` fix is required; items D1–D2 are candidates for optional PRD/spec/story write-back via `product-engineer`'s `activity-drift-reconciliation`, and D3 is a wording clarification only.

| Drift | Description | Impact | Intent | Evidence source(s) | Non-blocking |
| --- | --- | --- | --- | --- | --- |
| **D1** | **Time-range chips (7d/30d/all) not built** — only the implicit "all" window ships. `/DESIGN.md` §5.1 lists a time-range filter among common header elements; no chips exist in `components/dashboard/**`. | Minor | Intended | Codebase: `grep` for `7d/30d/timeRange` in `components/dashboard/` returns nothing. Story S-107 Business Rules explicitly authorize "ship 'all' only and record the reduction". Rationale (recorded): client-side window misreports counts; server-side window needs a `searchParams` write that reintroduces the forbidden refetch (violates AC-107.2 / EC-8). | Yes — story grants the reduction |
| **D2** | **AC-106.6-style 1024px "no horizontal scroll" not asserted in an automated test** for the dashboard screens. jsdom computes no geometry. | Minor | Intended | Codebase: no jsdom width/overflow assertion. Test-plan G7 prescribes exactly this: manual at 1024/1440px now, Playwright scenario in S-114. Story Manual/UI Testing references the same. | Yes — deferred to S-114 by design |
| **D3** | **Slug rendered as plain text, not a second run-history link; ledger reaches run history by keyboard, not a per-row `<Link>`.** Story wording is "Agent name/slug links to that agent's run history." | Minor | Intended | Codebase: `DenseRows`/`AgentCards` — `name` is `<Link href={/agents/${slug}}>`, `slug` is a plain `<span>`. `Ledger` rows are `role="option"` in a listbox with `Enter`=Invoke, no per-row history `<Link>`. Story Technical Notes describe the ledger as keyboard-first (roving tabindex), so the ledger's navigation model is intentional. | Yes — name link satisfies the AC; "/slug" is presentation |

**Notes on classification:**
- **D1 and D2** are drift against a *design/plan expectation* (DESIGN §5.1 chips; AC-106.6-style geometry) that the story or test plan already pre-authorized reducing/deferring. They are Intended because the deviation was decided and recorded before implementation, not discovered after.
- **D3** is drift against the *literal* AC wording only. The functional intent — an operator can reach an agent's run history from the dashboard — is met in all three variants (name link in rows/cards; not present in ledger, which is invoke-first by design). No user-facing capability is missing. If the intent is that the slug *also* be a link, that is a one-line change, but it is not required by the functional criterion.

---

## Edge-Case and Randomized Test Outcomes

The Wave 3 compliance test plan (`test-plan-wave3-S-106-S-107-S-108.md`) is the design-mode counterpart to this audit. S-107-relevant scenarios and their observed status:

| Scenario | Intent | Observed |
| --- | --- | --- |
| CT-1 (aggregate counts `effective_status`) | Stale `running` → `timed_out` in breakdown | **Pass, live** — `dashboard-query.test.ts` |
| CT-2 (derived status reaches the pill) | Rendered output, not function return | **Pass** — component tree renders `timed_out`, `running` absent |
| CT-3 (no third SD4 copy) | Mechanical import-surface check | **Pass** — shaper imports `effectiveStatus`, restates no threshold arithmetic |
| CT-4 / CT-5 (untrusted `localStorage`) | Unknown/malformed/absent → default, no throw | **Pass** — `density-state.test.ts` |
| CT-7 (no N+1) | Request count flat as agents double (8→16) | **Pass, live** — two reads, equal count |
| CT-8 (bounded below `max_rows`) | 1,400 runs counted as 1,400, not 1,000 | **Pass, live** — internal `.range()` paging |
| CT-10 / CT-11 (formatters from `lib/format.ts`) | Single §7.1 relative form; no re-impl | **Pass** — variants call `formatRelative`/`formatRunCount`/`formatStatusLegend[Compact]` |
| EC-8 (variant switch no refetch) | Zero reads on toggle; no navigation | **Pass** — no data access in client tree; navigation-method spies |
| EC-19 / EC-25 (empty + no-match distinct) | Distinct copy naming the query | **Pass** — `EmptyNoAgents` vs `EmptyNoMatch` |
| EC-23 (future enum status) | Neutral fallback, no crash | **Pass** — `status-meta` fallback; breakdown drops unknown from named buckets but counts in `runCount` |
| EC-26 (`/` and `Escape` don't fight the input) | Second `/` types literal; `Escape` clears then blurs | **Pass** — `isTypingTarget` guard + `AgentFilter` Escape handler |

**Harness caveat (test-plan G2, not a defect):** the Layer 2.5 `dashboard-query.test.ts` is gated on **both** a reachable local DB **and** an exported `SUPABASE_SERVICE_ROLE_KEY`/`SERVICE_ROLE_KEY`. On a healthy stack *without* the key exported it skips green — observed directly during this audit (the suite skipped until the key was exported, then all 4 assertions passed). This matches G2's finding that some suites carry a precondition beyond `probeLocalDb`. The PR must state the suite ran live (it did, for this delivery).

**Randomized/property tests:** none in S-107 scope (no fuzz/seeded-random tactics apply to a read-only presentation story). No randomized-failure triage was required.

---

## Recommendations

| Item | Suggested next step | Owner |
| --- | --- | --- |
| D1 (time-range chips) | If the DESIGN §5.1 chip list should reflect the "all-only" reality, route to `product-engineer` for an optional DESIGN.md/story note. Otherwise **no action needed** — already recorded in Story Business Rules. | product-engineer (optional) / no action |
| D2 (1024px geometry) | **No action needed in S-107.** Carry the Playwright scenario in S-114 (#127) as already planned (G7). | S-114 |
| D3 (slug link / ledger navigation) | Clarify the AC wording ("name links; slug is text; ledger is invoke-first") via `product-engineer` if a literal-wording audit might re-flag it, **or** make the slug a link if that is the intent — a one-line, low-risk change. Not required for completion. | product-engineer (optional) / developer (optional) |
| G2 harness gate | Not S-107 scope. Tracked as #134 (CI must fail on a skipped Layer 2.5 project). Ensure PR #139 states the suite ran live. | planner / CI (#134) |

No item blocks PR #139 or issue #120. This audit ran after the developer completion gate and does not reopen or block it.

---

## Output Contract

- **Mode / phase:** Audit Mode · Phase 4 (Reporting & Publication)
- **Source artifacts:** `workstream/user-stories-prd-agent-fleet-panel-v2.md` (S-107, v1.2); `workstream/specification-prd-agent-fleet-panel-v2.md` (v1.6, referenced); `/DESIGN.md` (v1.1); `workstream/test-plan-wave3-S-106-S-107-S-108.md`; issue #120 body
- **Artifact written:** `workstream/fidelity-report-S-107.md`
- **GitHub target:** issue #120 / PR #139 (header + human-readable summary to be posted)
- **AC coverage:** 8 / 8 covered; 0 uncovered
- **Overall fidelity verdict:** High · highest drift impact: Minor (all Intended)
- **Blocking gaps:** none
