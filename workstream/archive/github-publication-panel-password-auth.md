# GitHub Publication Report: Panel Password Authentication

## Target Repository

- **Repo:** `llipe/dev-tasks-agent-fleet`
- **Date:** 2026-09-09
- **Source stories:** [`user-stories-panel-password-auth.md`](user-stories-panel-password-auth.md) (v1.0)
- **Milestone created:** `v2.1 — Panel authentication` (milestone #3)

## Created Issues

| Story ID | Story Title | Issue URL | Labels | Milestone | Assignee |
| -------- | ----------- | --------- | ------ | --------- | -------- |
| S-116 | Auth client foundation and pure policy modules | [#155](https://github.com/llipe/dev-tasks-agent-fleet/issues/155) | enhancement, priority:critical, size:M, story, scope:panel, security | v2.1 — Panel authentication | — |
| S-117 | Middleware auth gate (the chokepoint) | [#156](https://github.com/llipe/dev-tasks-agent-fleet/issues/156) | enhancement, priority:critical, size:M, story, scope:panel, security | v2.1 — Panel authentication | — |
| S-118 | Route-group restructure for login layout | [#157](https://github.com/llipe/dev-tasks-agent-fleet/issues/157) | enhancement, priority:high, size:S, story, scope:panel | v2.1 — Panel authentication | — |
| S-119 | Login screen and sign-in action | [#158](https://github.com/llipe/dev-tasks-agent-fleet/issues/158) | enhancement, priority:critical, size:M, story, scope:panel, security | v2.1 — Panel authentication | — |
| S-120 | Logout route and sidebar Log out affordance | [#159](https://github.com/llipe/dev-tasks-agent-fleet/issues/159) | enhancement, priority:high, size:S, story, scope:panel, security | v2.1 — Panel authentication | — |
| S-121 | Live-tail 401 handling (stop infinite reconnect) | [#160](https://github.com/llipe/dev-tasks-agent-fleet/issues/160) | enhancement, priority:high, size:S, story, scope:panel | v2.1 — Panel authentication | — |
| S-122 | Auth release gate replacing the privacy gate | [#161](https://github.com/llipe/dev-tasks-agent-fleet/issues/161) | enhancement, priority:critical, size:M, story, scope:infra, security | v2.1 — Panel authentication | — |
| S-123 | Go public (Phase B) | [#162](https://github.com/llipe/dev-tasks-agent-fleet/issues/162) | enhancement, priority:critical, size:S, story, scope:infra, security | v2.1 — Panel authentication | — |

All 8 stories published; none skipped.

## Phase Isolation (recorded on GitHub)

A `📌 Decision` comment recording the dependency order and the Phase A / Phase B split was posted to **#155** and **#162**:

- **Phase A** = #155 … #161 — the panel gains a working, verified auth gate while remaining unreachable from the internet.
- **Phase B** = #162 only — public exposure, isolated. **#162 MUST NOT be merged in the same PR as any Phase A story.**

## Notes

- **Execution method used:** `gh-cli` (GitHub MCP was not available in this runtime). All bodies were written to files and passed with `--body-file`, per the mandatory multi-line body rule — no shell interpolation was used.
- **Read-back verification performed** (mandatory step): every issue body was re-read via `gh issue view --json body`. All 8 issues show **13 line-start `## ` headings** and own-line `- [ ]` checklist items — confirmed not flattened.
- **Label convention deviation, deliberate:** the `github-ops` taxonomy specifies `type: enhancement` / `priority: critical` (with a space). This repository's established convention across the 16 existing story issues (#113–#128, S-101…S-115) is bare type labels (`enhancement`) and no-space qualifiers (`priority:critical`, `size:M`, `scope:panel`). Consistency with the existing corpus was prioritized over the doc's literal form, so all new issues match the repo. Flagged here rather than silently diverging.
- **New label created:** `security` (`#B60205`) — "Security-relevant change (auth, secrets, exposure boundary)". The repo had no security label; this feature reverses the panel's security posture (D16/SR2), so the six security-relevant stories carry it for searchability. Follows the repo's bare-label form rather than `type: security`.
- **New milestone created:** `v2.1 — Panel authentication`. The existing `v2.0 — Phase 2 panel` milestone has 0 open / 16 closed issues (effectively complete), and authentication is a distinct feature with its own PRD, so a new milestone keeps the tracking clean.
- **Assignees:** none set (single-operator repo; no assignee convention observed in existing issues).
- **Migration:** every issue documents the schema **migration opt-out** — auth state lives in Supabase's platform-managed `auth.*` schema. #162 additionally documents an infrastructure-apply confirmation gate for public exposure.
- **Assisted-by value for future PR creation / issue closure:** `Assisted-by: Kiro (kiro-cli chat)`. No PR was created and no issue was closed during this publication, so no attribution line was required yet.

## Manual Follow-up Needed

1. **Supabase project configuration** (operator, out-of-band, before #158 can be verified end-to-end and before #162): enable the Email provider, **disable public signups**, set the refresh-token inactivity timeout to 12h, and create the operator user.
2. **Spec OQ1** — confirm whether the Supabase project uses asymmetric signing keys (affects whether `getClaims()` is a local or network verification in middleware). Relevant to #156.
3. **Spec OQ2** — decide `NEXT_PUBLIC_SUPABASE_ANON_KEY` delivery: `fly.toml [env]` (recommended) vs `fly secrets`. Must be settled before #162.

## Source of Truth

GitHub is now the source of truth for execution tracking of this feature. Issues #155–#162 carry the acceptance criteria, AC-to-test mapping, and definition-of-done checklists; the local `workstream/` documents remain the design record.
