# Fidelity Report — Story S-105 (Design tokens, Nocturne primitives, formatters)

## 1. Header / Verdict

- **Overall fidelity:** **High**
- **Highest drift impact present:** **Minor**
- **Drift findings:** 5 (0 Critical, 0 Major, 5 Minor) — all classified **Intended**
- **Scope:** Issue #118 / S-105 · branch `story/S-105-design-tokens-primitives` · PR #133 (draft, base `main`)
- **Mode:** Audit (grey-box) · **Result:** all 7 acceptance criteria PASS · **Non-blocking:** drift does not gate completion.

Audit basis: read the delivered code on the feature branch (5 commits vs `main`, 50 files), cross-checked against `/DESIGN.md` v1.0 §2/§3/§6/§7/§8/§10/§11/§12, spec SD10/SD12, the S-105 story ACs, the wave-2 task breakdown, and the published test plan. Test suite executed live: **232 passed / 19 skipped** (integration `queries`/`rls-deny-all` skipped — S-104 layer, Docker-gated, expected). `git status` clean; no audit-time modifications.

## 2. Human-Readable Summary — what changed and why

S-105 delivers the panel's visual foundation: a single stylesheet of "design tokens" (every color, font, spacing step, corner radius, and shadow named once), twelve reusable UI building blocks (buttons, tags, status pills and dots, inputs, toggles, log lines, nav items, breadcrumbs, and two little run-history charts), a set of pure text-formatting helpers (clocks, durations, relative times, ID shortening, count legends), and a Phosphor icon set. There is also a developer-only "gallery" page for eyeballing every piece against the original prototype; it is switched off in production.

Everything asked for was built and matches the design contract. The build, type checks, linting, formatting, and tests all pass, and coverage on the new code is complete. The five items flagged below are **not defects** — each is a small, deliberate, documented choice the implementer made where the design document either contradicts itself or leaves a detail to a later story. The most notable: the design doc describes status pills two different ways in two different sections; the implementation followed the concrete component spec, so "running" and "queued" pills use a slightly lighter background tint and a marginally slower pulse than a second summary table suggests. Neither is user-visible as a fault, and status is always spelled out in words, so nothing is conveyed by color alone. A reviewer should confirm they are comfortable with these choices; none needs code change to close the story.

## 3. Per-Acceptance-Criterion Results

| AC | Description | Codebase evidence | Workstream evidence | Test evidence | Result |
|----|-------------|-------------------|---------------------|---------------|--------|
| AC1 | `styles/tokens.css` defines every §2 token incl. the four SD10 `--st-*`, utility aliases, typography, spacing, radii, shadows | `panel/styles/tokens.css:26-88` — core, neutral 100–900, accent 100–900, `--st-ok/-fail/-timeout` (`:64-66`), `--rule/--muted/--faint`, `--font-*`, `--space-1..8`, `--radius-*`, `--shadow-*`; running→`--color-accent`, failed_to_start→`--faint` reused per SD10 note | Story AC1; SD10 flag on the two reused colors | token-discipline test asserts `tokens.css` is the sole literal home; component tests consume the tokens | **PASS** |
| AC2 | No component hardcodes a hex, font-family, or px spacing; enforced by a lint/check where practical | All `*.module.css` use `var(--…)`; `globals.css` literal-free | Task 2.10 / G4 ("mechanical, not judgment") | `tests/unit/token-discipline.test.ts` — mechanical hex + `font-family` gate over `components/**` + `globals.css`; vacuity guard requires ≥12 modules scanned | **PASS** (see Drift D5 on the intentional px-scope carve-out) |
| AC3 | The twelve §11.2 primitives exist and are unit-tested (Button variants×sizes+disabled, Tag, StatusPill, StatusDot, NavItem, Input, LogLine, StatusBar, RunStrip, Toggle, KLabel, Breadcrumb) | All 12 present under `panel/components/*.tsx` (+ `.module.css`) | Story AC3; §11.2 inventory | 12 component suites, live-pass (Button 10, StatusDot 12, StatusPill 8, Toggle 5, LogLine 7, …) | **PASS** |
| AC4 | StatusPill/StatusDot cover all six statuses incl. `failed_to_start` (hollow) and running/queued pulse | `status-meta.ts:29-45` maps all six + `canceled` + unknown fallback; `hollow:true` for failed_to_start; `pulse:true` for running/queued; `StatusDot.module.css:.hollow/.pulse`; `StatusPill.module.css:.hollow/.pulse` | Story AC4 | `StatusDot.test.tsx` (12), `StatusPill.test.tsx` (8) incl. hollow + fallback | **PASS** (see Drift D1/D2 on pulse cadence + pill tint) |
| AC5 | Status conveyed by text never color alone; `:focus-visible` = 2px accent outline @2px offset, browser default rings suppressed | Every StatusPill renders `<span class=label>{meta.label}</span>`; dots are `aria-hidden`/decorative; `globals.css:88-96` `:focus-visible{outline:2px solid var(--color-accent);outline-offset:2px}` + `:focus:not(:focus-visible){outline:none}` | Story AC5; §12 Do; §6.4 | `StatusPill.test.tsx` asserts accessible text for every status | **PASS** |
| AC6 | `lib/format.ts` implements §7: 24h HH:MM:SS, relative times, `Xm XXs`, `running · Xm`, short uppercase-mono IDs, `n/m`, event counts, status legends | `panel/lib/format.ts` — `formatClock`, `formatRelative`, `formatDuration`, `formatDurationShort`, `formatRunningDuration`, `formatRunId`, `formatStepProgress`, `formatEventCount`, `formatStatusLegend(+Compact)`, `formatPagination` | Story AC6; §7.1–7.3 | `tests/unit/format.test.ts` — table-driven incl. zero/negative/sub-second, exact-minute, far-past, ID casing | **PASS** (see Drift D3 on the compact `14m ago` relative form) |
| AC7 | Icons from `@phosphor-icons/react` on `currentColor`, no Unicode stand-ins | `panel/components/icons.tsx` maps every §10 role to a Phosphor icon via `@phosphor-icons/react/ssr`; inherits `currentColor`; no glyph stand-ins remain in components | Story AC7; §10 mapping table | Icons rendered in `Breadcrumb` (`RowChevronIcon`) + gallery | **PASS** (see Drift D4 on the `✓✕⧗` legend glyphs — DESIGN content, not stand-ins) |

