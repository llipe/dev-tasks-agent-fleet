# Fidelity Report — S-106 (App shell — sidebar, top bar, collapse persistence)

## 1. Header / Verdict

| | |
| --- | --- |
| **Overall fidelity** | **High** |
| **Highest drift impact** | **Minor** |
| **Scope** | Story S-106 · issue [#119](https://github.com/llipe/dev-tasks-agent-fleet/issues/119) · branch `story/S-106-app-shell` · draft PR #138 |
| **Mode** | Audit (grey-box) |
| **Sources cross-checked** | Codebase (`panel/**` on-branch) · `/workstream` artifacts (story v1.2, test-plan wave3, tasks 1.0/1.1–1.28) · test suite (34 S-106 tests, ran live) · PRD/spec intent (DESIGN.md v1.1 §3.5/§4.1/§6.4/§6.5/§9, story ACs) |
| **AC coverage** | 6 / 6 covered · **6 Pass, 0 Fail, 0 Drift on AC verdicts** |
| **Gate note** | Non-blocking. Drift is reported, not gated. qa-engineer `coverage_gate` already PASS; `make validate` green (Python 436, panel 331 passed / 19 Docker-gated skips). |

## 2. Human-readable summary (what changed and why)

S-106 builds the panel's outer frame: a left sidebar you can collapse, a thin top bar, and a scrolling
content area — the chrome that every later screen lives inside. It behaves as the story asked:

- **The sidebar remembers whether you collapsed it.** Your choice is saved in the browser and comes
  back after a reload. You can toggle it with the collapse button or the keyboard shortcut (`Cmd+\`
  on a Mac, `Ctrl+\` elsewhere), and the shortcut politely stays out of the way while you are typing
  in a text field.
- **Only "Agents" actually goes anywhere.** The four destinations that are not built yet (All runs,
  Repositories, Settings, System health) are shown but visibly switched off, with a screen-reader
  label that says "not available in this phase." They are not clickable dead links and they do not
  trap keyboard focus — the deferral is meant to be *seen*, not stumbled into.
- **It does not flicker or complain on load.** The trickiest part of this story was avoiding a
  "hydration mismatch" — a whole class of subtle bug where the server and the browser disagree about
  what to draw. The team added a genuine test instrument that actually reproduces the load sequence
  and would fail if that mismatch happened. It passes, and — importantly — it was confirmed to be
  able to fail, so it is a real safety net rather than a rubber stamp.
- **It matches the house style.** Colours, spacing, the active-item highlight, and the focus ring all
  come from the shared Nocturne design tokens rather than hand-picked values.

Two honest caveats, both already known and accepted by the plan: the "works at 1024px with no
sideways scroll" check (AC-106.6) can only be *proven* by a real browser test, which lands later in
S-114 — for now it rests on token-driven CSS and manual comparison. And a handful of story details
(the exact filenames, an extra top-bar slot, an `aria-describedby` note) are richer than the story
text literally spelled out. None of that changes behaviour; it is documented below as minor,
intended drift.

An environment steering rule asking for Tailwind, a fixed blue/amber palette, `src/app`, and Jest
was present during this audit. It contradicts this repository's authoritative, already-locked
contract (Nocturne dark tokens + CSS Modules per DESIGN.md §11.1, `panel/app`, Vitest — settled in
S-101/S-105). Consistent with the S-105 audit, that rule is treated as **inapplicable** to this
codebase and non-conformance to it is **not** counted as drift.

## 3. Per-AC results

| AC | Description | Codebase evidence | Workstream evidence | Test evidence | Result |
| --- | --- | --- | --- | --- | --- |
| **AC-106.1** | Shell dimensions: 212/52px sidebar, `width 0.14s ease`, 38px top bar, content `flex:1; overflow-y:auto`, `100dvh`, no outer scroll | `Sidebar.module.css` (`width:212px` / `.collapsed{width:52px}` / `transition:width 0.14s ease`), `TopBar.module.css` (`height:38px`), `AppShell.module.css` (`.shell{height:100dvh;overflow:hidden}` / `.content{flex:1;overflow-y:auto}`); values token-backed (`--color-sidebar-bg` 92%, `--color-shell-bg` 88%) per story Tech Notes | tasks 1.4/1.6; CT-12 (§4.1 dimensional contract) | `AppShell.test.tsx` structure asserts nav/topbar/content present; dimensional strings are CSS-layer (CT-12 is component-render + manual) | **Pass** |
| **AC-106.2** | Collapse persists in `localStorage`, survives reload; `Cmd+\` toggles | `sidebar-state.ts` (closed-vocabulary read/write, `SIDEBAR_STORAGE_KEY`), `AppShell.tsx` (mount-effect reconcile + persist-on-change + keydown handler), `shortcuts.ts` (`isSidebarToggleShortcut`, `isTypingTarget`) | tasks 1.2/1.7/1.16; CT-4, CT-5, EC-5, EC-6, EC-7, EC-12, EC-24, G3 | 9 `sidebar-state` unit + 11 `shortcuts` unit + AppShell "restores from seeded storage", "persists", "Cmd/Ctrl+\ but not while typing", double-toggle, throwing-getItem, corrupt-value, **G3 hydration** (2 cases, `recoverable` empty) — all pass live | **Pass** |
| **AC-106.3** | Agents only enabled; 4 deferred render disabled with accessible "not available in this phase" affordance | `DisabledNavItem.tsx` — plain `<span>`, `aria-disabled="true"`, `aria-label="{label} — Not available in this phase"`, `title`, hidden `aria-describedby` note; `Sidebar.tsx` renders Agents as `NavItem` (link) + 4 `DisabledNavItem` | story AC3 / PRD §10; EC-15 | AppShell "marks Agents as the only enabled destination" — asserts the 4 are **not** links and carry `aria-disabled=true` | **Pass** |
| **AC-106.4** | Nav items match §3.5: active state (12% accent tint + 2px accent left border) + hover tint | `NavItem.module.css` — `.navitem{padding:6px 9px;border-radius:7px;border-left:2px solid transparent}`, `.active{background:color-mix(in srgb,var(--color-accent) 12%,transparent);border-left-color:var(--color-accent)}`, `:hover{color-mix(...text 5%...)}` — exact §3.5 match | story AC4 / DESIGN §3.5 | AppShell "derives the active nav item from the current route" asserts `aria-current="page"`; visual tint is CSS-layer + manual | **Pass** |
| **AC-106.5** | Keyboard reaches every interactive element; focus visible per §6.4; sidebar is `<nav>` with accessible label | `Sidebar.tsx` `<nav aria-label="Primary">`; collapse `<button type="button">` with `aria-label`/`aria-pressed`; `NavItem` is a real `<Link>`; `DisabledNavItem` is a non-focusable `<span>`; `globals.css` `:focus-visible{outline:2px solid var(--color-accent);outline-offset:2px}` (§6.4 exact) | story AC5; CT-13 (a11y roles), EC-15 | AppShell "renders a labeled primary nav"; disabled-not-links assertion; keydown/typing-guard test | **Pass** |
| **AC-106.6** | Layout holds at 1024px min width, no horizontal scroll (§9) | `AppShell.module.css` `min-width:0` on the content column + fixed-width `flex:none` sidebar + token-driven grid — structurally sound for 1024px | story AC6; **G7 (jsdom cannot verify geometry; Playwright deferred to S-114)** | No automated geometry test (jsdom has no layout engine). Verified by CSS inspection + manual per plan | **Pass (partial evidence — see D4)** |

## 4. Drift catalog

All drift below is **Minor** and **Intended**. Drift is **non-blocking to completion** — it is
recorded for reconciliation, not as a gate.

| ID | Description | Impact | Intent | Evidence source | Non-blocking |
| --- | --- | --- | --- | --- | --- |
| **D1** | **File layout richer than the story's "Files to Create/Modify."** The story lists `components/Sidebar.tsx` + `components/TopBar.tsx`; delivery uses a `components/shell/` subtree with an added `AppShell.tsx` (owns collapse state) and a separate `DisabledNavItem.tsx`. This is a cleaner decomposition, not a scope change — every story-named responsibility is present. | Minor | Intended | Codebase (`components/shell/*`) vs story Files section | Yes |
| **D2** | **`TopBar` exposes an extra `actions` slot** beyond the story's "breadcrumb slot." Forward-looking (realtime indicator, later screens); presentational, renders nothing when unused. | Minor | Intended | `TopBar.tsx` `actions?` prop; comment cites future use | Yes |
| **D3** | **`DisabledNavItem` accessibility exceeds the literal AC.** Adds `title` + a hidden `aria-describedby` note on top of `aria-label` + `aria-disabled`. Over-delivers on "communicated as unavailable to assistive technology (not by color alone)" (EC-15). | Minor | Intended | `DisabledNavItem.tsx` | Yes |
| **D4** | **AC-106.6 (1024px / no horizontal scroll) has no automated evidence.** jsdom computes no geometry, so the claim rests on token-driven CSS + manual comparison until Playwright scenarios land in S-114. Pre-flagged by the test plan as **G7 (Low)** — a known, accepted wave-boundary gap, not a defect. | Minor | Intended | Test plan G7; absence of a geometry test; `playwright.config.ts` stub, no committed scenarios | Yes |
| **D5** | **Bare dimensional `px` in shell CSS** (e.g. `212px`, `52px`, `38px`, `15px`, `5px` mark dot) sit outside the `--space-*` scale and outside the token-discipline gate's coverage. This is the documented S-105 carve-out (grid tracks, control heights, small radii) — DESIGN §4.1/§3.5 fix these exact pixel values, so reproducing them faithfully is correct. Colour/font literals *are* gated and clean. | Minor | Intended | `*.module.css`; S-105 token-discipline carve-out (guidelines §12 / verifier D5) | Yes |

**No Unintended drift and no Undetermined drift were found.** No `Critical` or `Major` drift.

## 5. Edge-case & randomized outcomes (prior test plan exists for this scope)

| Scenario | Intent | Outcome |
| --- | --- | --- |
| CT-4 — unknown/malformed/empty/absent persisted preference → default | Boundary (untrusted storage) | **Pass** — `sidebar-state` covers `collapsed`/`expanded`/`kanban`/`true`/`{`/`""`/absent; all non-canonical → `false` |
| CT-5 — type mismatch does not reach the component | Boundary | **Pass** — closed two-literal vocabulary; a `"false"` string never reads as `true`; return type validated at the boundary, not `as`-cast |
| CT-12 — §4.1 dimensional contract (incl. content owns the scroll) | schema-compat | **Pass** — the load-bearing "content region, not `<body>`, owns `overflow-y:auto`" is honored in `AppShell.module.css` |
| CT-13 (AC-106.5 half) — labeled nav, role-queryable | schema-compat | **Pass** — `getByRole("navigation", {name:/primary/i})` succeeds |
| EC-5 — rapid double toggle | State | **Pass** — final visual state matches final persisted value (`expanded`) |
| EC-6 — shell state across navigation | State | **Covered by design** — collapse state lives in the persistent `AppShell` in `layout.tsx`, not remounted per route; single-page persistence + storage round-trip tested (full cross-route is a manual/E2E item) |
| EC-7 / G3 — hydration does not flash or warn | Timing | **Pass** — real `renderToString`→`hydrateRoot` instrument, `recoverable` asserted empty; server renders the fixed default and reconciles in a mount effect (never reads storage during render) |
| EC-12 — `localStorage` throws | Failure mode | **Pass** — throwing getter → default expanded, no crash (unit + AppShell) |
| EC-15 — disabled items unreachable by any input | Auth/perms | **Pass** — `<span>` not `<a>`: not focusable, not a link, `aria-disabled` announced |
| EC-24 — preference shape from a previous version | Versioning | **Pass** — any unrecognized value ignored in favor of default |
| G3 falsifiability | instrument integrity | **Confirmed** by qa-engineer (genuinely falsifiable); the standing `console.error` trap + `no-suppress-hydration` grep guard reinforce it |
| G7 — 1024px in jsdom | instrument limit | **Deferred (Low)** — needs a real layout engine; Playwright scenarios land S-114 (→ D4) |

No randomized/fuzz tests are defined for this scope; no failure-triage entries.

## 6. Recommendations

| Item | Suggested next step | Owner |
| --- | --- | --- |
| D1 / D2 / D3 | Optional PRD/story write-back so "Files to Create/Modify" and the top-bar/a11y affordances match the shipped decomposition. Bookkeeping only. | `product-engineer` (drift-reconciliation) — **no code action** |
| D4 (AC-106.6 / G7) | Track the 1024px no-horizontal-scroll assertion as an explicit S-114 Playwright scenario so the manual-only gap is closed with automated evidence. | `product-engineer` / S-114 planning — **no action needed in S-106** |
| D5 | None — documented, accepted carve-out. Keep dimensional `px` a review point, not a gate. | — |
| Steering conflict (Tailwind/palette/`src/app`/Jest) | Already handled as inapplicable per S-105 precedent; no repository change. If the injected rule is meant to apply to a *different* project, scope its `fileMatchPattern` away from this repo. | `product-engineer` — **no code action** |

---

*Audit is additive and non-blocking. It does not gate PR/issue completion and does not replace the
existing quality gates (`test`/`lint`/`format:check`/`typecheck`/`audit`). Drift findings route to
`product-engineer`'s `activity-drift-reconciliation` flow; `verifier` reports findings only and does
not edit code, spec, PRD, or the task list.*
