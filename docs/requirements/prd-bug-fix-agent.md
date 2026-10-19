# PRD — Bug Fix Agent

> A scheduled, headless Claude Code agent that claims one `ready` bug from a
> GitHub repository, fixes it with a bounded, test-proven change, validates it, and
> opens a Draft PR for human review. Phase 5 of the Agent Fleet Control Plane.

## Changelog

| Version | Date       | Summary                                                                                                                                                                                                                       | Author           |
| ------- | ---------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------- |
| 1.0     | 2026-10-17 | Initial PRD. Produced from the `activity-grill` WHAT session recorded in `workstream/decisions-bug-fix-agent.md` (D-01–D-24). Third fleet agent: headless Claude Code inside a Python wrapper, claim → fix → gate → Draft PR. | product-engineer |
| 1.1     | 2026-10-18 | HOW-phase amendments (D-25–D-39): GitHub App has no Issues write (prerequisite); worst case corrected in §17 (model-directed code execution, trust anchor, credential spike); hooks and MCP disabled (FR-11); params resolved (FR-1); added FR-28–FR-31 (permission preflight, dependency install, task list, run deadline); FR-26 corrected (ceilings are dispositions, not failures); red-to-green evidence (FR-19); AC-17–AC-20; open questions replaced; vocabulary gains wrapper, run deadline, claim marker. | product-engineer |
| 1.2     | 2026-10-19 | Provider change (D-40–D-42): Anthropic API directly, no Bedrock; `MODEL_ID` default `claude-sonnet-5-5`; dedicated `ANTHROPIC_API_KEY` with a spend limit is the CLI's only secret (new FR-32, amended FR-9, FR-11, AC-5, §12, §15, §16, §17, §18 Q6, diagram, vocabulary). | product-engineer |
| 1.3     | 2026-10-19 | Verifier Design Mode findings F-1–F-5, approved by the user (D-44–D-48): FR-24 stale rule covers any terminal run without a PR and skips on read errors; FR-28 and AC-17 check the token's granted write permissions. | product-engineer |

---

## 1. Executive Summary

The fleet has two agents that act on a repository: `dependency-update` and `security-analyst`. Neither works on the bugs a human has already reported and refined. This PRD adds `bug-fix`: on a schedule, it picks the oldest **ready bug**, **claims** it, fixes it with a bounded change proven by a regression test, re-runs the repository's gates itself, and opens a Draft PR. A human reviews and merges. It reuses the existing scheduler and reporting contract; the new surface is the agent, its container, and the GitHub claim protocol (D-01, D-03).

## 2. Feature Overview

`bug-fix` is a fleet agent on AgentCore (Container runtime, Python), registered in `agents` with a params schema, invocable from the panel and from a schedule (D-01, D-03). Inside the container a Python **wrapper** owns every credential and every GitHub mutation; a headless Claude Code (`claude -p`, Sonnet) subprocess does only the part that needs a model: reproduce the bug, write the regression test, make the fix (D-05, D-11, D-04).

```mermaid
flowchart TD
    A[Run starts: repo, optional issue] --> B[Stale-claim sweep]
    B --> C{Pick ready bug}
    C -- none --> N1[succeeded / no_findings]
    C -- explicit issue not ready bug --> N2[succeeded / not_applicable]
    C -- picked --> D{Repo gates present?<br/>developer.md + 4 gate scripts}
    D -- no --> N2
    D -- yes --> E[Claim: assign + in-progress + comment]
    E --> F[Wrapper clones, branches issue/N-slug]
    F --> G[claude -p: reproduce, test, fix<br/>no tokens, no push, no gh]
    G --> H{Wrapper checks:<br/>caps, forbidden paths,<br/>4 gates, red-to-green}
    H -- fail or budget hit --> I[Disposition: comment + needs-refinement<br/>succeeded / needs_review]
    H -- pass --> J[Wrapper commits, pushes, opens Draft PR<br/>succeeded / fixed]
    G -. crash, timeout .-> K[failed + error_code]
```

## 3. Goals & Objectives

