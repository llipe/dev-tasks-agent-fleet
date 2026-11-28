# Implementation Plan - Repository Knowledge Views, Wave A (contract, skill, template)

Source: `llipe/dev-tasks-agent-fleet` `workstream/user-stories-prd-repo-knowledge-views.md` (v1.1), S-216–S-218
Wave issue: none

> Note: The publication report (`llipe/dev-tasks-agent-fleet` `workstream/github-publication-prd-repo-knowledge-views.md`) has no `Wave issue` line. The planner will search for the wave issue at Phase 0. PRD, spec and decision log live in `llipe/dev-tasks-agent-fleet` (`docs/requirements/prd-repo-knowledge-views.md` v1.2, `workstream/specification-prd-repo-knowledge-views.md` v1.0, `workstream/decisions-repo-knowledge-views.md`). This is a single-package repository, so task lines carry no package bracket.

## Relevant Files

- `.claude/skills/repo-knowledge/SKILL.md` - New skill (Claude Code)
- `.github/skills/repo-knowledge/SKILL.md` - New skill (Copilot)
- `.kiro/skills/repo-knowledge/SKILL.md` - New skill (Kiro)
- `templates/repo-knowledge/field-guide-README.md` - Field-guide README template (section-to-source map, stamp)
- `templates/repo-knowledge/field-guide-update-prompt.md` - Paste-ready update prompt, 12-section default
- `templates/repo-knowledge/graphifyignore` - Default `.graphifyignore` (tests and fixtures excluded)
- `templates/workflows/graph.yml` - Graph refresh workflow template
- `docs/runbooks/graph-workflow.md` - Runbook for the workflow (FR-49a)
- `docs/runbooks/README.md` - Runbook index row
- `bundle-manifest.json` - Ship the skill, templates and workflow
- `test/integration/install-parity.test.ts` - Parity across the three platforms and templates
- `test/fixtures/graph-repo/**` - Small fixture repository for the workflow dry run
- `.github/workflows/<ci>.yml` - CI job that dry-runs the `graph.yml` steps on the fixture
- `.claude/agents/technical-writer.md`, `.github/agents/technical-writer.agent.md`, `.kiro/agents/technical-writer.md` - Ownership
- `AGENTS.md`, `AGENTS.md.template`, `CLAUDE.md`, `CLAUDE.md.template` - Registry entries
- `CHANGELOG.md` - Release note

## Tasks

- [ ] 1.0 Implement Story S-216 - https://github.com/llipe/dev-tasks/issues/364: Field-guide contract and skill
  - [ ] 1.1 Write failing install-parity expectations for `repo-knowledge` on `.claude/`, `.github/`, `.kiro/` and for the two field-guide templates (D-27)
  - [ ] 1.2 Author `.claude/skills/repo-knowledge/SKILL.md`. The field-guide contract has:
    - required `docs/field-guide/index.html`;
    - optional pages and assets;
    - `README.md` with source map, update prompt and stamp;
    - riel's page rules;
    - no `fetch`/XHR;
    - no reference outside `docs/field-guide/` (D-02, D-10, D-23)
  - [ ] 1.3 Add procedure "Create a field guide" ending in a draft PR (D-10, D-27)
  - [ ] 1.4 Add procedure "Refresh a field guide (full or targeted)" with the stamp step, ending in a draft PR (D-27)
  - [ ] 1.5 Add the mandatory pre-PR verification step to both procedures:
    - local serve + Playwright;
    - no console errors;
    - no sideways scroll at 390 px;
    - no `fetch`/XHR;
    - no out-of-folder reference (D-27)
  - [ ] 1.6 Write `templates/repo-knowledge/field-guide-README.md` and `field-guide-update-prompt.md` with the 12-section default set and sources (D-27)
  - [ ] 1.7 Mirror the skill to `.github/skills/` and `.kiro/skills/`, with the same procedure content and each platform's frontmatter
  - [ ] 1.8 Add the skill and the two templates to `bundle-manifest.json`
  - [ ] 1.9 Edge cases: install into a temp repository with no `docs/`; refresh over an existing `docs/field-guide/` does not overwrite unrelated files (procedure text plus integration test)
  - [ ] 1.10 Verify Acceptance Criterion: three identical `SKILL.md` copies exist (FR-22)
  - [ ] 1.11 Verify Acceptance Criterion: the contract text covers every FR-23 rule, including no `fetch` and no out-of-folder reference
  - [ ] 1.12 Verify Acceptance Criterion: templates carry the 12-section default (FR-24)
  - [ ] 1.13 Verify Acceptance Criterion: both procedures end in a draft PR (FR-25)
  - [ ] 1.14 Verify Acceptance Criterion: both procedures carry the verification step
  - [ ] 1.15 Verify Acceptance Criterion: manifest lists skill and templates; `validate` and install-parity pass (AC-10)
  - [ ] 1.16 AC-to-test mapping: AC1, AC6 → install-parity; AC2–AC5 → content checklist recorded in the PR body
  - [ ] 1.17 Run Tests: `pnpm run test:unit`, `pnpm run test:integration`, `pnpm run validate`

