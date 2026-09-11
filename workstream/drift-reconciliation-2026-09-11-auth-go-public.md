# Drift Reconciliation Handoff — auth go-public close-out (2026-09-11)

> **STATUS: COMPLETED 2026-09-11** (branch `docs/drift-reconcile-auth-go-public`). All seven items
> below were written back: PRD v2.5 (D1), spec v1.7 (D2/OQ1/OQ2/OQ3), DESIGN.md v1.4 (DESIGN-1/2).
> **Update (same branch): OQ1 was subsequently marked RESOLVED** — the operator confirmed the
> deployed panel's Fly OIDC → AWS STS connection works (no static keys; live invocation via
> `credentialSource(): fly-oidc`), closing the live half of AC8. This file is retained as the audit
> record of the pass.

> **Owner:** `product-engineer` (via `activity-drift-reconciliation`). **Source:** issue #162 / S-123
> close-out (branch `issue/162-go-public-close-out`, PR #175) + the Road A/B reconciliation pass.
> **Nature:** decision-record write-backs to the **spec/PRD** documents. These are deliberately
> **out of scope** for the developer close-out PR (which touched only `technical-guidelines.md`,
> `product-context.md`, the runbook, `fly.toml`, and the gate scripts/tests). Nothing here blocks the
> #162 completion gate — per the implement rules, drift is handled *after* the mandatory audit gate,
> not before it.

## Why this file exists

The auth wave (S-116…S-123) reversed decision **D16** ("no user auth; privacy is the only boundary")
and resolved risk **R1**, and several open questions were settled by observation during the wave. The
per-story `technical-writer` passes deliberately did **not** rewrite the spec/PRD decision records
(they are `product-engineer` territory), so the spec §17 / PRD still describe the pre-auth world in
places. This is the consolidated list to reconcile.

## Items to write back

| # | Where | Current (stale) state | Correct state | Evidence |
|---|-------|-----------------------|---------------|----------|
| D1 | **PRD `prd-agent-fleet-panel-v2.md`** §8 D16, §10 Non-Goals, §17 R1, §18 | "Phase 2 ships with no user authentication (D16)"; R1 "No authentication in the first iteration"; mitigation = keep the Fly app private | **D16 reversed / R1 resolved.** The panel requires Supabase password login and is deployed public behind it. Mark D16 as reversed (point to `prd-panel-password-auth.md` + ADR-007) and R1 as Resolved. | tech-guidelines §5/§6/§13 (rows 1.29, 1.30), ADR-007, `panel/middleware.ts`, live gate PASS 2026-09-11 |
| D2 | **Spec `specification-prd-agent-fleet-panel-v2.md`** §7 SD7, §17 | SD7 "No user auth; the security boundary is the Fly app's privacy"; the "future deploy that adds a public service silently removes the boundary" warning | Superseded by the auth spec. SD7 should point to `specification-panel-password-auth.md`; the boundary is now login, mechanically gated. | same as D1 |
| OQ1 | **Spec** §17 / **PRD** Open Question #5 (Fly OIDC socket shape + normalized `sub` + `MaxSessionDuration`) | Open — "blocks AC #8" | **RESOLVED (2026-09-11)** — the deployed panel's Fly OIDC → AWS STS connection is confirmed working (no static keys; live invocation over `credentialSource(): fly-oidc`); socket shape / `sub` / `DurationSeconds ≤ MaxSessionDuration` matched the shipped provider contract, which fails loudly on a mismatch. Closes the live half of AC8. | operator-confirmed; `panel/lib/aws/credentials.ts`; runbook `panel-deployment.md` Impl Step 5 (probe retained for re-verification); §13 / §5 |
| OQ2 | **Spec** §17 / **PRD** §18 (panel→agent `prompt` wrapping) | Listed as open in the spec/PRD | **Settled 2026-09-06** (issue #89): panel sends bare inner JSON, accepted end-to-end. Write back as resolved. | `runbooks/issue-89-live-verification.md`; tech-guidelines row 1.20 |
| OQ3 | **Spec** §17 (SSE + auth sequencing / reconnect) | If still listed open in the v2 spec | **Settled by S-121**: the SSE gate returns a plain 401 before the stream opens; the client treats never-opened + CLOSED as terminal and stops reconnecting. | auth spec §6.3/§8.4; tech-guidelines row 1.28 |
| DESIGN-1 | **`DESIGN.md`** §5.1 | Time-range chips (7d/30d/all) specified but not built (S-107 scope decision) | Write back: "all" only; a client window misreports counts, a server window reintroduces the forbidden toggle refetch. | tech-guidelines row 1.18 |
| DESIGN-2 | **`DESIGN.md`** §8.2 | Outcome-tag set omits the `N/A` tag the run-history renders for `not_applicable` | Add the `N/A` outcome tag to the §8.2 set. | tech-guidelines row 1.19 |

## Not drift (recorded so it is not re-flagged)

- The `technical-guidelines.md` changelog rows and the runbook still *mention* `verify-fly-private.sh`
  and "private" as **history** — that is correct historical prose and MUST NOT be edited to pretend
  the panel was always public. The current-state body text (§5/§6/§13) is what was corrected.
- The `.next/` stray `" 2"`-suffixed duplicate files are a **local file-sync artifact**, not a repo
  defect (`.next/` is gitignored). No action.

## Follow-ups already tracked as their own issues (not this pass)

- **#172** — migrate off the legacy Supabase anon key to publishable API keys (S-124). The client
  anon key delivery is noted in the runbook; the migration itself is #172.
- **#156 / #158** — S-117 / S-119 tracking issues left OPEN despite their PRs (#165/#166) being
  merged. Close with a pointer comment (Road A stale-issue cleanup) — no code.