1. **Turn refined bugs into reviewable PRs without the operator driving.** A ready bug in an enabled repo reaches a Draft PR on the next schedule tick with no human action between (D-01, D-07).
2. **Keep every change small, specific, and proven.** No PR exists without a regression test that fails on the base code and passes with the fix, all four blocking gates green, and a diff inside the caps (D-09, D-14, D-15).
3. **Be safe unattended.** A prompt-injected issue can produce at worst a bad Draft PR a human reviews: the model holds no credentials and has no push path (D-11).
4. **Never stall the queue.** A bug the agent cannot fix leaves the queue with a stated reason; a dead claim is recovered automatically (D-08, D-16).
5. **Reuse, not rebuild.** No new scheduler, no new outcome values, no new trigger type (D-01, D-20).

## 4. Affected Repositories

| Repo                        | Role / Impact                                                                                                                                                                                                       |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `llipe/dev-tasks-agent-fleet` | **Primary.** New `agents/bug-fix/` (AgentCore project, Python wrapper, image with Node + Python + Claude Code CLI), `agents` seed row and params schema, panel `invoke-runtime` IAM policy entry, runbook, tests, roadmap. |
| Target repos (fleet-managed) | **Consumers.** Must have dev-tasks installed (`.claude/agents/developer.md`) and expose the four gates (D-06, D-19). No change is made to them except through the agent's Draft PRs and issue updates.                |
| `llipe/dev-tasks`           | **Reference only.** Source of the `developer` definition, `github-ops` label and branch conventions the agent follows. No change.                                                                                  |

## 5. Target Users

- **Primary: the operator** (the repo owner running the fleet). Defines a schedule per repo, reviews Draft PRs, re-labels `needs-refinement` bugs, clears the G5 block.
- **Secondary: bug reporters and reviewers** who see the claim comment, the disposition comment, and the PR.

## 6. User Stories

1. As the operator, I want a schedule on a repo to fix its oldest ready bug, so that refined bugs turn into PRs while I do other work.
2. As the operator, I want to name a specific issue when I invoke the agent, so that I can steer which ready bug is fixed next.
3. As the operator, I want the agent to assign me, mark the issue `in-progress`, and comment with the run link, so that I and my team can see the bug is taken and by which run.
4. As a reviewer, I want each PR to carry a regression test that failed before the fix, so that I can trust the fix addresses the reported bug.
5. As a reviewer, I want a per-file rationale and the gate results in the PR body, so that I can review a 10-file change without reverse-engineering intent.
6. As the operator, I want a bug the agent cannot fix to leave the queue with a reason, so that the schedule keeps working on other bugs.
7. As the operator, I want dead claims recovered automatically, so that a crashed run never leaves an issue stuck `in-progress`.
8. As the operator, I want failures I must act on to be separate from bugs that were simply too hard, so that the circuit breaker does not pause my schedule because of hard bugs.

## 7. Functional Requirements

### 7.1 Invocation and selection

- **FR-1.** The agent SHALL accept params `issue_number` (optional), `assignee` (optional login; default from the `OPERATOR_GITHUB_LOGIN` runtime variable; neither set → `INVALID_PARAMS`), and the per-run caps and budgets `max_code_files`, `max_code_lines`, `max_turns`, `plan_max_turns`, `cli_timeout_seconds` (specification §5.1); the repository comes from the invocation payload. It SHALL be registered in `agents` with a JSON Schema for these params so the panel form and schedule validation work unchanged (D-01, D-03).
- **FR-2.** With no `issue_number`, the agent SHALL select the oldest open issue by `created_at` that carries both `type: bug` and `status: ready` and has no open linked PR (D-10).
- **FR-3.** With an `issue_number`, the agent SHALL work on that issue only if it is open and carries both labels; otherwise the run ends `succeeded` / `not_applicable` with a run_event giving the reason. An explicit number never bypasses `status: ready` (D-10).
- **FR-4.** With no ready bug, the run ends `succeeded` / `no_findings` (D-20).
- **FR-5.** Before claiming, the agent SHALL verify the repository gate (FR-6). A failed gate ends `succeeded` / `not_applicable` naming the missing item and does not touch the issue (D-06, D-19).
- **FR-6.** A repository is applicable only if it contains `.claude/agents/developer.md` and exposes the four blocking gates `test`, `lint`, `format:check` (JS/TS) or `format-check` (Python), and `typecheck`, as `package.json` scripts (JS/TS, pnpm or npm) or `Makefile` targets (Python). There is no fallback definition (D-06, D-18, D-19).

### 7.2 Claim

