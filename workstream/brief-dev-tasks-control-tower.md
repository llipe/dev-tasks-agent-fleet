# Brief: the dev-tasks side of the Control Tower

For the `product-engineer` session in `llipe/dev-tasks`. This is input to a PRD there, not a PRD. It records what was decided in `llipe/dev-tasks-agent-fleet` and what is left for dev-tasks to decide.

## Changelog

| Version | Date       | Summary                                                               | Author                    |
| ------- | ---------- | --------------------------------------------------------------------- | ------------------------- |
| 1.0     | 2026-11-25 | Initial brief, written after `prd-control-tower` v1.1 was approved. | @llipe / product-engineer |

## What exists

- **PRD:** `llipe/dev-tasks-agent-fleet` → `docs/requirements/prd-control-tower.md` (v1.1, approved). It adds a `/tower` section to the Agent Fleet panel showing repository → PRD → wave → issue.
- **Decisions:** `workstream/decisions-control-tower.md` in that repository, D-01 to D-17. Cite them as `control-tower#D-NN`.
- **Split:** that PRD owns the panel and the ingestion contract. dev-tasks owns everything that sends (`control-tower#D-16`).

## What dev-tasks must deliver

| # | Deliverable | Source decision | Needed by |
| - | ----------- | --------------- | --------- |
| 1 | `dev-tasks tower login`: store the panel URL and a per-repository tower token on the machine, outside the repository, never committed. All worktrees of the repository share it. | `control-tower#D-11` | Panel Wave B |
| 2 | `dev-tasks tower sync`: build a full snapshot (PRDs, waves, issues, issues with no PRD) from `docs/roadmap.md`, PRD files, `workstream/` and `gh`, and push it. Runnable by hand on every platform. | `control-tower#D-05`, `D-06` | Panel Wave B |
| 3 | `dev-tasks tower emit <event>`: push one tower event. | `control-tower#D-06` | Panel Wave C |
| 4 | Agent instructions: at each lifecycle point where an agent already edits a status comment, it also runs `emit`. Same on Claude, Copilot and Kiro. A `sync` at the batch boundary. | `control-tower#D-06` | Panel Wave C |
| 5 | Claude Code hooks: deterministic, non-blocking triggers at specific events, and model and token capture at session and subagent end, attributed by branch name. | `control-tower#D-06`, `D-07` | Panel Wave C |
| 6 | Lanes registry reader: include `workstream/lanes/registry.md` (crew, lanes, status, "Waiting on the owner") in the snapshot when the repository uses parallel-lanes; report "unreadable" when it cannot be parsed. | `control-tower#D-10` | Panel Wave C |

Order agreed (`control-tower#D-16`): panel Wave A → deliverables 1–2 → panel Wave B → deliverables 3–5 → panel Wave C (deliverable 6 before it).

## Constraints already decided

- **Never block the workflow.** A failed, slow or unconfigured push is reported and skipped. No gate depends on it (`control-tower#D-06`).
- **Evidence only.** The CLI derives every status from artifacts and `gh`. It sends no manually set status (`control-tower#D-05`, `D-08`, `D-09`).
- **No self-reported tokens.** Token counts come from the session transcript through a hook, never from an agent's statement (`control-tower#D-07`).
- **Contract by version.** Every push states the ingestion contract version. The contract is defined in the agent-fleet specification; the dev-tasks PRD cites that version and does not redefine it (`control-tower#D-16`).
- **Works without parallel-lanes.** A repository with no lanes registry sends a snapshot without one (`control-tower#D-01`).
- **Vocabulary.** Wave stage (eight: Refine, Spec, Stories, Publish, Plan, Build, Audit, Ship) and issue step (eight: Plan, Test design, Build, Quality gates, Coverage gate, Fidelity audit, Merged, Shipped). A dev-tasks role or crew member is a "workflow agent" on the panel side (`control-tower#D-17`).

## Reuse from dev-tasks

- **`prd-factory-board` (parked).** Its evidence rules carry over: the eight wave stages and their evidence (FR-6), the story-to-wave link (FR-7), and "no manual override" (D-08). The command, page and `board.json` do not. The dev-tasks PRD should say whether factory-board is superseded or stays parked.
- **`prd-projects-tracking` (done).** PRD and wave tracking issues, sub-issues and marker-identified status comments are the structured source for the snapshot and name the lifecycle points for `emit`.

## Open for dev-tasks to decide

1. Which Claude Code hook events fire a push, and which lifecycle points emit which event names. The agent-fleet specification fixes the event kinds the panel accepts; dev-tasks maps its lifecycle to them.
2. Where the token is stored on the machine, and how a cloud or CI session receives it.
3. What `sync` does when `gh` is unavailable or unauthenticated: send a partial snapshot marked as such, or send nothing.
4. How two lanes pushing snapshots from different worktrees of the same repository are reconciled (open question OQ-3 in the agent-fleet PRD; needs an answer from both sides).
5. Whether `emit` retries or queues locally when the panel is unreachable.
6. How the issue is identified for a main-thread session that spans several stories; the panel accepts wave-level attribution.

## Not ready yet

The ingestion contract (payload shapes, event kinds, version number) does not exist until the agent-fleet specification for Wave A is approved. Start the dev-tasks PRD's WHAT phase now; do not start its specification before that contract is published.