## 4. Drift Catalog

> All drift below is **non-blocking to completion** (verifier operating rule 8). All five are classified **Intended**. Routing: items D1–D3 warrant a `product-engineer` DESIGN.md reconciliation (spec-internal contradiction or an unimplemented compact form); D4–D5 are documentation-confirmations needing no action.

### D1 — Status-pill background tint uniform 14% (running/queued not 16%)
- **Evidence:** `panel/components/StatusPill.module.css:14` — `background: color-mix(in srgb, var(--st-color) 14%, transparent)` applied to every status. `/DESIGN.md` §8.1 lists running/queued pill BG as **16% accent**, while `/DESIGN.md` §3.4 (the concrete component CSS) specifies **14%** for all. The implementation follows §3.4.
- **Impact:** **Minor** (a 2-percentage-point tint delta on two statuses; not perceptible as a fault, meaning carried by text).
- **Intent:** **Intended** — DESIGN.md contradicts itself (§3.4 vs §8.1); implementer chose the concrete component spec.
- **Recommendation:** `product-engineer` — reconcile §3.4 vs §8.1 in DESIGN.md (pick 14% or 16% for running/queued and make both sections agree). No code change required if §3.4 is authoritative.

### D2 — `queued` pulse cadence 1.6s (not 1.4s)
- **Evidence:** `StatusDot.module.css:.pulse{animation:pulse 1.6s …}` and `StatusPill.module.css:.pulse{…1.6s…}` — a single pulse class at 1.6s for both running and queued. `/DESIGN.md` §8.1 gives `queued` = `pulse 1.4s`; §3.4/§3.9 and the running dot give `pulse 1.6s`.
- **Impact:** **Minor** (0.2s cadence difference on the queued state only).
- **Intent:** **Intended** — same §3.4↔§8.1 contradiction; implementer unified on 1.6s (the value stated in three of four DESIGN locations).
- **Recommendation:** `product-engineer` — reconcile the queued cadence in DESIGN.md §8.1. No code change if a single shared pulse keyframe is acceptable.

### D3 — Compact relative-time form (`14m ago`) not implemented
- **Evidence:** `lib/format.ts:formatRelative` returns `"{m} min ago"` for minutes, `"{h}h ago"`, `"yesterday"`, `"{d}d ago"`. `/DESIGN.md` §7.1 shows two minute forms: `2 min ago` (run-history table) **and** `14m ago` (both run-history table and dashboard last-run). The delivered formatter emits only the spaced `N min ago` form; there is no compact `Nm ago`.
- **Impact:** **Minor** (hours/days/`yesterday` forms match exactly; only the sub-hour "minutes" abbreviation differs, and DESIGN itself shows both spellings).
- **Intent:** **Intended** — the formatter is consistent and tested; §7.1 is ambiguous (lists both `2 min ago` and `14m ago`). No screen consumes it yet (dashboard is S-107), so there is no live divergence.
- **Recommendation:** `product-engineer` — clarify in DESIGN.md §7.1 whether dashboard last-run wants the compact `14m ago` form; if so, a follow-up (S-107) adds a `formatRelativeCompact`. Not an S-105 blocker.

