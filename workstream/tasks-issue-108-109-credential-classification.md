# Implementation Plan — Issues #108 + #109 (agent credential-failure classification)

> **Mode:** Issue Mode (two tightly-coupled issues planned together).
> **Source:** [#108](https://github.com/llipe/dev-tasks-agent-fleet/issues/108) (code + tests),
> [#109](https://github.com/llipe/dev-tasks-agent-fleet/issues/109) (tests only) — both follow-ups to
> #106 (PR #107), surfaced by the verifier audit `workstream/archive/fidelity-report-106.md`
> (Recommendations rows 2 and 3).

## Why one plan / one PR

#108 and #109 touch the **same two files** (`agents/dependency-update/app/dependencyUpdate/credentials.py`
and `.../tests/unit/test_credentials.py`) and are both direct descendants of #106's audit
recommendations. Splitting them into two PRs would churn the same test file twice and split one
coherent "harden credential-error classification" story. They are planned as one branch / one PR that
**closes both issues**. #108 is the code+test half (boto3 Secrets Manager paths); #109 is additive
test hardening (non-`ConnectionError` `RequestException` subclasses) with **no production change
expected** — if #109 turns out to need a production change, that is itself a finding to report (its AC2).

## Language / toolchain (Python agent — NOT the pnpm panel)

The `dependency-update` agent is a Python package with its **own** gate. Commands below use the agent
package's canonical targets, run from `agents/dependency-update/app/dependencyUpdate/`:

- `make validate` — aggregate gate: `lint` (ruff) + `format-check` (ruff) + `typecheck` (mypy) + `test-cov` (pytest --cov) + `audit` (pip-audit --strict)
- `python -m pytest tests/unit/test_credentials.py` — the focused suite
- `python -m pytest -m unit` — Layer 1

`botocore` ships with `boto3` (already a runtime dependency), so classifying `botocore.exceptions.ClientError`
adds **no new dependency**.

## Current state (verified 2026-09-11)

- `credentials.py` `fetch_supabase_key` (≈L46-50) and `_fetch_pem` (≈L104-108) call
  `boto3.client("secretsmanager").get_secret_value(...)` and index `response["SecretString"]` with
  **no exception handling** — a `ClientError` or a missing `SecretString` key raises raw, bypassing
  the entrypoint's `except CredentialError` and landing in `except Exception → UNHANDLED_ERROR`.
- The `requests` paths (`_get_installation`, `mint_installation_token`) **already** classify
  `requests.RequestException` → `SUPABASE_UNREACHABLE` / `GITHUB_UNREACHABLE` (the #106 fix).
- `test_credentials.py` has `TestFetchSupabaseKey` (happy paths only) and **no `TestFetchPem` class at
  all** — `_fetch_pem` has zero coverage today (confirmed in the #108 body and the #106 report).
- `main.py` already catches `CredentialError` before the generic handler and yields
  `build_return_payload("failed", "not_applicable", exc.code)` — so a new classified code surfaces as a
  clean terminal chunk with no entrypoint change needed.
- The mocked-`requests` test pattern re-attaches real exception classes onto the mock
  (`mock_requests.RequestException = requests.RequestException`) so `except requests.RequestException`
  binds correctly — the #109 tests must follow this same pattern with `requests.Timeout`.

## Migration

**Documented opt-out — N/A.** No schema, data-model, or migration change. Pure agent code + tests.

## Relevant Files

- `agents/dependency-update/app/dependencyUpdate/credentials.py` — add `botocore.exceptions.ClientError` handling to `fetch_supabase_key` and `_fetch_pem`; new classified codes `SUPABASE_KEY_UNAVAILABLE` / `PEM_UNAVAILABLE`. **No change to vendored `agent_reporter.py` (D13).**
- `agents/dependency-update/app/dependencyUpdate/tests/unit/test_credentials.py` — add boto3 failure-path tests (#108) + `_fetch_pem` happy-path (#108) + non-`ConnectionError` `RequestException` assertions (#109).

## Tasks

- [x] 1.0 Implement Issue #108 - https://github.com/llipe/dev-tasks-agent-fleet/issues/108: classify Secrets Manager failures as CredentialError

  > Note: mirror the #106 `requests` treatment for the boto3 Secrets Manager reads. New codes: `SUPABASE_KEY_UNAVAILABLE` (fetch_supabase_key), `PEM_UNAVAILABLE` (_fetch_pem). `from exc` chaining preserved; the surfaced exception is `CredentialError`, not a raw boto3 type.

  - [x] 1.1 Add `from botocore.exceptions import ClientError` to `credentials.py` (confirm no new dependency — botocore ships with boto3; `pip-audit --strict` stays green).
  - [x] 1.2 Wrap `fetch_supabase_key`'s `get_secret_value` in `try/except ClientError` → `raise CredentialError("SUPABASE_KEY_UNAVAILABLE", ...) from exc`; also raise the same classified error when `SecretString` is missing/empty (`response.get("SecretString")` falsy). Success path unchanged (still returns the key string).
  - [x] 1.3 Wrap `_fetch_pem`'s `get_secret_value` identically → `raise CredentialError("PEM_UNAVAILABLE", ...) from exc`; missing/empty `SecretString` → same classified error. Success path unchanged.
  - [x] 1.4 Confirm the classified error message names the failing secret context (secret id / arn label) **without** leaking secret values, consistent with the credential-scrubbing posture (the message carries the code + a human hint, never the `SecretString`).
  - [x] 1.5 Write unit tests — `TestFetchSupabaseKey`: add `ClientError` → `SUPABASE_KEY_UNAVAILABLE` and missing-`SecretString` → `SUPABASE_KEY_UNAVAILABLE`; assert the surfaced type is `CredentialError`, not `ClientError`. Mock pattern: `@patch("credentials.boto3")`, set `mock_client.get_secret_value.side_effect = ClientError({...}, "GetSecretValue")`.
  - [x] 1.6 Write unit tests — **new** `TestFetchPem` class: happy path (returns the PEM string — closes the zero-coverage gap), `ClientError` → `PEM_UNAVAILABLE`, missing-`SecretString` → `PEM_UNAVAILABLE`.
  - [x] 1.x Verify Acceptance Criterion (#108 AC1): `fetch_supabase_key` raises classified `CredentialError` on `ClientError` / missing `SecretString`; unchanged on success — via the new `TestFetchSupabaseKey` cases + existing happy-path tests still green.
  - [x] 1.y Verify Acceptance Criterion (#108 AC2): `_fetch_pem` raises classified `CredentialError` on `ClientError` / missing `SecretString`; unchanged on success — via the new `TestFetchPem` cases.
  - [x] 1.z Verify Acceptance Criterion (#108 AC3): new tests cover both failure paths + the `_fetch_pem` happy path; existing credential tests still pass — `python -m pytest tests/unit/test_credentials.py`.
  - [x] 1.aa Verify Acceptance Criterion (#108 AC4): full agent gate `make validate` (lint, format:check, typecheck, test, audit) passes.
  - [x] 1.bb Run Tests: `python -m pytest tests/unit/test_credentials.py` (focused) then `make validate` (full gate); confirm `credentials.py` coverage did not regress (was ~95% under #106; `_fetch_pem` now covered). → 22 focused / 460 full passed; `credentials.py` 100% coverage.

- [x] 2.0 Implement Issue #109 - https://github.com/llipe/dev-tasks-agent-fleet/issues/109: assert non-ConnectionError RequestException classification

  > Note: purely additive test hardening. The #106 fix already catches the `requests.RequestException` base class, so `Timeout` etc. are handled transitively — this asserts it explicitly for both `requests` functions. NO production-code change expected (AC2: if one is needed, report it as a finding rather than silently making it).

  - [x] 2.1 Add to `TestGetInstallation`: a `requests.Timeout` (a non-`ConnectionError` `RequestException` subclass) side-effect on `requests.get` → assert `CredentialError` with code `SUPABASE_UNREACHABLE`. Re-attach real exception classes on the mock (`mock_requests.RequestException = requests.RequestException`, `mock_requests.Timeout = requests.Timeout`) so the base-class `except` binds.
  - [x] 2.2 Add to `TestMintInstallationToken`: a `requests.Timeout` side-effect on `requests.post` → assert `CredentialError` with code `GITHUB_UNREACHABLE`, same mock pattern.
  - [x] 2.3 Confirm no production change was required (AC2). The base-class `except requests.RequestException` catches `Timeout` as expected — the two new tests pass against the pre-existing handler; no `credentials.py` edit made under the #109 label.
  - [x] 2.x Verify Acceptance Criterion (#109 AC1): both functions re-classify a non-`ConnectionError` `RequestException` subclass to `CredentialError` with the correct code — via the two new assertions.
  - [x] 2.y Verify Acceptance Criterion (#109 AC2): no production-code change made (git diff shows `credentials.py` changes are entirely the #108 boto3 handling; the #109 half is test-only).
  - [x] 2.z Run Tests: `python -m pytest tests/unit/test_credentials.py` then `make validate` — AC3. → green.

- [ ] 3.0 Close-out (both issues)

  - [x] 3.1 Edge-case matrix confirmed covered: `ClientError` (missing secret / access denied / throttling — one representative `ClientError` is sufficient, the handler does not branch on the error code), missing-`SecretString`, `Timeout` on each `requests` path, happy paths for all four functions.
  - [x] 3.2 Acceptance-criteria → test mapping recorded in the PR body (each of #108 AC1-4 and #109 AC1-3 → its test / gate evidence).
  - [x] 3.3 `make validate` green; record the pytest pass count + `credentials.py` coverage in the PR. → 460 passed, `credentials.py` 100%.
  - [x] 3.4 PR (draft → ready) with `--body-file`, `Closes #108` and `Closes #109`; targets `main` (user review + merge). Branch `issue/108-classify-secrets-manager-failures`. → Draft PR #178 opened; converted to ready after gates below.
  - [ ] 3.5 After merge: confirm both #108 and #109 are closed.

## Definition of Done

- [ ] Code implemented per technical guidelines (Python agent conventions; no `agent_reporter.py` change)
- [ ] Unit tests written and passing (boto3 failure paths, `_fetch_pem` happy path, `Timeout` on both requests paths)
- [ ] Quality gates passing (`make validate`: lint, format-check, typecheck, test-cov, audit)
- [ ] Acceptance criteria verified and mapped to test evidence (#108 AC1-4, #109 AC1-3)
- [ ] Migration lifecycle — N/A, documented opt-out (no schema/data change)
- [ ] `qa-engineer` pass + `coverage_gate` recorded
- [ ] `verifier` audit (audit mode) run + summary posted to the PR
- [ ] PR reviewed, approved, and merged by the user; then both issues closed
