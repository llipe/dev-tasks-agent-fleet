# Fidelity Report — Story S-118

## 1. Header / Verdict

- **Overall fidelity verdict:** **High**
- **Highest drift impact present:** **None** (one Minor *observation*, not a behavioral drift — see §4)
- **Scope reference:** Story **S-118** "Route-group restructure for an unshelled login route" · Issue **#157** · PR **#164** · branch `story/S-118-route-group` → base `integration/v2.1-panel-auth`
- **Mode:** Audit (grey-box fidelity) · **Non-blocking** on drift

> This story is a declared **pure mechanical restructure** — the acceptance bar is "no observable behavior changed." The audit confirms that bar was met: every URL resolves identically, moved page content is byte-identical (git R100), inline route-segment config is preserved and still honored by the build, and the SD2 ESLint guard was empirically re-proven to cover the relocated `app/(panel)/**` tree in both directions.

## 2. Human-Readable Summary (what changed and why)

The panel's page files (`app/page.tsx`, `app/agents/**`, `app/runs/**`, `app/dev/**`) were moved into a new folder named `app/(panel)/`. The parentheses make it a Next.js "route group," which is a purely organizational folder — it never appears in the address bar. Because of that, every page keeps the exact same web address it had before.

The reason for the move: the shared "app shell" (the sidebar and top bar) used to wrap *every* page from the top-level layout. A future login page (a later story) needs to appear *without* that shell. By grouping the logged-in pages under `(panel)/` and putting the shell in that group's own layout, the login page can later sit outside the group and render bare. Nothing a user sees today changes — same pages, same shell, same URLs.

To make this safe and easy to review, the change was kept strictly mechanical: the page files were moved without editing their contents (verified byte-for-byte), the top-level layout was trimmed to only the page skeleton, fonts, and styling, and only three test files had a folder name updated in one import line each. The developer also swept out ten stray duplicate files (`… 2.ts`) that macOS had created earlier — housekeeping unrelated to the feature. The production build, type check, and the relevant tests all pass, and the build's route listing shows every address unchanged with no `(panel)` segment anywhere.

## 3. Per-AC Result Table

| AC | Description | Codebase evidence | Workstream evidence | Test evidence | Result |
|----|-------------|-------------------|---------------------|---------------|--------|
| AC1 | `page.tsx`, `agents/**`, `runs/**`, `dev/**` relocated under `app/(panel)/`, content otherwise unchanged | `git diff --find-renames` reports **R100** (100% similarity → byte-identical) for all 10 moved files incl. co-located `page.module.css` ×3 and `dev/gallery/ToggleDemo.tsx`; `app/` now holds only `(panel)`, `api`, `layout.tsx` | Story impl-steps 1; task 3.x | typecheck PASS (imports resolve); `next build` PASS | **Pass** |
| AC2 | `(panel)/layout.tsx` renders `AppShell`; root `layout.tsx` renders only `<html>`/`<body>`, fonts, global styles | New `app/(panel)/layout.tsx` returns `<AppShell>{children}</AppShell>`; root `layout.tsx` diff shows clean removal of the `AppShell` import + wrapper, keeping `<html>`/`<head>` Inter links/metadata/`<body>` + `tokens.css`+`globals.css` imports only | Story impl-steps 2–3 | build PASS (shell renders in group) | **Pass** |
| AC3 | Every existing URL resolves exactly as before (`/`, `/agents/[slug]`, `/runs/[id]`, `/api/...`) | `next build` route table shows `/`, `/agents/[slug]`, `/agents/[slug]/invoke`, `/runs/[id]`, `/dev/*`, `/api/agents/[slug]/invoke`, `/api/runs/[id]/events/stream` — **no `(panel)` segment in any URL**; `api/` left in place | AC "URL-parity" | Independently reproduced `next build` route table (this audit); developer E2E 10/10 as URL-parity regression proof | **Pass** |
| AC4 | Inline route-segment config (`dynamic`/`revalidate`/`fetchCache`) preserved verbatim in each moved page | `grep` confirms all three exports present inline in every data page under `app/(panel)/`; preserved *verbatim by definition* since the files are R100 renames; build marks every moved route `ƒ (Dynamic)`, proving the inline config is honored, not silently dropped | §12 convention; Business Rule "config must remain inline" | build route table = all `ƒ` | **Pass** |
| AC5 | SD2 ESLint rule still applies to the moved tree (`app/**` glob + server-entrypoint exclusions still behave) | `eslint.config.mjs` scopes the rule to `app/**/*.tsx` with `ignores` on `app/**/{page,layout,route,…}.tsx`; **empirically probed** (this audit): a non-entrypoint client component placed under `app/(panel)/__sd2_probe__/` **fires** `no-restricted-imports` (SD2), and a `page.tsx` entrypoint under `app/(panel)/` correctly **does not** fire — `**` matches across the `(panel)` segment in both directions | AC "lint-scope" | `tests/unit/eslint-server-import.test.ts` PASS (2/2) | **Pass** |
| AC6 | Full existing test + E2E suite pass **unmodified** except import-path updates | Only 3 wiring tests changed, **2 lines each** (one doc comment + one `@/app/… → @/app/(panel)/…` import); no test logic touched | Story testing section | Reproduced: 4 target suites PASS (8/8); developer `pnpm run test` 823 passed / 44 Docker-gated skips + `test:e2e` 10/10 | **Pass** |
| AC7 | `pnpm run build` succeeds and `pnpm run validate` passes | — | — | Reproduced: `build` PASS, `typecheck` PASS; developer `validate` PASS (lint/format:check/typecheck/test/audit) + repo-root `make validate` PASS (Python 452 + JS) | **Pass** |

