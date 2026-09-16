# security-analyst Agent

Five-tool security scanner agent (semgrep, gitleaks, trivy, checkov, CodeQL) for the Agent Fleet
Control Plane. Runs as an AWS Bedrock AgentCore Container runtime.

> **Status (S-125-S-137):** project scaffold, deploy, and reporting pipe (S-125), per-tool
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
> **`mode=audit_only` is the first fully working mode of this agent.** `mode=fix` is still the
> S-125 placeholder (straight to `succeeded`/`no_findings`, no scanners run) — S-138-S-140 still
> need to wire `fix`/`rescan`/`open_pr` and the orchestration loop into it. S-136 (`#229`) added the
> first two of `fix` mode's building blocks — `fixers/semgrep_autofix.py` (Semgrep native-patch
> application) and `fixers/trivy_bump.py` (Trivy version-bump application, plus a retroactive,
> additive `Remediation.package_name` field so the fixer can locate which manifest line to edit —
> see `normalize.py`'s `Remediation` docstring) — but **neither fixer is called from `main.py`
> yet**: they are standalone, independently unit/component-tested modules, not yet part of the
> live `fix` pipeline. S-137 (`#230`) added the third building block, `rescan.py`'s
> `rescan_gate()` — the agent's defining trust mechanism (D23/D25): it compares a pre-fix and
> post-fix finding set by `fingerprint()` and only reports `clean=True` when every targeted
> finding is gone and no unexplained new finding appeared, checked only against a fixed,
> enumerated allow-list table (`_ALLOWED_NEW_FINDING_EXCEPTIONS`), never inferred (requirement
> 34). Like the two fixers, **`rescan.py` is standalone and not yet called from `main.py`** —
> wiring `fix`/`rescan`/`open_pr` into one live orchestrator loop is S-140's job, not this
> story's. This is distinct from `audit_only`'s S-135 status above, which *is* fully
> wired end-to-end.
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
> into one live pipeline. `fix`/`rescan`/`open_pr` remain unwired (S-136-S-140).

## Layout

```
agents/security-analyst/
├── agentcore/
│   ├── agentcore.json     # Runtime configuration (Container, HTTP, lifecycle)
│   ├── aws-targets.json   # Deployment target (us-east-1)
│   └── cdk/                # CDK infrastructure (managed by agentcore CLI)
├── app/securityAnalyst/
│   ├── main.py              # Pipeline orchestrator entrypoint. `mode=audit_only`: real
│   │                        # scan -> classify -> determine_outcome pipeline (S-135). `mode=fix`
│   │                        # still on the S-125 placeholder — the `fixers/` modules (S-136) and
│   │                        # `rescan.py` (S-137) exist but are not yet called from here
│   │                        # (S-138-S-140 wire it).
│   ├── severity.py          # Per-tool severity normalization, pure functions (S-126)
│   ├── normalize.py         # Finding/Remediation frozen dataclasses (S-127)
│   ├── fingerprint.py       # fingerprint(), banded-line dedup key (S-127)
│   ├── dedupe.py            # dedupe(), _merge_overlapping_by_line(), MergedFinding — cross-tool
│   │                        # merge within one scan pass (file+category+line-overlap), distinct
│   │                        # from fingerprint.py's across-scan tolerance (S-133)
│   ├── classifier.py        # classify(), _is_major_bump(), _is_semver() — D22 three-bucket
│   │                        # mechanical/manual/unscannable model, D24/req-54 lockfile
│   │                        # boundary, requirement 27 major-version guard (S-134)
│   ├── fixers/               # Mechanical fix application (S-136) — NOT yet called from main.py
│   │   ├── __init__.py        # Package docstring: both fixers are standalone, unwired until S-140
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
│   │                        # Standalone and unit-tested; NOT yet called from main.py (S-140 wires it).
│   ├── scanners/
│   │   ├── __init__.py        # run_scanners() dispatcher + AllScannersFailedError (S-135) — the
│   │   │                      # aggregation point for all five run_<tool>() call sites; sequential,
│   │   │                      # not parallelized (PRD §11/OQ6)
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
│   │                        # pre-check) plus its two query packs — does NOT yet install the
│   │                        # semgrep/gitleaks/trivy/checkov binaries (S-128/S-129/S-130/S-131's
│   │                        # tests all mock subprocess.run; those four tools' own real-binary
│   │                        # install/wiring is a separate, still-open gap, tracked outside this
│   │                        # story's scope per issue #192)
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
│       │                    # crossing, incl. AC-12b's gate-outcome-not-artifact case),
│       │                    # test_trivy_bump.py (S-136, `_bump_manifest_text()`/`_bump_line()`/
│       │                    # `_name_pattern()` pure-function target-version selection, no I/O),
│       │                    # test_rescan_gate.py (S-137, 13 tests: all four still-present/
│       │                    # new-finding combinations, the allow-list exception path incl. a
│       │                    # still-present target alongside an allow-listed new finding, and
│       │                    # two near-miss cases proving no fuzzy inference — pluralized rule
│       │                    # id, right pattern under the wrong tool)
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
│       │                    # only mechanical-bucket files change)
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
   of five) is non-fatal — the run continues with whatever `PASSED` results exist.
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

### `mode=fix` (still the S-125 placeholder)

`mode=fix` has not been wired yet: after `checkout`, it goes straight to `succeeded`/`no_findings`
with every scanner reported `scanners_skipped` — no scanner runs. S-138-S-140 replace this
placeholder with the real `scan -> classify -> fix -> rescan -> open_pr` pipeline (spec
`workstream/specification-prd-security-analyst-agent.md` S8.8); this is explicitly out of S-135's
scope. S-136 (`#229`) already built the two deterministic fixers (`fixers/semgrep_autofix.py`,
`fixers/trivy_bump.py`), and S-137 (`#230`) already built the re-scan gate (`rescan.py`'s
`rescan_gate()`) this pipeline will call, but none of the three are invoked yet — see Layout
above. Wiring `fix`/`rescan`/`open_pr` into one live orchestrator loop remains S-140's job.