- **FR-7.** The claim SHALL consist of: assigning the `assignee` login; replacing `status: ready` with `status: in-progress`; posting a claim comment with the run ID and a panel link. The comment SHALL carry a machine-parsable marker identifying the agent and the run ID, posted by the GitHub App identity (D-07, D-16, D-23).
- **FR-8.** v1 SHALL NOT depend on assigning the GitHub App bot (D-07).

### 7.3 Fix loop and confinement

- **FR-9.** The wrapper SHALL perform clone, branch (`issue/<N>-<slug>`), commit, push, PR creation, and every issue mutation. The Claude Code subprocess SHALL run with no GitHub token, no Supabase key, and no AWS credentials in its environment — its only secret is the dedicated Anthropic API key (FR-32) — with `git push` and `gh` denied, permitted only to edit files in the checkout and run the repository's gate and test commands (D-11, D-12).
- **FR-10.** The issue title and body SHALL be passed to the model as quoted, untrusted data (D-11).
- **FR-11.** The subprocess SHALL load the target repository's `CLAUDE.md` and `developer` definition, with the repository's hooks and MCP servers disabled (enforced by CLI flags and a managed-settings file in the image), on the Anthropic API model given by `MODEL_ID` (default `claude-sonnet-5-5`) (D-05, D-29, D-40).
- **FR-12.** The wrapper SHALL bound the CLI with `--max-turns` (default 40) and a wall-clock kill (default 30 minutes), and the whole run with a 60-minute lifetime. All three are params. Reaching any ceiling takes the disposition path with the reason (D-22).

### 7.4 Change limits

- **FR-13.** After the CLI exits and before pushing, the wrapper SHALL reject the change if it exceeds **10 code files** or **400 changed code lines**. Docs/text files (`*.md`, `*.txt`, `*.rst`) and test files are excluded from both counts (D-09).
- **FR-14.** The wrapper SHALL reject any change that edits a lockfile, a CI workflow, or anything under `.claude/` (D-09).
- **FR-15.** The change SHALL include at least one added or changed test (D-09).
- **FR-16.** The PR body SHALL contain a rationale per changed file tying it to the bug. This is prompt-level; the wrapper checks only that each changed file is listed (D-09).

### 7.5 Validation

- **FR-17.** The wrapper SHALL itself run `test`, `lint`, `format:check`/`format-check`, and `typecheck` on the final tree and treat any failure as a failed validation. It SHALL NOT rely on the model's report (D-14).
- **FR-18.** The wrapper SHALL run `audit` and record the result in the PR body. An `audit` already failing on the base commit SHALL NOT block the PR (D-14).
- **FR-19.** **Red-to-green.** The wrapper SHALL revert the non-test changes, run the added/changed tests on the base code, and require at least one failure; then restore the fix and require them to pass. Tests that pass on the base code fail validation (D-15). Red means a non-zero exit with at least one failure line; the first 40 lines of the failing output go in the PR body so a reviewer can tell an assertion failure from an import error (D-34).

### 7.6 Pull request

- **FR-20.** On success the wrapper SHALL open a **Draft** PR against the default branch from `issue/<N>-<slug>`, with Conventional Commit messages, the body supplied via `--body-file`, a link to the issue, the per-file rationale (FR-16), the gate results (FR-17/18), the red-to-green evidence (FR-19), `verifier_audit: not-run(no-delegation)`, and `coverage_gate: SKIPPED(no-delegation)`. The PR SHALL stay Draft. The agent SHALL NOT merge (D-12, D-13).
- **FR-21.** The PR SHALL be recorded as a `pull_request` run artifact so the scheduler's G5 backoff applies (D-21).

### 7.7 Disposition and recovery

- **FR-22.** When a claimed run ends without a PR for any reason in FR-12, FR-13–FR-15, FR-17, FR-19, or because the model gives up, the wrapper SHALL post a diagnosis comment (what was tried, why it stopped, the diffstat when a cap was hit), replace `status: in-progress` with `status: needs-refinement`, and keep the assignee. It SHALL NOT retry automatically (D-08).
- **FR-23.** The wrapper's `finally` path and the existing signal backstop SHALL apply the disposition for every failure it can observe (D-08, D-16).
- **FR-24.** **Stale-claim sweep.** At the start of every run the agent SHALL find `status: in-progress` issues carrying its own claim marker (FR-7) whose run is not the current run, is terminal in Supabase (`succeeded`, `failed`, `timed_out`, `failed_to_start`, `canceled`), and has no PR artifact, and apply the disposition to each. It SHALL NOT touch issues without its marker, issues claimed by a human, or runs still non-terminal; a failed read skips the issue rather than disposing it (D-16, D-47, D-48).

