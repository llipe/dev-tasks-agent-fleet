# GitHub Publication Report: Agent Fleet Control Panel, Phase 2

## Target Repository

- Repo: `llipe/dev-tasks-agent-fleet`
- Date: 2026-09-02
- Source: [`user-stories-prd-agent-fleet-panel-v2.md`](user-stories-prd-agent-fleet-panel-v2.md) v1.0
- Milestone created: **v2.0 — Phase 2 panel** (milestone #2)

## Created Issues

| Story ID | Story Title | Issue URL | Labels | Milestone |
|---|---|---|---|---|
| S-101 | pnpm workspace and panel scaffold | [#114](https://github.com/llipe/dev-tasks-agent-fleet/issues/114) | story, enhancement, phase:control-plane, priority:critical, size:M, scope:infra | v2.0 |
| S-102 | Adopt Supabase CLI migrations | [#115](https://github.com/llipe/dev-tasks-agent-fleet/issues/115) | story, enhancement, phase:control-plane, priority:critical, size:M, scope:infra | v2.0 |
| S-103 | English-only SQL surface and seed fix | [#116](https://github.com/llipe/dev-tasks-agent-fleet/issues/116) | story, enhancement, documentation, phase:control-plane, priority:critical, size:S, scope:infra | v2.0 |
| S-104 | Server-side data layer and status parity | [#117](https://github.com/llipe/dev-tasks-agent-fleet/issues/117) | story, enhancement, phase:control-plane, priority:critical, size:M, scope:panel | v2.0 |
| S-105 | Design tokens and Nocturne primitives | [#118](https://github.com/llipe/dev-tasks-agent-fleet/issues/118) | story, enhancement, phase:control-plane, priority:critical, size:L, scope:panel | v2.0 |
| S-106 | App shell with collapsible sidebar | [#119](https://github.com/llipe/dev-tasks-agent-fleet/issues/119) | story, enhancement, phase:control-plane, priority:high, size:S, scope:panel | v2.0 |
| S-107 | Agents dashboard with density toggle | [#120](https://github.com/llipe/dev-tasks-agent-fleet/issues/120) | story, enhancement, phase:control-plane, priority:high, size:M, scope:panel | v2.0 |
| S-108 | Agent run history | [#121](https://github.com/llipe/dev-tasks-agent-fleet/issues/121) | story, enhancement, phase:control-plane, priority:high, size:M, scope:panel | v2.0 |
| S-109 | Run detail with bounded log viewer | [#122](https://github.com/llipe/dev-tasks-agent-fleet/issues/122) | story, enhancement, phase:control-plane, priority:high, size:L, scope:panel | v2.0 |
| S-110 | SSE relay and live log tail | [#123](https://github.com/llipe/dev-tasks-agent-fleet/issues/123) | story, enhancement, phase:control-plane, priority:high, size:M, scope:panel | v2.0 |
| S-111 | AWS credential provider | [#124](https://github.com/llipe/dev-tasks-agent-fleet/issues/124) | story, enhancement, phase:control-plane, priority:critical, size:M, scope:panel | v2.0 |
| S-112 | Invoke route and payload translation | [#125](https://github.com/llipe/dev-tasks-agent-fleet/issues/125) | story, enhancement, phase:control-plane, priority:critical, size:L, scope:panel | v2.0 |
| S-113 | Schema-driven invoke form | [#126](https://github.com/llipe/dev-tasks-agent-fleet/issues/126) | story, enhancement, phase:control-plane, priority:high, size:M, scope:panel | v2.0 |
| S-114 | Playwright E2E against the local stack | [#127](https://github.com/llipe/dev-tasks-agent-fleet/issues/127) | story, enhancement, phase:control-plane, priority:medium, size:M, scope:panel | v2.0 |
| S-115 | Fly deployment and OIDC probe | [#128](https://github.com/llipe/dev-tasks-agent-fleet/issues/128) | story, enhancement, phase:control-plane, priority:high, size:M, scope:infra | v2.0 |

No assignees were set (single-operator repository).

## Dependency Graph (as published)

```
#114 S-101 ─┬─> #117 S-104 ─┬─> #120 S-107
            │               ├─> #121 S-108
            ├─> #118 S-105 ─┼─> #119 S-106 ─> #122 S-109 ─> #123 S-110 ─┐
            └─> #124 S-111 ─┤                                            │
                            └─> #125 S-112 ─> #126 S-113 ────────────────┼─> #127 S-114 ─> #128 S-115
#115 S-102 ──> #116 S-103 ──────────────────────> (#125, #126)
```

Each issue's `**Dependencies:**` line carries the resolved issue numbers, so the graph is navigable from GitHub without this file.

## Notes

- **Stories skipped:** none. All 15 published.
- **Execution method used:** `gh-cli`. GitHub MCP was not available in this runtime; `github-ops` conventions were applied directly, which is recorded here as the required fallback note.
- **Body delivery:** every issue body was written via `--body-file` (never inline `--body`), then read back and verified to render with headings on their own lines, `- [ ]` checklists intact, and blank-line-separated sections.
- **Label taxonomy deviation, deliberate.** `.kiro/agents/github-ops.md` specifies a `type: <value>` / `scope: <value>` taxonomy with a space after the colon. This repository's ~113 existing issues use the no-space form (`priority:high`, `size:M`, `phase:control-plane`) and GitHub's default type labels (`bug`, `enhancement`, `documentation`). Introducing a second, space-separated taxonomy would fragment filtering across the existing history, so the established repository convention was followed and two new labels were created in that same style: `scope:panel` and `scope:infra`. Reconciling the two taxonomies repository-wide is a `github-ops` audit task, not a Phase 2 concern.
- **Milestone `v1`** holds 31 closed issues and no open ones; closing it requires user confirmation and was not performed.
- **Issue #89** (agent invocation payload contract) is **not** duplicated by these stories. It remains open and is closed by S-112 / [#125](https://github.com/llipe/dev-tasks-agent-fleet/issues/125), which carries its remaining scope and its four acceptance criteria.
- **Manual follow-up needed:**
  - #116 (S-103) and #115 (S-102) carry the only database migrations in the phase. Both apply steps require explicit user confirmation against the live project.
  - #124 (S-111) cannot close PRD AC8; only #128 (S-115) can, via a live Fly Machine probe.
  - #128 (S-115) requires one-time AWS and Fly infrastructure work (OIDC IdP registration, IAM role) outside the repository.
- **Assisted-by value for future PR creation / issue closure:** `Assisted-by: Kiro`.

## Source of Truth

GitHub is now the source of truth for Phase 2 execution status. The local `workstream/` documents are the design record; issue state and checklists are the execution record.
