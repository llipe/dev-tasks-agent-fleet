# Fidelity Report — Issues #108 + #109

## Header / Verdict

- **Overall fidelity:** **High**
- **Highest drift impact present:** **Minor**
- **Scope:** issues #108 + #109 · branch `issue/108-classify-secrets-manager-failures` · PR #178 (draft) · repo `llipe/dev-tasks-agent-fleet`
- **Mode:** Audit (grey-box)
- **Drift is non-blocking** to PR/issue completion. Any drift routes to `product-engineer`'s `activity-drift-reconciliation` flow — never applied here.

---

## Human-readable summary (what changed and why)

When the agent starts a run it has to read two secrets out of AWS Secrets Manager:
the Supabase service-role key and the GitHub App private key (PEM). Before this
change, if Secrets Manager refused or failed — the secret is missing, access is
denied, the service is throttling, or the secret has no text value — the error
came out as an unlabeled crash with a raw stack trace. To an operator that looked
like an internal bug ("UNHANDLED_ERROR") rather than what it actually was: the
agent couldn't get the credentials it needed to start.

This change teaches those two secret-reads to recognize a Secrets Manager failure
and re-label it as a proper, named credential error — `SUPABASE_KEY_UNAVAILABLE`
for the Supabase key, `PEM_UNAVAILABLE` for the GitHub key. Because the agent's
main handler already knows how to catch labeled credential errors and finish the
run cleanly with that label, a failed secret-read now ends as a tidy, classified
failure instead of a confusing crash. The error message names *which* secret
failed for troubleshooting but never includes the secret's value. Normal success
is untouched.