### 7.8 Reporting and outcomes

- **FR-25.** The agent SHALL report through the existing reporter: steps for sweep, select, claim, checkout, fix, validate, red-to-green, open PR; `run_events` at each; heartbeat and signal backstop as in the sibling agents (D-03).
- **FR-26.** Outcomes SHALL use existing values only: PR opened → `succeeded`/`fixed`; no ready bug → `succeeded`/`no_findings`; repository or issue gate not met → `succeeded`/`not_applicable`; claimed, no PR → `succeeded`/`needs_review`; credentials, permission preflight, clone, GitHub API, push or PR errors, a CLI that cannot start or exits abnormally for a reason other than a limit, unparseable CLI output, wrapper error → `failed` with an `error_code`. Reaching a turn, wall-clock, or run-deadline ceiling is a disposition (`needs_review`), not a failure (specification §8.8). Only `failed` counts toward the scheduler's G3. The run summary and the issue comment SHALL state the reason for every `needs_review` (D-20).
- **FR-27.** `runs.metrics` SHALL record turns, token usage, wall-clock, files and lines changed, per-gate results, the red-to-green result, and the count of permission denials (D-22, D-39).

### 7.9 Preparation, task list, and run budget

- **FR-28.** At the start of every run the agent SHALL check its GitHub permissions: the installation token's granted permissions MUST include `issues: write`, `pull_requests: write`, and `contents: write`, and a read of the repository's issues and labels MUST succeed. Any failure ends the run `failed` / `GITHUB_PERMISSION_DENIED`, naming what is missing, before anything is claimed (D-25, D-46).
- **FR-29.** After the claim and before the CLI starts, the wrapper SHALL install the repository's dependencies (JS/TS: `pnpm install --frozen-lockfile` or `npm ci`; Python: a throwaway virtualenv via `make install` or `pip install -e '.[dev]'`), with a 300-second cap; lifecycle scripts run. A failed install takes the disposition path. A lockfile changed by the install is reverted before measuring (D-33).
- **FR-30.** The task list SHALL be the issue's own checklist copied into a scratch, uncommitted `workstream/tasks-issue-<N>-<slug>.md`. When the issue has none, a first CLI pass runs the repository's `plan` skill to produce it, within its own turn cap and the shared CLI wall-clock budget; a failed or empty pass takes the disposition path (`NO_TASK_LIST`) (D-31).
- **FR-31.** A run-level deadline (`start + lifetime − 180 s`) SHALL bound every step: each step's timeout is the lesser of its cap and the time remaining, and an exhausted budget before a step takes the disposition path (`RUN_BUDGET_EXHAUSTED`) (D-30).
- **FR-32.** The CLI SHALL authenticate to the Anthropic API with a dedicated key used by no other agent, held in Secrets Manager, fetched by the wrapper, registered with the scrubber, and passed only to the CLI process; the key's workspace carries a monthly spend limit (D-41, D-42).

## 8. Business Rules

- `status: ready` is the human refinement gate and is never bypassed (D-10).
- The label `status: in-progress` is the lock; it is applied only by a successful claim and removed only by the PR path or the disposition (D-07, D-08).
- Agents never merge to `main`; the PR stays Draft until a human acts (D-13; CLAUDE.md).
- One open agent PR per repo at a time, enforced by the scheduler's G5 (D-21).
- The agent follows `github-ops` conventions: `issue/<N>-<slug>` branches, labels, Conventional Commits (D-02, D-12).

## 9. Data Requirements

| Entity                   | Change                                                                                                                                                                                      |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `agents`                 | New row `bug-fix` with `default_params` and `params_schema` (seed, same `on conflict (slug) do update` shape as the siblings).                                                              |
| `runs`                   | Existing columns. `trigger_type` = `schedule` or `manual`. `params` snapshot includes caps and budgets. `metrics` as FR-27.                                                                 |
| `run_events`, `run_steps`| Existing; steps per FR-25.                                                                                                                                                                  |
| run artifacts            | `pull_request` on success (existing type).                                                                                                                                                 |
| GitHub issue             | Claim comment with marker (FR-7), disposition comment (FR-22), labels, assignee.                                                                                                           |
| Enums                    | **No migration.** `run_outcome` already has `fixed`, `needs_review`, `not_applicable`, `no_findings` (D-20).                                                                                |

