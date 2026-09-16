# security-analyst Agent

Five-tool security scanner agent (semgrep, gitleaks, trivy, checkov, CodeQL) for the Agent Fleet
Control Plane. Runs as an AWS Bedrock AgentCore Container runtime.

> **Status (S-125-S-134):** project scaffold, deploy, and reporting pipe (S-125), per-tool
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
> tolerance) (S-133), and the finding classifier (`classify()`, `_is_major_bump()`,
> `_is_semver()` — the D22 three-bucket `mechanical`/`manual`/`unscannable` model, the D24/
> req-54 `dependency-update` lockfile boundary, and requirement 27's major-version guard;
> retroactively added `Remediation.current_version`, populated only by
> `trivy_runner.py`'s `version_bump` branch, so the major-bump guard has a pre-fix version to
> compare against `target_version` — see `normalize.py`'s `Remediation` docstring) (S-134). The
> entrypoint still validates the invocation payload and runs the S-125 placeholder pipeline
> (`resolve_credentials` -> `checkout` -> `succeeded`/`no_findings`) — **`main.py` does not call
> any scanner yet**.
> `scanners/semgrep_runner.py`'s `run_semgrep()`/`normalize_semgrep()`,
> `scanners/gitleaks_runner.py`'s `run_gitleaks()`/`normalize_gitleaks()`,
> `scanners/trivy_runner.py`'s `run_trivy()`/`normalize_trivy()`,
> `scanners/checkov_runner.py`'s `run_checkov()`/`normalize_checkov()`/`has_iac_files()`,
> `scanners/codeql_runner.py`'s `run_codeql()`/`normalize_codeql()`/`detect_languages()`,
> `severity.py`'s five `severity_from_<tool>()` functions, `normalize.py`'s
> `Finding`/`Remediation` dataclasses, `fingerprint.py`'s `fingerprint()`, `dedupe.py`'s
> `dedupe()`, and `classifier.py`'s `classify()` are all pure/subprocess-mocked,
> unit-and-component-tested, and not yet wired into the pipeline (no `run_scanners()`
> dispatcher, dedupe/classify step, or `main.py` caller exists until **S-135**, `audit_only`
> mode end-to-end). This is a deliberate bring-up milestone, not a shortcut: it proves the
> deploy/credential/reporting pipe end-to-end (mirroring how `agents/dependency-update/` proved
> its own pipe first) before all five scanner integrations (S-128-S-132), cross-tool dedupe
> (S-133), and classification (S-134, now complete) are wired together and invoked
> (S-135-S-141).

## Layout

```
agents/security-analyst/
├── agentcore/
│   ├── agentcore.json     # Runtime configuration (Container, HTTP, lifecycle)
│   ├── aws-targets.json   # Deployment target (us-east-1)
│   └── cdk/                # CDK infrastructure (managed by agentcore CLI)
├── app/securityAnalyst/
│   ├── main.py              # Pipeline orchestrator entrypoint (placeholder pipeline, S-125)
│   ├── severity.py          # Per-tool severity normalization, pure functions (S-126)
│   ├── normalize.py         # Finding/Remediation frozen dataclasses (S-127)
│   ├── fingerprint.py       # fingerprint(), banded-line dedup key (S-127)
│   ├── dedupe.py            # dedupe(), _merge_overlapping_by_line(), MergedFinding — cross-tool
│   │                        # merge within one scan pass (file+category+line-overlap), distinct
│   │                        # from fingerprint.py's across-scan tolerance (S-133)
│   ├── classifier.py        # classify(), _is_major_bump(), _is_semver() — D22 three-bucket
│   │                        # mechanical/manual/unscannable model, D24/req-54 lockfile
│   │                        # boundary, requirement 27 major-version guard (S-134)
│   ├── scanners/
│   │   ├── __init__.py        # Subpackage docstring: one module per tool, shared ScanStatus/ScanResult
│   │   ├── types.py           # ScanStatus/ScanResult shared shape, reused verbatim by S-129-S-132 (S-127-adjacent, landed S-128)
│   │   ├── semgrep_runner.py  # RULESET, run_semgrep(), normalize_semgrep() (S-128) — not yet called by main.py
│   │   ├── gitleaks_runner.py # run_gitleaks(), normalize_gitleaks() (S-129) — not yet called by main.py
│   │   ├── trivy_runner.py    # run_trivy() fs/config/conditional-image dispatch, normalize_trivy(),
│   │   │                      # _JS_LOCKFILES D24/req-54 boundary (S-130) — not yet called by main.py
│   │   ├── checkov_runner.py  # run_checkov(), normalize_checkov(), has_iac_files() pre-flight
│   │   │                      # skip detector (Terraform/Dockerfile/CloudFormation/Kubernetes),
│   │   │                      # unconditional structural remediation (S-131) — not yet called by main.py
│   │   └── codeql_runner.py   # run_codeql(), normalize_codeql(), detect_languages() JS/TS +
│   │                          # Python-only two-phase (database create/analyze) dispatch, merged
│   │                          # findings across languages, unconditional structural remediation
│   │                          # (S-132) — not yet called by main.py
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
│       │                    # case, EC-38)
│       ├── component/       # Component tests (mocked externals), incl.
│       │                    # test_semgrep_runner_subprocess.py (S-128, subprocess.run mocked),
│       │                    # test_gitleaks_runner.py (S-129, subprocess.run mocked),
│       │                    # test_trivy_runner.py (S-130, three-mode subprocess dispatch mocked),
│       │                    # test_checkov_runner.py (S-131, run_checkov() subprocess dispatch
│       │                    # mocked, incl. test_skip_no_iac AC-23),
│       │                    # test_codeql_runner.py (S-132, two-phase per-language subprocess
│       │                    # dispatch mocked, incl. skip path and both-languages merge)
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

## Pipeline (this story's subset)

1. Validate payload (reject with `INVALID_PARAMS` on bad input — no clone attempted)
2. Resolve credentials (Supabase service role key, GitHub App token — reuses the sibling agent's
   `credentials.py` unmodified against the shared `github_installations` row)
3. Clone repository (depth 1)
4. Report `succeeded` / `no_findings` (placeholder — no scanner ran)

Later stories replace step 4 with the real `scan -> classify -> fix -> rescan -> open_pr` pipeline
(spec `workstream/specification-prd-security-analyst-agent.md` S8.8).

There are two related but distinct "not yet wired" categories below: the five **scanner
runners** (no `run_scanners()` dispatcher exists yet to call them) and the **dedupe + classify**
post-scan steps (no caller exists yet because they consume `run_scanners()`'s output, which does
not exist yet either). Both land together in **S-135**, but they are separate gaps for separate
reasons — a scanner runner producing zero findings is not the same condition as dedupe/classify
having no input to run against.

> **Note (S-128/S-129/S-130/S-131/S-132) — scanner runners not yet wired:**
> `scanners/semgrep_runner.py`'s `run_semgrep()`, `scanners/gitleaks_runner.py`'s
> `run_gitleaks()`, `scanners/trivy_runner.py`'s `run_trivy()`, `scanners/checkov_runner.py`'s
> `run_checkov()`, and `scanners/codeql_runner.py`'s `run_codeql()` are all fully implemented and
> covered by unit and component tests (with `subprocess.run` mocked — no real Semgrep, Gitleaks,
> Trivy, Checkov, or CodeQL binary invocation is exercised in tests, though CodeQL's real CLI is
> now installed in the Dockerfile, see Layout above), but **step 4 above still runs unmodified**:
> `main.py` does not import or call any runner. The scan step's real wiring (`run_scanners()`
> dispatching across all requested tools) lands in **S-135** (`audit_only` mode end-to-end).
>
> **Note (S-133/S-134) — dedupe + classify not yet wired:** `dedupe.py`'s `dedupe()` and
> `classifier.py`'s `classify()` are not scanners — they are pure, unit-tested post-scan steps
> that consume a scanner run's combined `Finding` list (`dedupe()`) and a deduped
> `MergedFinding` (`classify()`) respectively. Both are fully implemented and covered by unit
> tests, but neither is wired into the pipeline: no caller invokes either yet, since
> `run_scanners()` — the step that would produce their input — does not exist until S-135. Their
> real wiring (`run_scanners()`'s output -> `dedupe()` -> `classify()` per finding) lands
> alongside the rest of the `scan -> classify -> fix -> rescan -> open_pr` pipeline in **S-135**
> and following.

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