This is the natural finish of the earlier network-error work (#106): #106 handled
"can't reach Supabase/GitHub over the network," and #108 handles "can't read the
secrets from AWS." The companion piece (#109) is test-only hardening — it adds
explicit tests proving that a *timeout* (not just a dropped connection) reaching
Supabase or GitHub is also relabeled correctly; that behavior already worked, so
no product code changed for the #109 half. New tests also cover the GitHub-key
read for the first time (it previously had none). The full agent gate passes with
the credentials module now at 100% coverage.

---

## Per-AC result table

| AC-ID | Description | Codebase evidence | Workstream / intent evidence | Test evidence | Result |
|-------|-------------|-------------------|------------------------------|---------------|--------|
| **#108 AC1** | `fetch_supabase_key` raises classified `CredentialError` on `ClientError` / missing `SecretString`; unchanged on success | `credentials.py` `fetch_supabase_key`: `get_secret_value` wrapped in `try/except ClientError` → `raise CredentialError("SUPABASE_KEY_UNAVAILABLE", …) from exc`; `key = response.get("SecretString")` + `if not key:` → same classified code. Success path still `return key` | Mirrors the #106 `requests` treatment; #106 report Recommendation row 2 asked for exactly this | `test_client_error_raises_credential_error` (code, and `not isinstance ClientError`), `test_missing_secret_string_raises_credential_error`, `test_reads_from_secrets_manager` / `test_uses_default_secret_id` still green | **Pass** |
| **#108 AC2** | `_fetch_pem` same | `credentials.py` `_fetch_pem`: identical `try/except ClientError` → `PEM_UNAVAILABLE`; `pem = response.get("SecretString")` + `if not pem:` → same code; success path `return pem` | Consistent-by-design with AC1 (comment cross-references `fetch_supabase_key`) | `TestFetchPem.test_client_error_raises_credential_error`, `test_missing_secret_string_raises_credential_error` | **Pass** |
| **#108 AC3** | New tests cover both failure paths + `_fetch_pem` happy path; existing tests still pass | New `TestFetchPem` class (happy + both failures) closes the prior zero-coverage gap; `TestFetchSupabaseKey` gains two failure tests | Task 1.6 / #106 report noted `_fetch_pem` had zero coverage | New `TestFetchPem.test_reads_pem_from_secrets_manager` (happy path); focused suite reported 22 passed | **Pass** |
| **#108 AC4** | `make validate` passes | — | Agent gate (ruff lint + ruff format-check + mypy + pytest-cov + pip-audit --strict) | User-supplied evidence: `make validate` exit 0 — **460 passed**, `credentials.py` **100%** coverage (up from ~95%), all gates green. Not re-executed in this audit | **Pass (evidence-backed)** |
| **#109 AC1** | Both requests functions re-classify a non-`ConnectionError` `RequestException` subclass to the correct code | No production change needed — pre-existing `except requests.RequestException` (base class) in `_get_installation` and `mint_installation_token` already catches `Timeout` | #106 report Recommendation row 3 / Edge-case note: `Timeout` covered transitively but not asserted | `TestGetInstallation.test_non_connection_request_exception_is_classified` (`Timeout` → `SUPABASE_UNREACHABLE`), `TestMintInstallationToken.test_non_connection_request_exception_is_classified` (`Timeout` → `GITHUB_UNREACHABLE`) | **Pass** |
| **#109 AC2** | NO production-code change for the #109 half | `git diff main...HEAD -- credentials.py` shows **only** the #108 boto3 handling (the `botocore` import + two `try/except ClientError` blocks + two missing-`SecretString` guards). The `requests`/`Timeout` paths are untouched | The `Timeout` tests pass against the pre-existing base-class `except` | Confirmed by diff inspection; the two `Timeout` tests are additive | **Pass** |
| **#109 AC3** | `make validate` passes | — | Same gate as #108 AC4 (one branch, one PR closing both issues) | User-supplied evidence: `make validate` exit 0 — 460 passed | **Pass (evidence-backed)** |

**Intent verification — confirmed end-to-end.** `main.py` L886 `except CredentialError as exc:` logs the error and yields `build_return_payload("failed", "not_applicable", exc.code)` as a terminal chunk, *ordered before* the generic `except Exception → UNHANDLED_ERROR` at L909. So the new `SUPABASE_KEY_UNAVAILABLE` / `PEM_UNAVAILABLE` codes surface as clean classified terminal chunks — the exact behavior #108 intended, matching how #106's `SUPABASE_UNREACHABLE` / `GITHUB_UNREACHABLE` already flow.

**AC coverage status:** #108 AC1–AC4 + #109 AC1–AC3 — all **covered / Pass**.

---

## Drift catalog

All drift is **non-blocking** to completion and routes to `product-engineer`'s `activity-drift-reconciliation` flow (never applied here).

| ID | Description | Impact | Intent | Evidence source(s) |
|----|-------------|--------|--------|--------------------|
| **D1** | New classified codes `SUPABASE_KEY_UNAVAILABLE` / `PEM_UNAVAILABLE` are introduced in code + tests but are not recorded in any spec/technical-guidelines credential-error-code catalog (technical-guidelines §5/§13 names `CREDENTIALS_UNAVAILABLE`/`INVOCATION_FAILED` for the *panel*, and the reaper codes elsewhere, but no agent-side `*_UNAVAILABLE` list exists to update). Same latent doc-gap as #106's `SUPABASE_UNREACHABLE`/`GITHUB_UNREACHABLE`, which were also never cataloged. | **Minor** | **Intended** | `credentials.py`; grep of technical-guidelines shows no agent credential-code table |
| **D2** | Missing/empty `SecretString` handling uses `response.get("SecretString")` + `if not key:` — a `SecretString` of `""` (empty string) is treated as unavailable and classified, not returned. This is a (correct, defensive) behavior refinement beyond the literal AC wording ("on `ClientError` / missing `SecretString`"); an empty-but-present value is arguably neither. Tests exercise the `SecretBinary`-only case, not the explicit `""` case. | **Minor** | **Intended** | `credentials.py` `if not key:` / `if not pem:`; tests use `{"SecretBinary": b"\x00"}` |

Neither item is a defect against the delivered ACs; both are documentation / test-completeness observations.

---

## Edge-case & randomized test outcomes

No Design-Mode test plan exists for this scope, so no pre-planned edge-case matrix was executed. Observations from reading the delivered tests:

- `from exc` chaining is present on both new boto3 handlers, preserving the original `ClientError` cause for debugging without surfacing the raw type.
- The no-leak posture is asserted: `test_error_message_does_not_leak_secret` checks the secret *id* is present for context and (by construction) the `SecretString` value never enters the message — the failure branches interpolate only `sid`/`secret_arn` and `str(exc)`, never the secret value.
- A single representative `ClientError` (`ResourceNotFoundException`) is used deliberately — the handler does not branch on the error code, so access-denied / throttling collapse to the same path. Reasonable coverage choice, documented in the `_client_error()` helper.
- Missing-`SecretString` is exercised via a `SecretBinary`-only response (realistic for a binary secret). An explicit empty-string (`""`) case is not separately asserted (see drift D2).
- `Timeout` (the #109 addition) re-attaches the real `requests.Timeout` + `requests.RequestException` onto the mocked module so the base-class `except` binds — the correct pattern, matching #106's approach.

---

## Recommendations

| Item | Recommendation |
|------|----------------|
| Delivered change vs. ACs and intent | **No action needed** — all 7 ACs Pass; fidelity is High. |
| D1 — new credential codes uncataloged | Route to `product-engineer`: consider whether the agent-side credential-error codes (`SUPABASE_UNREACHABLE`, `GITHUB_UNREACHABLE`, `NO_INSTALLATION`, `SUPABASE_KEY_UNAVAILABLE`, `PEM_UNAVAILABLE`) warrant a small catalog in the spec/technical-guidelines. Documentation-only; not a code defect. |
| D2 — empty-string `SecretString` | Optional test hardening for `developer`/`qa-engineer`: add an explicit `{"SecretString": ""}` case to make the "empty is unavailable" behavior a documented, asserted contract rather than an implicit consequence of `if not key:`. Non-blocking. |
| #109 AC2 (no-production-change) | Confirmed by diff — the "tests-only" contract held; no drift. |

---

## Output Contract

- **Mode / phase:** Audit / Phase 4 (Reporting & Publication)
- **Source artifact:** `workstream/tasks-issue-108-109-credential-classification.md` + issues #108/#109 ACs (as supplied) + delivered diff on branch `issue/108-classify-secrets-manager-failures`
- **Files created:** `workstream/fidelity-report-108-109.md`
- **GitHub target:** PR #178 / issues #108 + #109 (post header + human-readable summary)
- **AC coverage status:** #108 AC1–AC4, #109 AC1–AC3 — all **covered / Pass**
- **Overall fidelity verdict:** High · **Highest drift impact:** Minor (D1, D2 — both Intended, non-blocking)
- **Blocking gaps:** none