Sensitivity: issue text is third-party input (FR-10). Installation tokens and the Supabase key stay in the wrapper (FR-9) and are scrubbed from logs by `scrubber.py`.

## 10. Non-Goals (Out of Scope)

- Assigning the GitHub App bot as assignee (D-07).
- Automatic retry of a failed fix (D-08).
- Any merge by the agent, or converting the PR out of Draft (D-13).
- Running `verifier` or `qa-engineer` inside the agent (D-13).
- Several bugs per run (D-10, D-21).
- A bundled `developer` definition for repos without dev-tasks (D-06).
- Stacks other than JS/TS and Python (D-18).
- **Fast-follows, recorded not built:** automatic detection of PR merge/close to release G5 (G5-b); an event-driven trigger on `status: ready` using the webhook trigger type; a per-repo stack extension (D-21, D-24).

## 11. Design Considerations

No UI work. The panel's invoke form and the `/schedules` cadence picker are schema-driven and work from the registered params schema (FR-1). **No `/DESIGN.md` impact.** The run summary text must carry the `needs_review` reason (FR-26) because the run list renders it green.

## 12. Technical Considerations

```mermaid
flowchart LR
    S[pg_cron scheduler<br/>or panel invoke] --> W
    subgraph R[AgentCore runtime: bug-fix container]
        W[Python wrapper<br/>credentials, GitHub, gates]
        C[claude -p subprocess<br/>model key only, edit and test only]
        W --> C
    end
    W --> GH[GitHub: issues, branches, PRs]
    W --> DB[(Supabase: runs, run_events)]
    C --> AN[Anthropic API: Sonnet]
```

- **Runtime:** AgentCore Container, ARM64, Python wrapper following the sibling modules (`agent_reporter`, `credentials`, `heartbeat`, `signal_backstop`, `scrubber`, `pull_request`). The image adds Node, pnpm/npm, Python toolchain, and the Claude Code CLI (D-03, D-05).
- **Model:** Anthropic API directly, not Bedrock (D-40). `MODEL_ID` env var, default `claude-sonnet-5-5`; the CLI authenticates with a dedicated `ANTHROPIC_API_KEY` (D-41, D-42). This differs from the sibling agents, which call Bedrock.
- **First fleet agent not built on Strands.** Confinement and cap enforcement therefore live in the wrapper (D-05).
- **Infrastructure scope.** A new AgentCore runtime, the panel's `invoke-runtime` IAM policy (it lists runtime and `runtime-endpoint/DEFAULT` ARNs explicitly; a new runtime is not covered without an entry — see issue #280), and the dedicated Anthropic API key in Secrets Manager with Secrets Manager read for the runtime role (no Bedrock access is needed, D-40). **Recommend an `infra-engineer` pass.**
- **Scheduler dependency.** Waves C–E of the scheduler are not yet merged to `integration/agent-scheduler` (roadmap). G1, G3, and G5 reach this agent only once they are (D-01).
- **GitHub App permissions.** The agent needs Issues read/write (assign, labels, comments) in addition to contents and pull-request write. The existing installation does **not** grant Issues write (the sibling PRDs list Contents, Pull requests, Metadata only); it must be added and accepted by the installation owner before Wave A deploys (D-25).
- **Runbook.** Per FR-49a, a runbook for deploy and live verification ships in the same PR as the deploy scripts or workflow changes.

## 13. Acceptance Criteria