**Coverage: 7 / 7 ACs covered and Pass.**

## 4. Drift Catalog

No behavioral drift was found. One item is recorded as an **observation** for completeness (impact **None/Minor**, all Intended). *Drift is non-blocking to completion.*

| ID | Description | Impact | Intent | Evidence source(s) |
|----|-------------|--------|--------|--------------------|
| D1 | **Removal of 10 untracked `* 2.ts` macOS copy-collision artifacts** was performed on the branch but is *not* part of the S-118 commit (`8901ef2`) and is not enumerated in the story's ACs. It is a legitimate, disclosed branch-hygiene cleanup. Verified: `find` shows zero remaining artifacts and `git status` shows no untracked panel files. No product-code or behavioral effect. | None | Intended | Codebase (`find`, `git status`, `git log`) + prompt disclosure |
| D2 | **SD2 test fixture location vs. AC5 wording.** `eslint-server-import.test.ts` places its fixture under `components/__sd2_fixture__/`, so the *committed* test proves the rule fires via the `components/**` glob, not directly via `app/(panel)/**`. AC5 is nonetheless satisfied — the audit added a live probe under `app/(panel)/` confirming both the fire and the entrypoint-exclusion behavior — but there is no *committed automated* assertion pinning `app/(panel)/**` coverage specifically. | Minor | Intended | ESLint config + test file + this audit's empirical probe |

**Recommendation per item:**
- **D1** — `no action needed` (correct, disclosed hygiene).
- **D2** — Optional: `product-engineer`/`qa-engineer` may consider extending the SD2 test to add an `app/**`-scoped fixture case so the `app/(panel)/**` coverage is guarded by a committed test rather than by reasoning + one-off audit probe. Non-blocking; the hard `import "server-only"` build guard remains the real backstop regardless.

## 5. Edge-Case & Randomized Test Outcomes

No prior Design-Mode test plan exists for S-118 (the story's own testing section defers to the existing suite). Story-listed edge cases were checked against evidence:

- **Dev gallery still 404s in production** — `dev/*` routes moved intact under `(panel)/`, build lists them; production 404 behavior is inherited unchanged (files are R100). Not separately re-run; covered by "content byte-identical."
- **SSE route still streams** — `/api/runs/[id]/events/stream` left in place (not moved); present in build route table; developer E2E live-tail scenario passes.
- **`not-found` for unknown run id unchanged** — run-detail page is byte-identical; wiring test suite (incl. not-found path) passes.

## 6. Recommendations (next step per item)

1. **Merge is fidelity-clear.** All 7 ACs Pass; no behavioral drift. The restructure is faithful to the "pure mechanical" intent.
2. **D2 (optional, non-blocking):** route to `qa-engineer` to add a committed `app/**`-scoped SD2 fixture case, closing the small gap between AC5's wording ("applies to the moved tree") and the committed test's `components/**` fixture. — *suggested, not required.*
3. **No `developer` fix required** and **no `product-engineer` spec clarification required.**

---

### Audit method note (grey-box)

Evidence was collected directly from the branch, not merely trusted from the developer's report:
- `git diff --find-renames` (R100 confirmation), full diffs of the 2 modified + 1 new + 3 test files.
- Independent `pnpm run typecheck` (PASS) and `pnpm run build` (PASS, route-table inspected for URL parity + `ƒ` dynamic markers).
- Independent `vitest run` of the SD2 rule test + 3 wiring tests (8/8 PASS).
- **Two live ESLint probes** under `app/(panel)/` (created + linted + removed) to directly verify SD2 glob coverage in both the fire and exclusion directions — the one AC where the committed test gives only indirect evidence.
- `find` + `git status` to confirm the `* 2.ts` cleanup and a clean tree.

The full 823-test suite and 10-scenario E2E run were **not** re-executed in this audit (they require the Docker Supabase stack); the developer's PASS evidence for those is credible and consistent with the S-118-specific proofs reproduced here. This is disclosed rather than presented as independently re-verified.