- [ ] 2.0 Implement Story S-217 - https://github.com/llipe/dev-tasks/issues/365: graph.yml template and runbook
  - [ ] 2.1 Write the failing fixture CI job first. It runs the workflow script steps on `test/fixtures/graph-repo/`. It asserts that `docs/graph/graph.json` exists with `graph.schema_version == 1`, and that a second run leaves `graph.json` unchanged (D-18)
  - [ ] 2.2 Author `templates/workflows/graph.yml` (D-09, D-20):
    - pinned `graphifyy[sql]==0.9.120`;
    - `graphify extract . --code-only --no-viz`, then `graphify cluster-only . --no-viz`;
    - `GRAPHIFY_BACKEND=none`, `GRAPHIFY_QUERY_LOG_DISABLE=1`
  - [ ] 2.3 Copy outputs to `docs/graph/graph.json` and `docs/graph/GRAPH_REPORT.md`. Compare only `graph.json` for the change check (spec §9)
  - [ ] 2.4 Open or update a single PR `chore(graph): refresh dependency graph` from `chore/graph-refresh` only when `graph.json` changed. Never push to the default branch (D-09)
  - [ ] 2.5 Triggers: weekly `schedule`, `workflow_dispatch`, `push` to the default branch with `paths-ignore: ['docs/**', '**/*.md']`. Permissions: `contents: write`, `pull-requests: write` (D-09)
  - [ ] 2.6 Write `templates/repo-knowledge/graphifyignore` with the D-18 test and fixture patterns. The workflow writes it only when absent (D-20)
  - [ ] 2.7 Write `docs/runbooks/graph-workflow.md` (raise the pin, edit `.graphifyignore`, graph over 15 MB, failed run) and add the index row. It ships in this PR (FR-49a, D-20)
  - [ ] 2.8 Add procedure "Install the graph workflow" to all three `SKILL.md` copies (D-12):
    - copy `graph.yml` and `.graphifyignore`;
    - add `graphify-out/` to `.gitignore`;
    - add the consumer runbook;
    - open a draft PR
  - [ ] 2.9 Add the workflow and the ignore template to `bundle-manifest.json`
  - [ ] 2.10 Edge cases: existing `.graphifyignore` preserved; existing open `chore/graph-refresh` PR updated, not duplicated; repository with zero code files; SQL files parsed (`[sql]` extra)
  - [ ] 2.11 Verify Acceptance Criterion: pinned install and code-only commands (FR-28)
  - [ ] 2.12 Verify Acceptance Criterion: outputs written; ignore file only when absent
  - [ ] 2.13 Verify Acceptance Criterion: single PR, only on change, never a default-branch push (FR-29, AC-11)
  - [ ] 2.14 Verify Acceptance Criterion: triggers as specified (FR-30)
  - [ ] 2.15 Verify Acceptance Criterion: runbook in the same PR (FR-31)
  - [ ] 2.16 Verify Acceptance Criterion: skill procedure present on all three platforms (FR-25)
  - [ ] 2.17 Verify Acceptance Criterion: manifest entries present; workflow lint passes
  - [ ] 2.18 Manual check: `workflow_dispatch` on a scratch repository opens one PR, and a second dispatch with no change opens none. Record the run links in the PR
  - [ ] 2.19 AC-to-test mapping: AC1–AC3 → fixture CI job; AC4 → YAML assertion; AC5–AC7 → review checklist + lint
  - [ ] 2.20 Run Tests: `pnpm run test`, workflow lint, `pnpm run validate`

- [ ] 3.0 Implement Story S-218 - https://github.com/llipe/dev-tasks/issues/366: technical-writer owns field guides
  - [ ] 3.1 Add field-guide creation and refresh as a `technical-writer` responsibility referencing `repo-knowledge`, on all three platform definitions (D-10)
  - [ ] 3.2 Add `repo-knowledge` (consumer `technical-writer`) to `AGENTS.md` and `AGENTS.md.template`. Mention it in the skills list of `CLAUDE.md` and `CLAUDE.md.template`
  - [ ] 3.3 Add a `CHANGELOG.md` entry
  - [ ] 3.4 Verify Acceptance Criterion: three agent definitions updated (FR-26)
  - [ ] 3.5 Verify Acceptance Criterion: registries list the skill (FR-22)
  - [ ] 3.6 Verify Acceptance Criterion: CHANGELOG entry present
  - [ ] 3.7 Verify Acceptance Criterion: `validate` passes, including registry consistency
  - [ ] 3.8 AC-to-test mapping: AC1–AC4 → `validate` + review checklist
  - [ ] 3.9 Run Tests: `pnpm run validate`

## Decisions Consumed

| ID   | Decision (short form)                                                                                          |
| ---- | -------------------------------------------------------------------------------------------------------------- |
| D-02 | riel's `docs/field-guide/` is the reference implementation                                                     |
| D-09 | `graph.yml`: code-only, PR-based, weekly/dispatch/push                                                         |
| D-10 | Field-guide contract + `repo-knowledge` skill in dev-tasks, owned by `technical-writer`                         |
| D-12 | `graph.yml` lives in `templates/workflows/`, installed by the skill                                           |
| D-18 | graphify 0.9.120 code-only output measured; test-free sizes                                                    |
| D-20 | Tests excluded via `.graphifyignore`; `graphifyy[sql]==0.9.120`; 15 MB cap                                     |
| D-23 | Guides cannot `fetch`; no out-of-folder references (panel CSP)                                                 |
| D-27 | Skill structure, assets, procedures, 12-section default, verification                                          |