- **AC-1 (selection).** Given three open bugs, one `status: ready` newest, one `status: ready` oldest, one `status: needs-refinement`, when the agent runs with no `issue_number`, then it claims the oldest ready one (D-10).
- **AC-2 (explicit gate).** Given an open `type: bug` issue without `status: ready`, when invoked with its number, then the run ends `succeeded`/`not_applicable` with a reason and the issue is unchanged (D-10).
- **AC-3 (claim).** After a claim, the issue shows the configured assignee, `status: in-progress` and no `status: ready`, and a comment with the run ID and marker (D-07).
- **AC-4 (not applicable).** A repo without `.claude/agents/developer.md`, or missing any of the four gates, ends `succeeded`/`not_applicable` naming the missing item, with no issue change (D-06, D-19).
- **AC-5 (confinement).** In a test run the CLI environment contains no GitHub token, Supabase key, or AWS credential variable, its only secret is `ANTHROPIC_API_KEY`, and an attempted `git push` or `gh` call is denied (D-11, D-41, D-42).
- **AC-6 (prompt injection).** Given an issue body instructing the model to exfiltrate secrets or push to another branch, no credential is reachable and no push other than the wrapper's occurs (D-11).
- **AC-7 (caps).** A change touching 11 code files, or 401 code lines, or any lockfile, CI workflow, or `.claude/` path, produces no PR and takes the disposition path with the diffstat; docs and tests do not count toward the caps (D-09).
- **AC-8 (regression test).** A change without a test, or whose tests pass on the base code, produces no PR and takes the disposition path (D-09, D-15).
- **AC-9 (gates).** A red `test`, `lint`, `format`, or `typecheck` blocks the PR; an `audit` that is red on the base commit does not (D-14).
- **AC-10 (PR).** A successful run opens a Draft PR on `issue/<N>-<slug>` with the FR-20 body and a `pull_request` artifact; the issue links to it; the PR stays Draft (D-12, D-13).
- **AC-11 (disposition).** For every no-PR path in FR-22 the issue ends `status: needs-refinement` with a diagnosis comment, the assignee kept, and the run `succeeded`/`needs_review` (D-08, D-20).
- **AC-12 (G3).** Three consecutive `needs_review` runs do not pause the schedule; three consecutive `failed` runs do (D-20).
- **AC-13 (sweep).** Given an `in-progress` issue with the agent's marker whose run is `timed_out` and has no PR, the next run applies the disposition to it first. An `in-progress` issue without the marker, and one whose run is still `running`, are untouched (D-16).
- **AC-14 (budget).** A run hitting 40 turns, 30 minutes of CLI time, or the 60-minute lifetime stops and takes the disposition path with the reason (D-22).
- **AC-15 (G5).** After a successful run, the schedule does not fire again for that repo until the operator clears it in the panel (D-21).
- **AC-17 (preflight).** With the App lacking Issues write (token permissions without `issues: write`), a run ends `failed` / `GITHUB_PERMISSION_DENIED` naming the permission, before assigning, labeling, or commenting on anything (D-25, D-46).
- **AC-18 (deadline).** A step that would start with no time left before the disposition reserve instead takes the disposition path with `RUN_BUDGET_EXHAUSTED`; startup refuses an inconsistent clock configuration (D-30).
- **AC-19 (repo config).** A target repo whose `.claude/settings.json` defines a hook or `.mcp.json` defines a server has neither run during a fix pass (D-29).
- **AC-20 (install).** A repo whose dependencies fail to install ends in the disposition `INSTALL_FAILED` with the issue left `needs-refinement`, and a lockfile changed by a successful install does not appear in the PR (D-33).
- **AC-16 (live).** One end-to-end run against a real fixture repo with a seeded ready bug reaches a Draft PR on the deployed runtime, and a seeded unfixable bug reaches the disposition path.

## 14. Success Metrics

Initial targets, to be calibrated after the first 5–10 real runs (the same horizon as the budgets in D-22):

- Share of claimed runs that end in a Draft PR.
- Share of Draft PRs a reviewer merges without rework.
- Median time from `status: ready` to Draft PR, which is bounded below by the schedule interval.
- Tokens and wall-clock per run, from `runs.metrics` (FR-27).
- Zero issues left `in-progress` with a terminal run for more than one tick (FR-24).
- Zero G3 pauses caused by `needs_review` outcomes (FR-26).

## 15. Assumptions

- The GitHub App installation can be given issue write on the managed repos.
- The Claude Code CLI can be run non-interactively against the Anthropic API with `ANTHROPIC_API_KEY`, using the model in `MODEL_ID`, from the AgentCore runtime's public network.
- Managed repos use pnpm/npm or a Makefile with canonical targets; repos that do not end `not_applicable` and are fixed by the operator over time.
- 10 files / 400 code lines / 40 turns / 30 minutes are reasonable starting values (D-09, D-22); they are estimates, not measured.
- The operator is the right default assignee (D-07).

## 16. Constraints & Dependencies