### D4 — `✓ ✕ ⧗` glyphs in `formatStatusLegendCompact`
- **Evidence:** `lib/format.ts:formatStatusLegendCompact` emits `"{n} ✓ · {n} ✕ · {n} ⧗"`. AC7 forbids "Unicode glyph stand-ins" for icons.
- **Impact:** **Minor** (none, on inspection).
- **Intent:** **Intended** — these are `/DESIGN.md` §7.3 *content* (the "Cards compact" legend literally specifies `65 ✓ · 11 ✕ · 6 ⧗`), not the §10 nav/action *icon* stand-ins AC7 targets. Explicitly noted in `panel/README.md` (Icons section) and matches DESIGN §7.3 exactly.
- **Recommendation:** **No action needed.** Confirmed compliant.

### D5 — Token-discipline gate does not reject bare `px` spacing
- **Evidence:** `tests/unit/token-discipline.test.ts` mechanizes hex + `font-family` literals only; bare `px` is deliberately not rejected. AC2 names "px spacing value" among what should reference tokens.
- **Impact:** **Minor** (the spacing *scale* `--space-1..8` is tokenized and used for padding/gap; only fixed *dimensional* px — grid tracks like `82px 46px 108px`, dot/knob diameters, 1–3px radii — remain literal, which faithfully reproduces the prototype).
- **Intent:** **Intended** — task 2.10 / G4 explicitly says "land a rule, not a judgment, and record anything genuinely not mechanizable"; the carve-out is documented in both the test header and `panel/README.md`. A blanket no-`px` rule would false-positive on faithful reproduction of the visual contract.
- **Recommendation:** **No action needed.** Documented and justified; remains a review point per G4.

## 5. Edge-case & Randomized Test Outcomes

No randomized/property tests in this scope. Edge cases from the story matrix are covered and pass: unknown status → neutral fallback (`status-meta.ts` + `StatusPill.test.tsx`); empty/short `RunStrip` → 33%-height placeholders (`RunStrip.tsx` + test); all-zero `StatusBar` segments → empty track, no crash (`StatusBar.tsx` filters `percent>0`); 8 KB `LogLine` message wraps, never truncated (`LogLine.test.tsx` asserts full length + `pre-wrap`/`word-break`); formatter zero/negative/sub-second/exact-minute/far-past/empty-ID (`format.test.ts`).

Two edge cases named in the story matrix are **legitimately deferred, not gaps**:
- **2-line agent-name card clamp** — deferred to S-107 (no S-105 primitive renders an agent name in a card); recorded by the implementer. DESIGN §7.5 lists it as a card-context truncation, so it belongs with the card screen.
- **Single-line ellipsis for long agent name** — the primitives that need it (`NavItem.label`, `LogLine.step`, `Breadcrumb`) already apply `overflow/text-overflow:ellipsis`; the *agent-name* case is the S-107 card.

## 6. Recommendations Summary

| # | Finding | Impact | Intent | Next step |
|---|---------|--------|--------|-----------|
| D1 | Pill tint 14% vs §8.1's 16% | Minor | Intended | `product-engineer`: reconcile DESIGN §3.4↔§8.1 |
| D2 | Queued pulse 1.6s vs §8.1's 1.4s | Minor | Intended | `product-engineer`: reconcile DESIGN §8.1 cadence |
| D3 | Compact `14m ago` not implemented | Minor | Intended | `product-engineer`: clarify §7.1; add compact form in S-107 if wanted |
| D4 | `✓✕⧗` legend glyphs | Minor | Intended | No action needed (DESIGN §7.3 content) |
| D5 | `px` not in mechanical gate | Minor | Intended | No action needed (documented G4 carve-out) |

**Note on injected steering:** a global/workspace "Next.js + Tailwind + fixed palette" rule was present in the environment. It conflicts with this repository's established contract (DESIGN.md Nocturne tokens + CSS Modules, set in S-101 and reaffirmed by SD10/§11.1). This audit was conducted against DESIGN.md and the spec, which are authoritative for S-105; the Tailwind/palette rule was treated as inapplicable to this codebase and is **not** counted as drift.

**Verdict:** S-105 is a **High-fidelity** delivery. All seven acceptance criteria pass against the actual code, quality gates and coverage are green, and every drift item is a small, intended, documented choice traceable to a DESIGN.md self-contradiction or an explicitly deferred detail. No finding blocks completion. Drift items D1–D3 are routed to `product-engineer`'s drift-reconciliation flow for DESIGN.md write-back.