> **Design note — `determine_outcome()`'s 3-tuple return:** spec §8.10's pseudocode describes a
> 4-tuple `(status, outcome, error_code, pr_opened)`. `audit_only` never opens a PR, so
> `pr_opened` would always be `False` here and carries no information; `determine_outcome()`
> therefore returns a 3-tuple, documented in its own docstring as a deliberate, scope-appropriate
> choice (mirroring the sibling agent's own 3-tuple `determine_outcome()`), not a spec
> non-compliance. The docstring also notes S-140 (which adds the `fix`/PR-opening branch, where
> `pr_opened` becomes meaningful) is expected to either widen the signature back to 4 elements or
> compute `pr_opened` separately at the call site — a decision deferred to that story.

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

The example above uses `mode=audit_only` (the default), which as of S-135 runs the real five-tool
scan/classify/report pipeline described under Pipeline above. `mode=fix` is also accepted by
`validate_payload()` (it is in `_VALID_MODES`), but is still unimplemented — it falls straight
through to the S-125 placeholder (`succeeded`/`no_findings`, no scanner run) until S-137-S-140
land. S-136 built the fixer modules `mode=fix` will eventually call, but they are not wired in yet.

## Deployment

```bash
cd agents/security-analyst
agentcore deploy -y      # non-interactive build + deploy
agentcore status         # confirm runtime ready; copy the runtime ARN
```

After a successful deploy, the `runtime_arn` is recorded in `supabase/seed.sql` as part of
**S-141** (this story does not touch the seed file — no `security-analyst` `agents` row exists
until then).

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

This agent recomputes ADR-006's clock-invariant chain for its own, higher bounds — a five-scanner
step (CodeQL's database-build phase especially) can legitimately run far longer than the sibling
agent's `pnpm test`. At entrypoint start `config.assert_clock_invariant()` fails fast
(`ClockConsistencyError`) unless
`FIX_COMMAND_TIMEOUT <= SCANNER_TIMEOUT <= IDLE_SESSION_TIMEOUT <= MAX_LIFETIME <= REAPER_THRESHOLD_SECONDS`
and `HEARTBEAT_INTERVAL <= IDLE_SESSION_TIMEOUT / 2`. `IDLE_SESSION_TIMEOUT` / `MAX_LIFETIME` MUST
mirror `agentcore.json` `lifecycleConfiguration`, and `REAPER_THRESHOLD_SECONDS` (default
`MAX_LIFETIME + 120`) MUST equal the database `max_runtime_seconds` + `grace_seconds` set for this
agent's row in `supabase/seed.sql` (S-141). See `docs/technical-guidelines.md` S7/S8 and
[ADR-006](../../docs/adr/ADR-006-long-step-keepalive-and-clock-invariant.md).

### Environment Variables (set by AgentCore / Secrets Manager)

| Variable | Required | Description |
|----------|----------|-------------|
| `SUPABASE_URL` | Yes | Supabase project URL |
| `SUPABASE_KEY_SECRET_ID` | Yes | Secrets Manager ID for Supabase service role key |
| `RUN_ID` | Yes | Execution ID (passed by control plane at invocation) |
| `RUN_PARAMS` | Yes | JSON payload with invocation parameters |
| `AGENT_LOG_LEVEL` | No | Minimum log level captured (default: INFO) |
| `MODEL_ID` | No | Bedrock model for the LLM fix loop, wired in a later story (default: `us.anthropic.claude-sonnet-4-6`) |
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
