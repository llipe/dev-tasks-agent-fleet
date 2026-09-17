# security-analyst Agent

Five-tool security scanner agent (semgrep, gitleaks, trivy, checkov, CodeQL) for the Agent Fleet
Control Plane. Runs as an AWS Bedrock AgentCore Container runtime.

> **Status (S-125-S-141, build complete):** all 17 stories of the agent build are done; the code
> path is fully wired for both modes. Applying the seed migration, redeploying, and running real
> repo invocations remain pending explicit user confirmation (see the S-141 paragraph below).
> Story-by-story: project scaffold, deploy, and reporting pipe (S-125), per-tool
> severity normalization (S-126), the normalized `Finding`/`Remediation` schema plus
> `fingerprint()` (S-127), the Semgrep scanner integration (S-128), the Gitleaks scanner
> integration + secret redaction (S-129), the Trivy scanner integration (`fs`/`config`/`image`
> three-mode dispatch, D24/req-54 `lockfile_managed` boundary) (S-130), the Checkov scanner
> integration (own IaC-file pre-flight skip detector, unconditional `structural` remediation)
> (S-131), the CodeQL scanner integration (JS/TS + Python-only language dispatch, two-phase
> `database create`/`database analyze` CLI call per language, merged findings when both
> languages are detected) (S-132), cross-tool deduplication (`dedupe()`,
> `_merge_overlapping_by_line()`, `MergedFinding` — conservative file+category+line-overlap
> merge across tools within one scan pass, distinct from `fingerprint()`'s across-scan
> tolerance) (S-133), the finding classifier (`classify()`, `_is_major_bump()`,
> `_is_semver()` — the D22 three-bucket `mechanical`/`manual`/`unscannable` model, the D24/
> req-54 `dependency-update` lockfile boundary, and requirement 27's major-version guard;
> retroactively added `Remediation.current_version`, populated only by
> `trivy_runner.py`'s `version_bump` branch, so the major-bump guard has a pre-fix version to
> compare against `target_version` — see `normalize.py`'s `Remediation` docstring) (S-134), and
> **`mode=audit_only` end-to-end** (S-135, `#228`): `main.py` now calls the new
> `scanners.run_scanners()` dispatcher (all five tools, sequential, `AllScannersFailedError` on
> total failure) inside a heartbeated `scan` step, then a `classify` step (`dedupe()` →
> `classify()` per merged finding), builds the `audit_report` artifact from the full, unfiltered
> finding set, and calls the new `determine_outcome()` (`_at_or_above_floor()` applies
> `min_severity` to the terminal status only, never to the artifact — PRD requirement 62/AC-12b)
> to reach `succeeded`/`no_findings`, `succeeded`/`needs_review`, or `failed`/`AUDIT_FINDINGS`.
> S-136 (`#229`) built the two deterministic fixers — `fixers/semgrep_autofix.py` (Semgrep
> native-patch application) and `fixers/trivy_bump.py` (Trivy version-bump application, plus a
> retroactive, additive `Remediation.package_name` field so the fixer can locate which manifest
> line to edit — see `normalize.py`'s `Remediation` docstring). S-137 (`#230`) built `rescan.py`'s
> `rescan_gate()` — the agent's defining trust mechanism (D23/D25): it compares a pre-fix and
> post-fix finding set by `fingerprint()` and only reports `clean=True` when every targeted
> finding is gone and no unexplained new finding appeared, checked only against a fixed,
> enumerated allow-list table (`_ALLOWED_NEW_FINDING_EXCEPTIONS`), never inferred (requirement
> 34). S-138 (`#231`) built `fix_agent.py`'s `run_fix_loop_for_finding()` — the LLM escape hatch
> invoked, per finding, only when the deterministic fixers (S-136) left a `mechanical` finding
> `unresolved`. It is ported near-verbatim from the sibling agent's own `fix_agent.py` (5-tool
> surface, `_safe_path` workspace confinement) with one architectural departure — per-finding
> invocation and per-finding `max_fix_attempts` budgeting rather than per-run (D22/D26, PRD
> AC17) — plus its own post-fix mandate check, `_assert_diff_confined_to()`, this agent's
> equivalent of the sibling's package.json check, narrowed to the single targeted finding's own
> `file_path`. S-139 (`#232`) built `pull_request.py`'s `build_pr_body()` plus its
> branch/idempotency/push mechanics (`branch_name()`, `existing_pr()`, `create_pr()`) — ported
> near-verbatim from the sibling agent's own `pull_request.py` (same credential-helper push,
> same `gh pr list` idempotency pattern, same "body always via `--body-file`, never inline
> `--body`" rule). S-136 through S-139 each built their piece standalone, independently
> unit/component-tested, but not yet called from `main.py`.
>
> **`mode=fix` end-to-end (S-140, `#233`): the capstone integration story.** `main.py` now wires
> all four S-136-S-139 building blocks into one live orchestrator loop, completing the full
> `resolve_credentials -> checkout -> scan -> classify -> fix -> rescan -> open_pr ->
> determine_outcome()` state machine for `mode=fix` (spec §8.8) — the same shape `mode=audit_only`
> reached at S-135, now mirrored for the write path. **Both modes of this agent are now fully
> wired end-to-end; no placeholder pipeline remains.** The `fix` step calls the two deterministic
> fixers first, then `fix_agent.py`'s LLM escape hatch only for findings they left `unresolved`
> (and only when `max_fix_attempts > 0`); the `rescan` step re-runs the full scanner set and
> gates on `rescan.py`'s `rescan_gate()`; the `open_pr` step is reached only on a clean gate and
> calls `pull_request.py`'s `open_pr_if_needed()`/`build_pr_body()`. See "Pipeline" below for the
> full per-step description.
>
> This story also resolved the two forward-reference gaps S-135 and S-139 left open. **S-135's
> `determine_outcome()` 3-tuple:** the function keeps its `(status, outcome, error_code)` shape
> for `fix` mode too — `main.invoke()` computes `pr_opened` at the call site
> (`status=="succeeded" and outcome in ("fixed","partial")`) rather than widening the tuple,
> mirroring the sibling `dependency-update` agent's own `determine_outcome()`, which likewise
> takes `pr_existed`/`has_pr` as caller-supplied flags rather than deriving them internally (see
> `agents/dependency-update/app/dependencyUpdate/main.py`'s `determine_outcome()` signature).
> **S-139's local `PipelineState`:** `main.py`'s `open_pr` step constructs the exact
> `PipelineState` shape `pull_request.py` defined — no superset was needed, and no type moved.
> See `pull_request.py`'s own module docstring, now rewritten to describe this resolution instead
> of the open gap it originally flagged for S-140.
>
> **Design note — idempotency location (PRD AC22):** the `open_pr` step's idempotency check
> (`existing_pr()`, via `open_pr_if_needed()`) is only ever reached after a clean re-scan gate —
> spec §8.8's diagram has exactly one edge into `open_pr`, `rescan --> open_pr: gate clean`, and
> `main.py` implements no other path into that step. This differs from a naive reading of spec
> §8.10's pseudocode, which checks `state.existing_pr_url` as its very first statement before any
> mode branching; this agent instead resolves idempotency only inside `open_pr`, meaning an
> already-open PR still costs a full fix+rescan cycle before the run short-circuits to
> `succeeded`/`not_applicable` — it is not a cheap pre-`scan` check. See `determine_outcome()`'s
> own docstring for the full rationale.
>
> `severity.py`'s five `severity_from_<tool>()` functions, `normalize.py`'s
> `Finding`/`Remediation` dataclasses, `fingerprint.py`'s `fingerprint()`,
> `scanners/semgrep_runner.py`'s `run_semgrep()`/`normalize_semgrep()`,
> `scanners/gitleaks_runner.py`'s `run_gitleaks()`/`normalize_gitleaks()`,
> `scanners/trivy_runner.py`'s `run_trivy()`/`normalize_trivy()`,
> `scanners/checkov_runner.py`'s `run_checkov()`/`normalize_checkov()`/`has_iac_files()`,
> `scanners/codeql_runner.py`'s `run_codeql()`/`normalize_codeql()`/`detect_languages()`,
> `dedupe.py`'s `dedupe()`, and `classifier.py`'s `classify()` are all now wired into the live
> `audit_only` pipeline via `scanners/__init__.py`'s `run_scanners()` dispatcher and `main.py`'s
> `scan`/`classify` steps — none of these are "not yet wired" placeholders any longer for
> `audit_only`. This is a deliberate, staged bring-up, not a shortcut: S-125 proved the
> deploy/credential/reporting pipe end-to-end first (mirroring how `agents/dependency-update/`
> proved its own pipe first), S-126-S-134 built and unit/component-tested each scanner, dedupe,
> and classification piece in isolation, and S-135 is the first story to converge all of them
> into one live pipeline for `audit_only`. S-136-S-139 built and independently tested each `fix`
> piece (fixers, rescan gate, LLM escape hatch, PR builder) in isolation, and S-140 is the second
> — and final — story to converge a full mode into one live pipeline, completing the agent's
> state machine for both `audit_only` and `fix`.
>
> **S-141 (final story — seed configuration, deployment, and real-repo verification):** appended
> the `security-analyst` `agents` seed block to `supabase/seed.sql` (Block 4), documented the
> `max_runtime_seconds`/`maxLifetime` manual-sync coupling and confirmed the two values already
> agree (5400s, PRD AC31), and confirmed by reading `reap_stale_runs()` that the existing
> `pg_cron` reaper needs no change for this agent (PRD AC31, generic per-run threshold snapshot,
> D8). Applying the seed migration, redeploying to pick up S-126-S-140's real pipeline, and the
> real `audit_only`/`fix` invocations against live/fixture repos (tasks 17.4-17.6, 17.10-17.11)
> remain **pending explicit user confirmation** — see "Deployment" and "Seed migration — rollback
> and impact" below.

## Layout

```
agents/security-analyst/
├── agentcore/
│   ├── agentcore.json     # Runtime configuration (Container, HTTP, lifecycle)
│   ├── aws-targets.json   # Deployment target (us-east-1)
│   └── cdk/                # CDK infrastructure (managed by agentcore CLI)
├── app/securityAnalyst/
│   ├── main.py              # Pipeline orchestrator entrypoint. Both modes fully wired:
│   │                        # `mode=audit_only` is scan -> classify -> determine_outcome (S-135);
│   │                        # `mode=fix` is scan -> classify -> fix -> rescan -> open_pr ->
│   │                        # determine_outcome (S-140), calling the `fixers/` modules (S-136),
│   │                        # `rescan.py` (S-137), `fix_agent.py` (S-138), and `pull_request.py`
│   │                        # (S-139) from the `fix`/`rescan`/`open_pr` steps.
│   ├── severity.py          # Per-tool severity normalization, pure functions (S-126)
│   ├── normalize.py         # Finding/Remediation frozen dataclasses (S-127)
│   ├── fingerprint.py       # fingerprint(), banded-line dedup key (S-127)
│   ├── dedupe.py            # dedupe(), _merge_overlapping_by_line(), MergedFinding — cross-tool
│   │                        # merge within one scan pass (file+category+line-overlap), distinct
│   │                        # from fingerprint.py's across-scan tolerance (S-133)
│   ├── classifier.py        # classify(), _is_major_bump(), _is_semver() — D22 three-bucket
│   │                        # mechanical/manual/unscannable model, D24/req-54 lockfile
│   │                        # boundary, requirement 27 major-version guard (S-134)
│   ├── fixers/               # Mechanical fix application (S-136) — called from main.py's `fix`
│   │   │                      # step (S-140), first in the deterministic-before-LLM order
│   │   ├── __init__.py        # Package docstring
│   │   ├── types.py           # FixOutcome shared result shape, reused by both fixers
│   │   ├── semgrep_autofix.py # apply_semgrep_autofix() — one blanket `semgrep --autofix
│   │   │                      # --config <RULESET>` call (RULESET imported verbatim from
│   │   │                      # scanners/semgrep_runner.py), applied-fingerprint tracking via
│   │   │                      # `git diff --name-only`
│   │   └── trivy_bump.py      # apply_trivy_bump() — applies Remediation.target_version (never
│   │                          # re-derives it); poetry.lock/Pipfile.lock targets bump the
│   │                          # companion manifest then reconcile via `poetry lock`/`pipenv
│   │                          # lock` (mirrors agents/dependency-update's reconcile_lockfile()
│   │                          # precedent); requirements.txt is edited in place, no
│   │                          # reconciliation step; anything needing more than a version-string
│   │                          # edit falls through to FixOutcome.unresolved (PRD requirement 29)
│   ├── rescan.py             # rescan_gate(), GateResult, _ALLOWED_NEW_FINDING_EXCEPTIONS (fixed,
│   │                        # enumerated table) — the agent's defining trust mechanism (D23/D25,
│   │                        # S-137): compares pre-fix/post-fix finding sets by fingerprint(),
│   │                        # clean=True only when every targeted finding is gone and no
│   │                        # unexplained new finding appeared (never inferred — requirement 34).
│   │                        # Called from main.py's `rescan` step (S-140) to gate entry to `open_pr`.
│   ├── fix_agent.py         # run_fix_loop_for_finding() — LLM escape hatch invoked once per
│   │                        # LLM-eligible finding, own fresh max_fix_attempts budget per call
│   │                        # (per-finding, not per-run — D22/D26, PRD AC17, this story's one
│   │                        # genuine architectural departure from the sibling agent's own
│   │                        # fix_agent.py). Ported near-verbatim: the 5-tool surface
│   │                        # (shell/read_file/write_file/find_files/grep_code) and _safe_path
│   │                        # workspace-confinement resolver. _assert_diff_confined_to() is this
│   │                        # agent's post-fix mandate check (equivalent of the sibling's
│   │                        # package.json check), narrowed to the single targeted finding's own
│   │                        # file_path; a violation raises MandateViolationError rather than the
│   │                        # diff being trusted. _changed_files() deliberately uses `git status
│   │                        # --porcelain` (catches untracked new files from write_file), not the
│   │                        # sibling's `git diff --name-only` — see the function's own docstring
│   │                        # (S-138). Called from main.py's `fix` step (S-140), only for
│   │                        # mechanical findings the deterministic fixers left `unresolved`.
│   ├── pull_request.py      # branch_name(), existing_pr(), create_pr(), build_pr_body() (req
│   │                        # 38-43, S-139) — branch/idempotency/push mechanics ported near-
│   │                        # verbatim from the sibling agent's own `pull_request.py`; body
│   │                        # section builders (summary, fixed-findings, always-present
│   │                        # remaining-manual, conditional D24-boundary/major-version-guard/
│   │                        # AI-modification-warning, always-present re-scan confirmation line)
│   │                        # are new. Defines its own local, minimal `PipelineState` dataclass —
│   │                        # `build_pr_body()`'s own input contract. `main.py`'s `open_pr` step
│   │                        # (S-140) constructs this exact shape directly at the call site (no
│   │                        # superset needed — see the module's own docstring for the resolution).
│   │                        # Called from main.py's `open_pr` step, reached only on a clean
│   │                        # re-scan gate.
│   ├── scanners/
│   │   ├── __init__.py        # run_scanners() dispatcher + AllScannersFailedError (S-135) — the
│   │   │                      # aggregation point for all five run_<tool>() call sites; sequential,
│   │   │                      # not parallelized (PRD §11/OQ6). Also relativize_path() +
│   │   │                      # canonicalize_category() + _normalize_findings() (S-141
│   │   │                      # real-invocation fixes): every returned finding's file_path is made
│   │   │                      # workspace-relative here (real Semgrep/Gitleaks echo the absolute
│   │   │                      # workspace path while Trivy/Checkov/CodeQL report scan-root-relative
│   │   │                      # paths) and its cwe_or_category is canonicalized to CWE-<int>
│   │   │                      # (CodeQL emits zero-padded CWE-079, Semgrep CWE-79) so dedupe() keys match
│   │   ├── types.py           # ScanStatus/ScanResult shared shape, reused verbatim by S-129-S-132 (S-127-adjacent, landed S-128)
│   │   ├── semgrep_runner.py  # RULESET, run_semgrep(), normalize_semgrep() (S-128) — called by
│   │   │                      # run_scanners() for audit_only mode (S-135)
│   │   ├── gitleaks_runner.py # run_gitleaks(), normalize_gitleaks() (S-129) — called by
│   │   │                      # run_scanners() for audit_only mode (S-135)
│   │   ├── trivy_runner.py    # run_trivy() fs/config/conditional-image dispatch, normalize_trivy(),
│   │   │                      # _JS_LOCKFILES D24/req-54 boundary (S-130) — called by
│   │   │                      # run_scanners() for audit_only mode (S-135)
│   │   ├── checkov_runner.py  # run_checkov(), normalize_checkov(), has_iac_files() pre-flight
│   │   │                      # skip detector (Terraform/Dockerfile/CloudFormation/Kubernetes),
│   │   │                      # unconditional structural remediation (S-131) — called by
│   │   │                      # run_scanners() for audit_only mode (S-135)
│   │   └── codeql_runner.py   # run_codeql(), normalize_codeql(), detect_languages() JS/TS +
│   │                          # Python-only two-phase (database create/analyze) dispatch, merged
│   │                          # findings across languages, unconditional structural remediation
│   │                          # (S-132) — called by run_scanners() for audit_only mode (S-135)
│   ├── agent_reporter.py    # Reporting SDK (byte-identical copy, docs/reference/)
│   ├── config.py            # Environment variable reads, this agent's own clock constants
│   ├── credentials.py       # Supabase key + GitHub App token resolution (unmodified copy)
│   ├── scrubber.py          # Token scrubbing for output/errors (unmodified copy)
│   ├── heartbeat.py         # Long-step keep-alive: live-yield heartbeat chunks (unmodified copy)
│   ├── signal_backstop.py   # Best-effort SIGTERM terminal-report backstop (unmodified copy)
│   ├── Dockerfile           # ARM64 container: Python 3.13 + git + gh + the CodeQL CLI (pinned
│   │                        # v2.27.0, S-132 — the first story to install a real scanner
│   │                        # toolchain into this image, per its own blocking ARM64-availability
│   │                        # pre-check) plus its two query packs, gitleaks + trivy as pinned
│   │                        # ARM64 binaries from GitHub Releases, and semgrep + checkov as
│   │                        # pinned pip packages via pyproject.toml (S-141 — closed the
│   │                        # S-128/S-129/S-130/S-131 toolchain-install gap that each of those
│   │                        # stories tracked and deferred; all five scanner binaries now ship
│   │                        # in the image). Also installs a Node.js runtime (NodeSource,
│   │                        # ARG NODE_MAJOR=22) right after the query-pack download step --
│   │                        # a real-invocation S-141 finding: CodeQL's JS/TS extractor shells
│   │                        # out to Node.js to parse .ts/.tsx via the TypeScript compiler API
│   │                        # regardless of --build-mode=none, which only skips a *custom*
│   │                        # build command, not the extractor's own parsing step
│   ├── pyproject.toml       # Python dependencies (pinned)
│   ├── Makefile              # install/lint/format-check/typecheck/test-unit/test-component/test-cov/audit/validate
│   └── tests/
│       ├── unit/            # Pure unit tests (no I/O), incl. test_severity.py (S-126),
│       │                    # test_fingerprint.py (S-127), test_semgrep_runner.py (S-128),
│       │                    # test_gitleaks_runner.py + test_gitleaks_redaction.py (S-129),
│       │                    # test_trivy_runner.py (S-130, normalize_trivy() + lockfile boundary),
│       │                    # test_checkov_runner.py (S-131, normalize_checkov() dual-shape
│       │                    # parsing + has_iac_files() detection incl. vendored-dir exclusion),
│       │                    # test_codeql_runner.py (S-132, normalize_codeql() rule-level
│       │                    # security-severity/CWE-tag lookup + detect_languages() 4-way
│       │                    # trigger-condition matrix), test_dedupe.py (S-133, merge/no-merge
│       │                    # cases, three-way chained overlap, reported_by dedup/order,
│       │                    # severity tie-break), test_classifier.py (S-134, every classify()
│       │                    # branch, the JS/TS-excluded vs. Python-not-excluded boundary side
│       │                    # by side, and the lockfile_managed=True + major-bump-simultaneous
│       │                    # case, EC-38), test_scanner_dispatch.py (S-135, run_scanners()
│       │                    # per-tool dispatch order + AllScannersFailedError all-failed vs.
│       │                    # partial-failure boundary), test_determine_outcome.py (S-135,
│       │                    # parametrized over PRD §8.1 audit_only rows + min_severity
│       │                    # crossing, incl. AC-12b's gate-outcome-not-artifact case; extended
│       │                    # S-140 with `TestFixOutcomeTable`/`test_fix_mode_matrix`,
│       │                    # parametrized over every PRD §8.1 `fix`-mode row, confirming the
│       │                    # `audit_only` rows above stay byte-for-byte unchanged),
│       │                    # test_trivy_bump.py (S-136, `_bump_manifest_text()`/`_bump_line()`/
│       │                    # `_name_pattern()` pure-function target-version selection, no I/O),
│       │                    # test_rescan_gate.py (S-137, 13 tests: all four still-present/
│       │                    # new-finding combinations, the allow-list exception path incl. a
│       │                    # still-present target alongside an allow-listed new finding, and
│       │                    # two near-miss cases proving no fuzzy inference — pluralized rule
│       │                    # id, right pattern under the wrong tool),
│       │                    # test_safe_path.py (S-138, 22 tests: traversal/absolute-path/symlink
│       │                    # escape refusal across every path-taking tool call shape),
│       │                    # test_diff_confinement.py (S-138, 12 tests:
│       │                    # _assert_diff_confined_to() confined-vs-out-of-scope cases),
│       │                    # test_fix_tools.py (S-138, 23 tests, ported near-verbatim from the
│       │                    # sibling agent's own test_fix_tools.py, added proactively per this
│       │                    # story's completion instructions: the 5 tool bodies exercised
│       │                    # directly via __wrapped__, not just _safe_path's own unit tests),
│       │                    # test_pr_body.py (S-139, 22 tests: synthetic local `PipelineState`
│       │                    # fixtures — no-LLM, LLM-used, D24-boundary present, major-version-
│       │                    # guard present, zero-remaining, all-sections-simultaneously —
│       │                    # always-present-even-empty remaining-manual table, conditional
│       │                    # section gating, branch-name format, markdown-cell escaping)
│       ├── component/       # Component tests (mocked externals), incl.
│       │                    # test_semgrep_runner_subprocess.py (S-128, subprocess.run mocked),
│       │                    # test_gitleaks_runner.py (S-129, subprocess.run mocked),
│       │                    # test_trivy_runner.py (S-130, three-mode subprocess dispatch mocked),
│       │                    # test_checkov_runner.py (S-131, run_checkov() subprocess dispatch
│       │                    # mocked, incl. test_skip_no_iac AC-23),
│       │                    # test_codeql_runner.py (S-132, two-phase per-language subprocess
│       │                    # dispatch mocked, incl. skip path and both-languages merge),
│       │                    # test_audit_only_pipeline.py (S-135, full main.py `invoke()`
│       │                    # audit_only path, all five scanners mocked — clean repo, findings
│       │                    # +/- fail_on_findings, min_severity gating incl. AC-12b, all- and
│       │                    # one-of-five-scanner-failure), test_mechanical_fixers.py (S-136,
│       │                    # `subprocess.run` mocked for semgrep/git/poetry/pipenv; real
│       │                    # filesystem I/O via `tmp_path` for applied-vs-untouched
│       │                    # assertions; AC28's mixed mechanical/manual/unscannable batch —
│       │                    # only mechanical-bucket files change),
│       │                    # test_fix_agent.py (S-138, 15 tests, `patch("fix_agent.Agent")` —
│       │                    # zero-Bedrock-call at max_fix_attempts=0, per-finding budget
│       │                    # exhaustion/early-stop/fresh-budget-per-finding, single-finding
│       │                    # prompt scoping, _assert_diff_confined_to() enforcement,
│       │                    # Agent-exception and all-scanners-failed-during-rescan handling,
│       │                    # five-tool construction, system-prompt content),
│       │                    # test_pr_creation.py (S-139, 16 tests: idempotency via mocked
│       │                    # `gh pr list`, `open_pr_if_needed` short-circuit on existing PR
│       │                    # (AC-22), happy-path branch/commit/push/create order,
│       │                    # `--body-file`-never-inline (AC-17 groundwork), fixed commit
│       │                    # message/branch-name format, never pushes to default branch (req
│       │                    # 40), push-failure token scrubbing — all `subprocess.run` mocked),
│       │                    # test_fix_mode_pipeline.py (S-140, full `main.invoke()` `fix` path
│       │                    # driven exactly like a real AgentCore invocation, every external
│       │                    # boundary mocked — mirrors test_audit_only_pipeline.py's pattern:
│       │                    # AC13 happy path/zero-LLM, AC14/AC15 re-scan gate blocks (unverified
│       │                    # fix, regression), AC21 no-mechanical-findings no-op, AC22
│       │                    # idempotency short-circuit, AC29 all-7-run_steps-present, requirement
│       │                    # 47 metrics contract, heartbeat keep-alive under a slow-scan fixture,
│       │                    # multi-tool-simultaneous findings — no real subprocess/network/LLM
│       │                    # call is ever made)
│       └── fixtures/        # Static scanner-output fixtures (semgrep_*.json, gitleaks_*.json,
│                            # trivy_{clean,config,fs_npm,fs_python,image}.json (S-130),
│                            # checkov_{clean,findings,no_severity}.json (S-131),
│                            # codeql_{clean,js_ts,python}.json (S-132))
│                            # plus gitleaks_fixture_repo/ + gitleaks_fixture_repo.bundle (S-129):
│                            # a tiny repo containing one clearly-labeled dummy secret
│                            # (FIXTURE_DUMMY_SECRET_DO_NOT_USE_...) used to exercise
│                            # run_gitleaks() end-to-end against a real file tree
└── README.md                 # This file
```

## Pipeline

### `mode=audit_only` (S-135 — first fully working mode)

1. Validate payload (reject with `INVALID_PARAMS` on bad input — no clone attempted)
2. Resolve credentials (Supabase service role key, GitHub App token — reuses the sibling agent's
   `credentials.py` unmodified against the shared `github_installations` row)
3. Clone repository (depth 1)
4. **`scan`** — `scanners.run_scanners()` dispatches every requested tool (default: all five)
   sequentially against the checked-out workspace, each isolating its own crash/timeout/
   unparseable-output handling into a non-fatal `ScanStatus.FAILED` (PRD requirement 18). The step
   is wrapped in `heartbeat.run_with_heartbeat()` (spec §8.8) since it is the single longest step —
   CodeQL's `database create`/`database analyze` phase in particular. If every requested scanner
   fails, `run_scanners()` raises `AllScannersFailedError` and the run terminates
   `failed`/`not_applicable`/`ALL_SCANNERS_FAILED` (PRD AC24); a partial failure (one, or even four,
   of five) is non-fatal — the run continues with whatever `PASSED` results exist. Before returning,
   `run_scanners()` relativizes every finding's `file_path` against the workspace
   (`relativize_path()`, spec §8.1's "repo-relative, normalized separators" contract) so cross-tool
   dedup keys line up and the ephemeral `/tmp` workspace path never reaches the `audit_report`
   artifact or a PR body — the real Semgrep and Gitleaks binaries echo the absolute workspace path
   they were invoked with, unlike Trivy/Checkov/CodeQL (S-141 real-invocation finding). In the same
   pass (`_normalize_findings()`) it canonicalizes every finding's `cwe_or_category` via
   `canonicalize_category()` — bare `CWE-<n>` becomes `CWE-<int>` with leading zeros stripped, other
   values untouched — because CodeQL's SARIF tags yield zero-padded `CWE-079` while Semgrep yields
   `CWE-79`, which made `dedupe()` report the same line twice (PRD requirement 22; S-141 finding).
5. **`classify`** — the combined `Finding` list from every `PASSED`/`SKIPPED` scan result is deduped
   (`dedupe.dedupe()`, cross-tool file+category+line-overlap merge into `MergedFinding`) and each
   merged finding is classified (`classifier.classify()` — `mechanical`/`manual`/`unscannable`).
6. **`audit_report` artifact** — `main.build_audit_report()` groups every classified finding by
   bucket/tool/severity and is attached via `run.artifact(...)`. It is always built from the full,
   unfiltered finding set — `min_severity` never narrows this artifact (PRD requirement 62 /
   AC-12b; see `_at_or_above_floor()`'s docstring).
7. **`determine_outcome()`** — pure function, `(status, outcome, error_code)`. Applies
   `min_severity` (via `_at_or_above_floor()`) to the finding set to decide the terminal status
   only:
   - no findings at/above the floor → `succeeded` / `no_findings` (PRD AC3, AC12b)
   - findings at/above the floor, `fail_on_findings=false` → `succeeded` / `needs_review` (PRD AC5)
   - findings at/above the floor, `fail_on_findings=true` (default) → `failed` / `AUDIT_FINDINGS`
     (PRD AC4, AC9)

`audit_only` never opens a branch or PR — it is a read-only scan/report mode (PRD §8.1).

### `mode=fix` (S-140 — fully wired)

Shares `resolve_credentials` / `checkout` / `scan` / `classify` with `audit_only` above (steps
1-6, including the same `heartbeat.run_with_heartbeat()` wrapping for `scan`), then continues
into the write path — `fix -> rescan -> open_pr -> determine_outcome()`. Fix mode builds its own
`audit_report` artifact (`build_fix_audit_report()` — `build_audit_report()`'s grouping plus
`findings_before`/`findings_after` bucket counts) and records it on every terminal path listed
below (AC21 no-op, `RESCAN_NOT_CLEAN`, and before `open_pr`), per PRD requirements 36/37 and user
story 4 (S-141 real-invocation finding):

7. **`fix`** — the classified findings are split by bucket (`classifier.py`'s
   `mechanical`/`manual`/`unscannable`, D22). If there are no `mechanical` findings, the step is a
   no-op (AC21): `rescan` and `open_pr` are never entered — there is nothing to fix and D23
   permits no PR without a fix to verify — but an `audit_report` artifact (before == after counts)
   is still recorded so the remaining `manual`/`unscannable` findings are visible. Otherwise:
   - `fixers/semgrep_autofix.py`'s `apply_semgrep_autofix()` and `fixers/trivy_bump.py`'s
     `apply_trivy_bump()` run first, against every `mechanical` finding.
   - For each finding either fixer left `unresolved`, `fix_agent.py`'s
     `run_fix_loop_for_finding()` (the LLM escape hatch) is invoked once, with its own fresh
     `max_fix_attempts` budget — only when `max_fix_attempts > 0` (PRD AC17, D22/D26). A finding
     the deterministic fixers fully resolved never reaches the LLM loop at all — zero Bedrock
     calls for it, not merely a call that immediately succeeds.
   - `metrics.fix_attempts_deterministic` counts every `mechanical` finding attempted;
     `metrics.fix_attempts_llm`/`metrics.llm_used` count only LLM invocations, which stay at their
     falsy defaults whenever the deterministic path resolved everything (AC13).
8. **`rescan`** — only entered when `mechanical` was non-empty. Re-runs the full scanner set
   (`_scan_with_heartbeat()`, the same heartbeated helper `scan` uses) against the working tree,
   then gates the result through `rescan.py`'s `rescan_gate()`: `clean=True` only when every
   fingerprint targeted by the `fix` step is gone and no unexplained new finding appeared
   (D23/D25, requirement 34). A not-clean gate terminates the run
   `failed`/`needs_review`/`RESCAN_NOT_CLEAN` (AC14/AC15) after recording the after-scan as an
   `audit_report` artifact (PRD requirement 36) — `open_pr` is never entered, even if
   the working tree carries a genuine local change from an unresolved fix attempt or the LLM's
   mandate-confined edits.
9. **`open_pr`** — reached only on a clean re-scan gate (spec §8.8's diagram has exactly one edge
   into this step: `rescan --> open_pr: gate clean`). The `audit_report` artifact is recorded
   immediately before this step, so it exists even if PR creation fails. Constructs `pull_request.py`'s
   `PipelineState` from the run's own bookkeeping (fixed findings, remaining manual/unscannable
   findings, the D24-boundary and major-version-guard subsets, LLM usage, pre-/post-fix finding
   counts) and calls `build_pr_body()` then `open_pr_if_needed()`. `open_pr_if_needed()` performs
   the PRD AC22 idempotency check (`existing_pr()` via `gh pr list`) — an already-open
   `security/fix-*` PR short-circuits to `succeeded`/`not_applicable` with no second branch/push/
   PR, but a new branch is only ever avoided here, not before `rescan` — see the design note
   below. Any push/PR-create failure after this point is a `PullRequestError`, mapped to
   `failed`/`needs_review` (the fix itself succeeded; only the PR handoff failed).
10. **`determine_outcome()`** — same pure function as `audit_only`, `mode="fix"` branch (spec
    §8.10's second pseudocode block): `no_findings`/`needs_review` when there was nothing
    mechanical to fix (AC21); `failed`/`RESCAN_NOT_CLEAN` on a not-clean gate; `not_applicable` on
    the idempotency short-circuit; otherwise `succeeded`/`fixed` (nothing left in
    `manual`/`unscannable` after gating) or `succeeded`/`partial` (AC13).

All 7 `run_steps` keys (`resolve_credentials`/`checkout`/`scan`/`classify`/`fix`/`rescan`/
`open_pr`) appear, in order, each terminal, on the full happy/blocked-at-rescan path (AC29) — the
AC21 no-mechanical-findings short-circuit is the one branch that enters `fix` and then terminates
without `rescan`/`open_pr`, the same precedent `audit_only`'s 4-step-only happy path already set
for never needing a 5th step for `audit_report`.

> **Design note — `determine_outcome()`'s 3-tuple return:** spec §8.10's pseudocode describes a
> 4-tuple `(status, outcome, error_code, pr_opened)`. `determine_outcome()` keeps its 3-tuple
> shape `(status, outcome, error_code)` for both modes — `audit_only` never opens a PR, so
> `pr_opened` would always be `False` there and carries no information, and for `fix` mode it is
> fully recoverable at the call site as `status == "succeeded" and outcome in ("fixed",
> "partial")` (deliberately excluding `not_applicable`, the idempotency case, since no *new* PR is
> opened there). `main.invoke()` computes `pr_opened` this way rather than widening the tuple,
> mirroring the sibling `dependency-update` agent's own `determine_outcome()`, which likewise
> takes `pr_existed`/`has_pr` as plain caller-supplied booleans rather than deriving them
> internally from a URL (see `agents/dependency-update/app/dependencyUpdate/main.py`). Keeping the
> 3-tuple required zero changes to any already-merged `audit_only` call site or test — the
> explicit mandate for this story.
>
> **Design note — idempotency location (PRD AC22):** spec §8.10's pseudocode checks
> `state.existing_pr_url` as its very first statement, before any mode branching — implying
> idempotency could short-circuit before `scan` even runs. This agent instead only ever calls
> `pull_request.existing_pr()` (via `open_pr_if_needed()`) from inside the `open_pr` step, which
> is reached only after a clean `rescan` gate — spec §8.8's diagram has no other edge into
> `open_pr`. Practically, this means an already-open PR does not skip the run early: the fix
> attempt, the full re-scan, and the gate check all still run (and are paid for) before the
> idempotency short-circuit can fire and avoid only the branch/push/PR-create step itself. This
> was a deliberate choice, not an oversight — checking idempotency any earlier is not supported by
> the state diagram.

## Invocation payload (spec S6.1)

```json
{
  "run_id": "<uuid>",
  "repository_org": "my-org",
  "repository_name": "checkout-api",
  "params": {
    "mode": "audit_only",
    "fail_on_findings": true,
    "min_severity": "low",
    "max_fix_attempts": 3,
    "scanners": ["semgrep", "gitleaks", "trivy", "checkov", "codeql"]
  }
}
```

`run_id`, `repository_org`, `repository_name` are required. `params` is optional and defaulted
(`mode=audit_only`, `fail_on_findings=true`, `min_severity=low`, `max_fix_attempts=3` clamped
0-5, `scanners=` all five). `min_severity` must be one of `low`/`medium`/`high`/`critical`;
`scanners` must be a non-empty subset of `semgrep`/`gitleaks`/`trivy`/`checkov`/`codeql`. An
invalid payload terminates `failed` / `not_applicable` / `INVALID_PARAMS` before any clone
(PRD AC28). The entrypoint tolerates the AgentCore `prompt` wrapper (single or double-wrapped,
identical mechanism to the sibling agent), and requires an existing `queued` `runs` row before
invoking — see the sibling agent's README for the full prerequisite/troubleshooting flow (shared
`RunReporter` contract).

The example above uses `mode=audit_only` (the default), which runs the real five-tool
scan/classify/report pipeline described under Pipeline above. `mode=fix` (`_VALID_MODES`) is
fully implemented as of S-140: it runs the same scan/classify steps, then the real
fix/rescan/open_pr pipeline described under Pipeline above — `succeeded`/`fixed` or `partial`
with an opened PR on the happy path, `failed`/`RESCAN_NOT_CLEAN` if the re-scan gate is not clean,
or `succeeded`/`no_findings`/`needs_review` when there was nothing mechanical to fix (AC21). Both
modes accepted by `validate_payload()` now run their real pipeline end-to-end — neither is a
placeholder any longer.

## Deployment

```bash
cd agents/security-analyst
agentcore deploy -y      # non-interactive build + deploy
agentcore status         # confirm runtime ready; copy the runtime ARN
```

After a successful deploy, the `runtime_arn` is recorded in `supabase/seed.sql` as part of
**S-141**, which appended the `security-analyst` block (Block 4) to the shared seed file,
following the exact idempotent `on conflict (slug) do update` shape of the sibling
`dependency-update` block (Block 3) — see spec §5.2. The seed row's `runtime_arn` reflects the
runtime already deployed under S-125
(`arn:aws:bedrock-agentcore:us-east-1:755641879575:runtime/securityanalyst_security_analyst-w6CpbYHRE0`).
**Applying** that seed migration against anything other than a local/dev Supabase stack is a
separate, confirmation-gated step (S-141 tasks 17.4-17.6) — this repo only carries the artifact
until that confirmation happens; a redeploy is also expected before real invocations, since S-125
only shipped the placeholder scan pipeline and S-126-S-140 have since replaced it end-to-end.

### Seed migration — rollback and impact (S-141)

The `security-analyst` seed block is a single `insert ... on conflict (slug) do update` against
the `agents` table, following the same idempotent shape as `dependency-update`'s existing Block 3
row. Rollback, if ever needed, is:

```sql
update agents set is_enabled = false where slug = 'security-analyst';
-- or, if the row must be removed outright and no run has referenced it yet:
delete from agents where slug = 'security-analyst';
```

**No data-loss risk.** The `agents` row carries only static configuration (name, description,
version, runtime pointer, timeout thresholds, default params, params schema) — the agent has no
other persisted state of its own. The one caveat is referential: once any `runs` row exists with
`agent_id` pointing at this row, `agents` cannot be hard-deleted (`runs.agent_id references
agents(id) on delete restrict`); disabling via `is_enabled = false` is the correct rollback path
at that point, matching how `dependency-update` would be rolled back. Re-applying the seed after a
disable is idempotent and restores the row exactly, since every column the block sets is covered
by the `on conflict ... do update` clause.

## Local Development

```bash
cd agents/security-analyst
agentcore dev
# In another terminal:
curl http://localhost:8080/ping
```

## Configuration

### Runtime Timeouts (spec S9.2, PRD S12.3)

| Setting | Value | Location |
|---------|-------|----------|
| `maxLifetime` | 5400s | `agentcore/agentcore.json` |
| `idleRuntimeSessionTimeout` | 900s | `agentcore/agentcore.json` |
| `max_runtime_seconds` | 5400 | `supabase/seed.sql` (Block 4, `agents` table) |
| `grace_seconds` | 150 | `supabase/seed.sql` (Block 4, `agents` table) |
| `start_timeout_seconds` | 300 | `supabase/seed.sql` (Block 4, `agents` table) |

This agent recomputes ADR-006's clock-invariant chain for its own, higher bounds — a five-scanner
step (CodeQL's database-build phase especially) can legitimately run far longer than the sibling
agent's `pnpm test`. At entrypoint start `config.assert_clock_invariant()` fails fast
(`ClockConsistencyError`) unless
`FIX_COMMAND_TIMEOUT <= SCANNER_TIMEOUT <= IDLE_SESSION_TIMEOUT <= MAX_LIFETIME <= REAPER_THRESHOLD_SECONDS`
and `HEARTBEAT_INTERVAL <= IDLE_SESSION_TIMEOUT / 2`. `IDLE_SESSION_TIMEOUT` / `MAX_LIFETIME` MUST
mirror `agentcore.json` `lifecycleConfiguration`, and `REAPER_THRESHOLD_SECONDS` (default
`MAX_LIFETIME + 120`) MUST equal the database `max_runtime_seconds` + `grace_seconds` set for this
agent's row in `supabase/seed.sql` (S-141).

**This coupling is a manual-sync obligation, not an enforced invariant** — nothing in the repo
verifies at runtime or in CI that `agentcore.json`'s `maxLifetime` and `supabase/seed.sql`'s
`max_runtime_seconds` agree; a future edit to either file can silently drift the other. As of
S-141, the two values are confirmed equal in the committed artifacts: `agentcore.json`
`lifecycleConfiguration.maxLifetime = 5400` and `seed.sql` Block 4's `max_runtime_seconds = 5400`
(PRD AC31, first half). Whoever changes one value in the future MUST update the other by hand and
re-verify this table. The database side of the pair (`runs.max_runtime_seconds` /
`runs.grace_seconds`) is a per-run snapshot (D8) taken from this agent's `agents` row at run
creation, so an edit to `seed.sql` after the row already exists only takes effect for runs created
after the seed is re-applied.

**The reaper needs no change for this agent (PRD AC31, second half).** `reap_stale_runs()`
(`supabase/migrations/20260902200101_initial_schema.sql`, see also
[ADR-004](../../docs/adr/ADR-004-schedule-pg-cron-reaper.md)) reads `runs.max_runtime_seconds` and
`runs.grace_seconds` off the run row it is currently examining — those columns are generic,
per-run snapshots (D8) populated from whichever `agents` row the run belongs to, and the function
contains no `agent_id`/`slug` branch or any hardcoded threshold. A security-analyst run that hangs
past `5400 + 150 = 5550` seconds is reaped by the exact same code path, with the exact same
`timed_out` status and `RUNTIME_TIMEOUT` `run_events` row, that already covers `dependency-update`
— confirmed by reading the function; no synthetic-row or live-hang exercise is required to
establish this (S-141 task 17.9). See `docs/technical-guidelines.md` §7/§8 and
[ADR-006](../../docs/adr/ADR-006-long-step-keepalive-and-clock-invariant.md).

### Environment Variables (set by AgentCore / Secrets Manager)

| Variable | Required | Description |
|----------|----------|-------------|
| `SUPABASE_URL` | Yes | Supabase project URL |
| `SUPABASE_KEY_SECRET_ID` | Yes | Secrets Manager ID for Supabase service role key |
| `RUN_ID` | Yes | Execution ID (passed by control plane at invocation) |
| `RUN_PARAMS` | Yes | JSON payload with invocation parameters |
| `AGENT_LOG_LEVEL` | No | Minimum log level captured (default: INFO) |
| `MODEL_ID` | No | Bedrock model for the LLM fix loop (`fix_agent.py`, invoked from `mode=fix`'s `fix` step, S-140) (default: `us.anthropic.claude-sonnet-4-6`) |
| `SCANNER_TIMEOUT` | No | Per-scanner subprocess timeout, in seconds (default: 600) |
| `FIX_COMMAND_TIMEOUT` | No | Per-LLM-shell-call timeout in the fix agent, in seconds (default: 180) |
| `IDLE_SESSION_TIMEOUT` | No | Mirror of `agentcore.json` `idleRuntimeSessionTimeout` (default: 900) |
| `MAX_LIFETIME` | No | Mirror of `agentcore.json` `maxLifetime` (default: 5400) |
| `REAPER_THRESHOLD_SECONDS` | No | Mirror of the DB `max_runtime_seconds` + `grace_seconds` (default: `MAX_LIFETIME + 120`) |
| `HEARTBEAT_INTERVAL` | No | Keep-alive cadence during long steps, in seconds; must be `<= IDLE_SESSION_TIMEOUT / 2` (default: 120) |

## Testing

Quality gates run through the `Makefile` (canonical command contract, mirrors `TESTING.md`). Run
from `app/securityAnalyst/`:

```bash
cd agents/security-analyst/app/securityAnalyst
make install         # pip install -e '.[dev]'
make test            # python -m pytest (all layers)
make test-unit       # python -m pytest -m unit
make test-component  # python -m pytest -m component
make test-cov        # python -m pytest --cov --cov-report=term-missing
make validate        # aggregate gate: lint + format-check + typecheck + test-cov + audit
```

Layer markers (`unit` / `component`) are applied automatically by `tests/conftest.py` based on the
test's directory, mirroring the sibling agent's convention.
