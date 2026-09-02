# Fidelity Report — Issue #106

## Header / Verdict

- **Overall fidelity:** **High**
- **Highest drift impact present:** **None**
- **Scope:** issue #106 · branch `issue/106-classify-credential-transport-failures` · PR #107 (draft) · repo `llipe/dev-tasks-agent-fleet`
- **Mode:** Audit (grey-box)
- **Drift is non-blocking** to PR/issue completion. Any drift routes to `product-engineer`'s `activity-drift-reconciliation` flow — never applied here.

---

## Human-readable summary (what changed and why)

When the agent tried to look up its GitHub installation or mint a token, and the
network couldn't reach the service (bad DNS, dropped connection, timeout), the
error came out as an unlabeled crash with a raw stack trace. To the operator that
looked like an internal bug ("UNHANDLED_ERROR") rather than what it actually was —
a failure to reach an external service while resolving credentials.

This change teaches those two lookup steps to recognize a network/transport
failure and re-label it as a proper credential error with a clear code
(`SUPABASE_UNREACHABLE` when Supabase can't be reached, `GITHUB_UNREACHABLE` when
GitHub can't be reached). Because the agent's main handler already knows how to
catch labeled credential errors and finish the run cleanly with that label, the
run now ends as a tidy, classified failure instead of a confusing crash. Normal
success and the existing "no installation configured" case are untouched. Two new
tests confirm the relabeling happens for both lookup steps, and all existing
credential tests still pass.

---

## Per-AC result table

| AC-ID | Description | Codebase evidence | Workstream / intent evidence | Test evidence | Result |
|-------|-------------|-------------------|------------------------------|---------------|--------|
| AC-1 | `_get_installation` raises `CredentialError` (classified) on `requests.RequestException`; unchanged on success and empty-result (`NO_INSTALLATION`) | `credentials.py` `_get_installation`: `requests.get` wrapped in `try/except requests.RequestException` → `raise CredentialError("SUPABASE_UNREACHABLE", ...) from exc`. `resp.raise_for_status()` and the `if not rows → NO_INSTALLATION` path are outside/after the try, unchanged | Matches Reading B — transport failure classified as credential-resolution failure | `test_transport_failure_raises_credential_error` (code `SUPABASE_UNREACHABLE`, not `requests.RequestException`); `test_returns_first_row`, `test_raises_no_installation_when_empty` still pass | **Pass** |
| AC-2 | `mint_installation_token` raises `CredentialError` on `requests.RequestException` | `credentials.py` `mint_installation_token`: `requests.post` wrapped in same pattern → `raise CredentialError("GITHUB_UNREACHABLE", ...) from exc`; `raise_for_status()` unchanged | Consistent with AC-1 by design (comment cross-references) | `test_transport_failure_raises_credential_error` (code `GITHUB_UNREACHABLE`); `test_happy_path` still passes | **Pass** |
| AC-3 | New unit tests cover both transport-failure paths and pass; existing credential tests still pass | `tests/unit/test_credentials.py` adds two transport-failure tests, preserving real `requests` exception classes on the mock so `except requests.RequestException` binds correctly | — | `pytest tests/unit/test_credentials.py` → **14 passed** (2 new + 12 pre-existing) | **Pass** |
| AC-4 | Full agent suite + quality gates (lint, format:check/ruff, typecheck/mypy, test, audit) pass | — | `make validate` evidence supplied: 436 passed; ruff lint, ruff format --check, mypy, pip-audit --strict green; `credentials.py` 95% coverage. qa-engineer `coverage_gate: PASS` | Re-ran `tests/unit/test_credentials.py` locally: 14 passed. Full-suite/gate result relied on provided evidence (not re-executed in this audit) | **Pass (evidence-backed)** |

**Intent verification (Reading B) — confirmed end-to-end.** `main.py` opens the
guarded `try:` at line ~501; the `resolve_credentials` step calls
`resolve_github_credentials(org)` (→ `_get_installation` → `mint_installation_token`)
at line ~552, inside that try. The `except CredentialError as exc:` handler (line ~886)
logs the error and yields `build_return_payload("failed", "not_applicable", exc.code)`
as a terminal chunk — ordered *before* the generic `except Exception → UNHANDLED_ERROR`
branch (line ~911). So a classified `SUPABASE_UNREACHABLE`/`GITHUB_UNREACHABLE` now
surfaces as a clean terminal chunk carrying that code, exactly as the issue intended.

---

## Drift catalog

No drift detected. Delivered behavior matches every AC and the stated intent. Nothing to route to drift-reconciliation.

*(Drift, if present, would be non-blocking to completion.)*

---

## Edge-case & randomized test outcomes

No Design-Mode test plan exists for this scope, so no pre-planned edge-case matrix
was executed. Observations from reading the delivered tests:

- The transport-failure tests re-attach real `requests.RequestException` /
  `ConnectionError` onto the mocked `requests` module — necessary and correct, since
  the code binds `except requests.RequestException` against the mocked module.
- `from exc` chaining is present in both handlers, preserving the original cause for
  debugging without leaking the raw type as the surfaced exception.
- Only `ConnectionError` (a `RequestException` subclass) is exercised directly;
  `Timeout` and other `RequestException` subclasses are covered transitively by the
  base-class `except`, but not asserted individually. Non-blocking observation, not drift.

---

## Recommendations

| Item | Recommendation |
|------|----------------|
| Delivered change vs. ACs and intent | **No action needed** — fidelity is High, no drift. |
| Boto3 Secrets Manager paths (`_fetch_pem`, `fetch_supabase_key`) carry the same unclassified-exception risk | Out of scope for #106 (flagged by qa-engineer). Suggest a **follow-up issue** for `product-engineer` to weigh — not a defect in this deliverable. |
| `Timeout`/other `RequestException` subclasses not individually asserted | Optional test hardening for `developer`; base-class `except` already covers behavior. Non-blocking. |

---

## Output Contract

- **Mode / phase:** Audit / Phase 4 (Reporting & Publication)
- **Source artifact:** issue #106 body (ACs verbatim) + delivered diff on branch `issue/106-classify-credential-transport-failures`
- **Files created:** `workstream/fidelity-report-106.md`
- **GitHub target:** PR #107 / issue #106 (post header + human-readable summary)
- **AC coverage status:** AC-1..AC-4 all **covered / Pass**
- **Overall fidelity verdict:** High · **Highest drift impact:** None
- **Blocking gaps:** none