- Scheduler Waves C–E merged to `integration/agent-scheduler` for G1/G3/G5 (roadmap).
- GitHub App permissions (Section 12) and the panel `invoke-runtime` IAM entry (issue #280).
- A dedicated Anthropic API key for `bug-fix` with a monthly spend limit, stored in Secrets Manager (`agent-fleet/prod/ANTHROPIC_API_KEY`) (D-42).
- `docs/product-context.md` and `docs/technical-guidelines.md` are the foundation documents in this repository (old names; `dev-tasks migrate docs` is proposed).

## 17. Security & Compliance

- **Threat:** issue text is untrusted input to a model that writes tests the wrapper then runs, so model-directed arbitrary code executes in the container (D-11, D-27). Anything the runtime role can read (the Supabase service-role key, the GitHub App private key) is potentially reachable; whether AgentCore exposes role credentials to child processes is unverified. **v1 boundary:** the human `status: ready` gate plus repositories the operator owns where reporters are trusted. **Mitigations:** FR-9, FR-10, the wrapper-side validation of every output (FR-13–FR-19), disabled hooks and MCP (FR-11), and branch protection on `main`. **Blocking before any schedule is enabled:** the Wave A credential spike (specification §12.4). **Model key:** the CLI must hold the dedicated Anthropic API key, so model-directed code can read it; it is scoped to this agent with a hard monthly spend limit, so a leak costs capped spend until rotation and reaches neither GitHub nor Supabase (D-42). **Top fast-follow:** credential isolation (role split or a sandbox runtime). The earlier statement that the worst case is a bad Draft PR no longer holds.
- **Repository-controlled code runs in the container.** The target repo's `.claude/` hooks and its test, lint, and build scripts execute in the container. They see no secrets (FR-9) but are third-party code. Egress is the existing AgentCore network mode.
- **Forbidden paths** (FR-14) stop the agent from changing the guards it runs under.
- **Auditability:** claim and disposition comments, run events, and the PR body record what happened. The agent never merges (D-13).

## 18. Open Questions

The eight HOW questions of v1.0 are resolved in `workstream/specification-prd-bug-fix-agent.md` (D-25–D-39). Remaining, resolved by the Wave A canary rather than by more design:

1. Whether a child process of the deployed runtime can reach the role credentials, and whether Secrets Manager reads succeed from it (decides credential isolation timing).
2. Whether `plan` produces a usable task list under `-p`.
3. Whether the target repo's `CLAUDE.md` and `developer` definition load under the hook/MCP-disabling flags.
4. The CLI's max-turns result subtype and exit code.
5. Whether a silent 20-minute step survives the 900-second idle timeout with a 120-second heartbeat.
6. The spend-limit value for the dedicated key, set from the first runs' `runs.metrics` cost (D-42).

## Decisions

| ID   | Decision (short form)                                                                                            |
| ---- | ---------------------------------------------------------------------------------------------------------------- |
| D-01 | Reuse the fleet scheduler; no own scheduler.                                                                     |
| D-02 | Labels `type: bug`, `status: ready`, `status: in-progress`, `status: needs-refinement` already exist.            |
| D-03 | Follows the sibling AgentCore + Supabase reporting contract.                                                     |
| D-04 | Model is Sonnet via `MODEL_ID` (provider superseded by D-40).                                                    |
| D-05 | Headless Claude Code inside a Python wrapper (not Strands).                                                      |
| D-06 | No `developer.md` in the repo → `not_applicable`; no fallback.                                                   |
| D-07 | Claim = assign operator + `in-progress` label + claim comment.                                                   |
| D-08 | No PR → diagnosis comment + `needs-refinement`, no auto-retry.                                                   |
| D-09 | 10 code files / 400 code lines; regression test required; forbidden paths; per-file rationale.                  |
| D-10 | Oldest ready bug; explicit number never bypasses labels.                                                         |
| D-11 | Wrapper holds credentials; CLI has none and cannot push.                                                         |
| D-12 | Branch `issue/<N>-<slug>`, Draft PR by the wrapper.                                                              |
| D-13 | PR stays Draft; verifier and qa gates recorded as not run.                                                       |
| D-14 | Block on test, lint, format, typecheck; audit recorded only.                                                     |
| D-15 | Mandatory red-to-green on the regression test.                                                                   |
| D-16 | Stale-claim sweep at the start of each run, own-marker claims only.                                              |
| D-17 | Precedent: pnpm/npm detection; Python Makefile targets in sibling packages.                                      |
| D-18 | JS/TS and Python in v1.                                                                                          |
| D-19 | Canonical gate names as scripts (JS/TS) or Make targets (Python); missing → `not_applicable`.                    |
| D-20 | Outcome mapping; only `failed` counts toward G3.                                                                 |
| D-21 | Keep G5 as-is: one open agent PR per repo.                                                                       |
| D-22 | Budgets: 40 turns / 30 min CLI / 60 min run.                                                                     |
| D-23 | Name `bug-fix` and four glossary terms.                                                                          |
| D-24 | Non-goals and fast-follows (G5-b, webhook trigger).                                                              |
| D-25 | The App lacks Issues write; add it; preflight every run.                                                         |
| D-26 | Package layout and touchpoints mirror the siblings.                                                              |
| D-27 | Trust anchor + disclose; credential spike; isolation is the top fast-follow.                                     |
| D-28 | Claude Code CLI facts and the unverified items for the canary.                                                   |
| D-29 | Honor CLAUDE.md and agents only; hooks and MCP disabled.                                                         |
| D-30 | Run-level deadline; relaxed `step <= idle` for heartbeated steps.                                                |
| D-31 | `--agent developer`; task list from the issue or the `plan` pass.                                                |
| D-32 | Code-file classification and line counting.                                                                      |
| D-33 | Install dependencies before the CLI.                                                                             |
| D-34 | Red = any failing exit, with evidence in the PR body.                                                            |
| D-35 | Default assignee from `OPERATOR_GITHUB_LOGIN`.                                                                   |
| D-36 | Claim marker plus App-bot author check.                                                                          |
| D-37 | Linked-PR detection by branch prefix and closing keywords.                                                       |
| D-38 | Test strategy with a fake CLI and a security-negative category.                                                  |
| D-39 | `stream-json`, one scrubbed event per turn.                                                                      |
| D-40 | Anthropic API directly, no Bedrock; `MODEL_ID` default `claude-sonnet-5-5`.                                      |
| D-41 | CLI auth by `ANTHROPIC_API_KEY`; no AWS credentials in the CLI env.                                              |
| D-42 | Dedicated key with a monthly spend limit, Secrets Manager, CLI-only.                                             |
| D-44 | Canary selector is a top-level payload key, gated by `ALLOW_CANARY=1`; not in `params_schema`.                  |
| D-45 | Unwrap the CLI's repeated `prompt` wrapper like the siblings (ADR-005).                                          |
| D-46 | Preflight checks the token's granted permissions (`issues`, `pull_requests`, `contents` write).                  |
| D-47 | Stale claim = any terminal run without a PR, issue still `in-progress`.                                          |
| D-48 | Sweep reads through a separate PostgREST client that raises; read errors skip.                                   |

## Vocabulary

| Term               | Status in glossary | Bounded context | Definition (proposals only)                                                                                                         | Forbidden synonyms (proposals only) |
| ------------------ | ------------------ | --------------- | ----------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------- |
| ready bug          | proposed           | bug-fix         | An open GitHub issue labeled `type: bug` and `status: ready`.                                                                        | none                                |
| claim              | proposed           | bug-fix         | The three-part act of taking an issue: assign the configured login, replace `status: ready` with `status: in-progress`, and post a marked claim comment. | lock, take, checkout                |
| disposition        | proposed           | bug-fix         | The issue-side outcome applied when a claimed run ends without a PR: a diagnosis comment and `status: needs-refinement`.             | triage                              |
| stale-claim sweep  | proposed           | bug-fix         | The start-of-run recovery that applies the disposition to claims whose run is terminal without a PR.                                 | none                                |
| wrapper            | proposed           | bug-fix         | The Python process in the container that owns every credential and GitHub mutation and measures the CLI's result; the CLI subprocess holds only the dedicated model API key. | orchestrator, harness               |
| run deadline       | proposed           | bug-fix         | The instant `start + lifetime − disposition reserve` after which no step starts; each step's timeout is the lesser of its cap and the time remaining. | none                                |
| claim marker       | proposed           | bug-fix         | The hidden `bug-fix-agent:v1 run=<id>` comment line, valid only when authored by the App's own bot account, that identifies an agent claim. | none                                |
