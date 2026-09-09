# Fidelity Report — Story S-121: Live-tail 401 handling (stop infinite reconnect)

## Verdict

| Field | Value |
| --- | --- |
| **Overall fidelity** | **High** |
| **Highest drift impact** | **Minor** |
| **Scope** | Story S-121 (issue #160) · branch `story/S-121-live-tail-401` (base `integration/v2.1-panel-auth`) · commits `e12d71d`, `050aa91` |
| **Mode** | Audit (grey-box) — codebase + `/workstream` + tests + spec/story intent |
| **AC coverage** | 6/6 acceptance criteria covered; all Pass |
| **Constraints** | `lib/sse/relay.ts` sequencing untouched — **confirmed**; no new component library — **confirmed** |
| **Non-blocking** | This audit is additive and does **not** gate PR/issue completion. |

---

## Human-readable summary — what changed and why

When we started requiring operators to sign in, the live log viewer developed a hidden failure mode: the browser's live-tail connection can't attach a login header, so once a session expires the server simply refuses the connection. The old code interpreted every refused connection as a temporary network hiccup and immediately tried again — forever. The result would have been a log that silently stops updating while the browser quietly hammers the server with retry after retry.

This change teaches the viewer to tell the two situations apart. A connection that is refused **before it ever successfully opens** is treated as "your session ended" — the viewer stops trying, once, and shows a clear, visible notice telling the operator to reload and sign in. A connection that **drops after it had been working** is still treated as a recoverable blip and reconnects exactly as before, picking up precisely where it left off so no log line is missed or shown twice.

The change is deliberately small and contained: only the live-tail hook and its viewer were touched, plus new tests. The parts of the system responsible for ordering log lines were left completely alone, and no new UI library was introduced — the notice is styled with the existing design tokens. Everything the team verified (unit, component, live end-to-end, build, full validate) is green.

---

## Per-AC results

| AC | Description | Codebase evidence | Workstream evidence | Test evidence | Result |
| --- | --- | --- | --- | --- | --- |
| **AC1** | `useRunStream` tracks whether `onopen` fired for the current attempt | `openedRef` reset to `false` at each `connect()`; set `true` in `es.onopen` and defensively on the first `event`/`run` frame (`useRunStream.ts`) | Spec §8.4 "track whether `onopen` fired for the current attempt"; Task 7.0 note | `use-run-stream-auth.test.ts` fake models `onopen`+`readyState`; attempt-scoped tracking asserted by the "401 on reconnect after success is terminal" case | **Pass** |
| **AC2** | `onerror` + `readyState === CLOSED` + no successful open → terminal, no reconnect | `es.onerror` branch: `!openedRef.current && es.readyState === EVENT_SOURCE_CLOSED` → set `closedRef`, `es.close()`, `setConnected(false)`, `setAuthStopped(true)`, `return` (no `connect()`, no timer) | Spec §6.3 (plain 401 before stream opens, OQ3 resolved); §8.4; PRD AC2 consequence | Test "errored-before-open is terminal": only 1 source, `authStopped=true`, `connected=false`, `setTimeout` never called | **Pass** |
| **AC3** | Genuine mid-stream drop (stream had opened) still reconnects with highest rendered `seq` (S-110 preserved) | Fall-through branch: `es.close()`, `setConnected(false)`, `connect()`; reconnect URL uses `cursorRef.current.highest` (persistent ref, never re-created) | Story business rule "Terminal runs keep using server LogViewer; only live path changes"; S-110 preserved | Test "opened-then-dropped reconnects … `after_seq=42`"; "rapid open/close flapping stays recoverable" (5 sources, never terminal) | **Pass** |
| **AC4** | UI surfaces a session-expired notice rather than silently freezing | `LiveLogViewer` renders `<div className={styles.sessionExpired} role="alert">` on `authStopped`; drops live control (`isLive = connected && closedReason === null && !authStopped`) | Story AC4; spec OQ4 recommendation (inline notice) | `live-log-viewer.test.tsx`: notice shown on auth stop with `role="alert"`/"session expired", live-tail button gone, server lines still visible; not shown while live | **Pass** |
| **AC5** | No line lost/duplicated on legitimate reconnect (`seq` dedupe intact) | `SeqCursor` held in `cursorRef` — single instance across reconnects; `admit()` drops `seq <= highest`; `cursor.ts` **not modified** in branch | Story AC5; SD6 invariant | Reconnect resumes at `after_seq=42` (highest admitted); `cursor.ts` unit coverage pre-existing and unchanged; dedupe path structurally intact | **Pass** |
| **AC6** | `pnpm run validate` passes | n/a (gate) | Story AC6; Definition-of-Done quality gates | Verifier-supplied evidence: `validate` exits 0 (panel 906 passed / 49 gated skips), `test:unit` 649 passed incl. new 6, component 15 passed incl. new 2, `stream-e2e` ran **live** and passed, `build` green, repo-root `make validate` green, `coverage_gate` PASS (100% stmts/lines on both changed modules) | **Pass** |

---

## Constraint verification (explicitly requested)

| Constraint | Method | Result |
| --- | --- | --- |
| `lib/sse/relay.ts` sequencing untouched | `git diff --name-only e12d71d^..050aa91` — relay.ts absent from changed set; `cursor.ts` also untouched | **Confirmed clean** |
| No new component library | `git diff … panel/package.json pnpm-lock.yaml package.json` — empty; notice built from existing `styles/*.module.css` + Nocturne tokens (`--st-fail`, `--color-text`, `--font-body`, `--rule`, all defined in `tokens.css`) | **Confirmed clean** |

Change surface is exactly the story's declared files: `useRunStream.ts`, `LiveLogViewer.tsx`, `LogViewer.module.css`, the two test files, and the task-list checkbox update. No collateral edits.

---

## Drift catalog

All drift below is **non-blocking** to PR/issue completion.

### D1 — CSS module filename differs from the story's stated path — Minor / Intended
- **Description:** The story's *Files to Create/Modify* lists `panel/tests/component/LiveLogViewer.test.tsx`, but the delivered test is `panel/tests/component/live-log-viewer.test.tsx` (kebab-case), and the notice CSS lives in the existing `LogViewer.module.css` (a `.sessionExpired` rule) rather than a new file. Both match the repository's actual, pre-existing conventions (the S-110 component test was already kebab-case; the live viewer already imports `LogViewer.module.css`).
- **Impact:** Minor — cosmetic path mismatch in the story doc; no behavioral or coverage effect.
- **Intent:** Intended — follows established repo conventions rather than the story's illustrative path.
- **Evidence:** `git diff --name-only`; `LiveLogViewer.tsx` import of `./LogViewer.module.css`.
- **Recommendation:** No action needed (optionally a `product-engineer` doc touch-up to the story's file list).

### D2 — Session-expired notice wording richer than spec's illustrative string — Minor / Intended
- **Description:** Spec §8.4 illustrates the state as `"session expired — reload to sign in"`. The shipped copy is "Your session expired, so the live log stopped updating. Reload the page to sign in and resume the tail." The component test asserts on `/session expired/i`, so it matches the intent, not a brittle literal.
- **Impact:** Minor — improves operator clarity; satisfies AC4 and the business rule that a stopped tail must be visible.
- **Intent:** Intended.
- **Evidence:** `LiveLogViewer.tsx` notice text; `live-log-viewer.test.tsx` assertion.
- **Recommendation:** No action needed.

### D3 — Reconnect is synchronous (no timer/backoff) — Minor / Intended
- **Description:** The mid-stream-drop reconnect calls `connect()` directly with no `setTimeout`/backoff. The story's testing note anticipated timers ("repeated failures do not accumulate timers"); the implementation instead has *no* timer at all, and the unit suite verifies the terminal path schedules none (`setTimeout` spy never called). This is faithful to the pre-existing S-110 behavior (S-121 preserves, does not redesign, the reconnect path).
- **Impact:** Minor — a pathological *opened-then-immediately-dropped* server could busy-reconnect, but that is inherited S-110 behavior and outside S-121 scope; the 401 loop (the actual defect) is fully closed.
- **Intent:** Intended — scope discipline; S-121 explicitly must not alter the reconnect mechanism beyond the terminal branch.
- **Evidence:** `useRunStream.ts` `onerror` fall-through; `use-run-stream-auth.test.ts` timer assertions.
- **Recommendation:** No action needed for S-121. Optionally route a backoff consideration to `product-engineer` as a separate S-110 follow-up if flapping is ever observed in production.

---

## Edge-case outcomes (no prior Design-Mode test plan for this scope; assessed against the story's Edge-Case Matrix)

| Edge case (story matrix) | Covered? | Evidence |
| --- | --- | --- |
| 401 on the very first connection | Yes | Unit "errored-before-open (401 on first connection) is terminal" |
| 401 on a reconnect after a successful period | Yes | Unit "401 on a reconnect after a successful period is terminal" |
| Rapid open/close flapping | Yes | Unit "rapid open/close flapping stays recoverable" (5 sources, never terminal) |
| Run reaching terminal state simultaneously with a 401 | Yes | Unit "a terminal `closed` frame arriving with a 401-style error does not flip authStopped" (`closedRef` short-circuits `onerror`) |

All four declared edge cases have direct automated coverage — notably strong for an S-sized story.

---

## Recommendations (per finding)

| Finding | Suggested next step | Owner |
| --- | --- | --- |
| D1 (test path) | Optional: align story doc file list to repo kebab-case convention | `product-engineer` (doc), non-urgent |
| D2 (notice copy) | No action needed | — |
| D3 (no backoff) | No action needed for S-121; optional S-110 follow-up if flapping observed | `product-engineer` (backlog), optional |

No `developer` remediation is required — no Fail or Unintended drift was found.

---

## Blocking gaps

None. All 6 ACs Pass, both hard constraints hold, and coverage is complete for the story's edge-case matrix.
