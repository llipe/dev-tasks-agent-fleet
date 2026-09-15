"""
Unit tests for Semgrep normalization (spec §8.5, PRD requirement 52, story
S-128 AC1-AC2).

Covers:
  - ``normalize_semgrep()`` against the fixture corpus (clean + findings),
    including the autofix-patch-present vs. absent vs. malformed-empty cases
    (story S-128 acceptance criteria, edge-case matrix).
  - ``RULESET``'s exact pinned-ruleset scope (PRD requirement 52 -- never
    ``--config auto``).
  - Severity delegation to ``severity.severity_from_semgrep()`` (D28) --
    not reimplemented here.

Deviation from spec §8.6's literal ``apply_semgrep_autofix`` pseudocode
(``["semgrep", "--autofix", "--config", RULESET, str(workspace)]``, which
treats ``RULESET`` as a single space-joined string passed as ONE ``--config``
argument value): that is not valid Semgrep CLI syntax -- ``--config`` takes
exactly one registry id/path per flag. ``RULESET`` here is a tuple of the
four individual registry ids, and ``_build_command()`` (tested via
``test_semgrep_runner_subprocess.py``) emits one ``--config <id>`` pair per
entry. Flagged as the same class of literal spec-pseudocode defect the
S-126/S-127 fidelity audits caught in ``severity.py`` (dict-indexing
``KeyError``) -- fixed here, not replicated, per this story's pre-authorized
"apply proactively" instruction.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from normalize import Finding, Remediation
from scanners.semgrep_runner import RULESET, TOOL_NAME, normalize_semgrep
from severity import Severity

_FIXTURES = Path(__file__).parent.parent / "fixtures"


def _load_fixture(name: str) -> str:
    return (_FIXTURES / name).read_text()


# ---------------------------------------------------------------------------
# RULESET -- PRD requirement 52, pinned scope only, no `--config auto`.
# ---------------------------------------------------------------------------


class TestRuleset:
    def test_ruleset_is_the_four_pinned_registry_ids(self):
        assert RULESET == ("p/javascript", "p/typescript", "p/python", "p/security-audit")

    def test_ruleset_never_contains_auto(self):
        # PRD requirement 52 -- `--config auto` is an always-latest, unpinned
        # alias that would make scan results non-reproducible run-to-run.
        assert "auto" not in RULESET

    def test_ruleset_is_a_tuple_not_a_single_joined_string(self):
        # Each entry becomes its own `--config <id>` CLI flag -- a single
        # space-joined string would not be valid Semgrep CLI syntax.
        assert isinstance(RULESET, tuple)
        assert all(isinstance(entry, str) and " " not in entry for entry in RULESET)

    def test_tool_name_is_semgrep(self):
        assert TOOL_NAME == "semgrep"


# ---------------------------------------------------------------------------
# normalize_semgrep() -- clean fixture
# ---------------------------------------------------------------------------


class TestNormalizeSemgrepCleanFixture:
    def test_clean_fixture_normalizes_to_no_findings(self):
        raw_output = _load_fixture("semgrep_clean.json")
        findings = normalize_semgrep(raw_output)
        assert findings == []


# ---------------------------------------------------------------------------
# normalize_semgrep() -- findings fixture
# ---------------------------------------------------------------------------


class TestNormalizeSemgrepFindingsFixture:
    @pytest.fixture
    def findings(self) -> list[Finding]:
        raw_output = _load_fixture("semgrep_findings.json")
        return normalize_semgrep(raw_output)

    def test_normalizes_every_result_into_a_finding(self, findings):
        assert len(findings) == 4
        assert all(isinstance(f, Finding) for f in findings)

    def test_every_finding_carries_the_semgrep_tool_name(self, findings):
        assert all(f.tool == "semgrep" for f in findings)

    def test_rule_id_taken_from_check_id(self, findings):
        assert findings[0].rule_id == "python.lang.security.audit.eval-detected"
        assert findings[1].rule_id == "javascript.lang.security.detect-child-process"

    def test_file_path_and_line_range_taken_from_path_and_start_end(self, findings):
        assert findings[0].file_path == "app/main.py"
        assert findings[0].line_start == 10
        assert findings[0].line_end == 10

    def test_message_taken_from_extra_message(self, findings):
        assert findings[0].message == (
            "Detected use of eval(). This can lead to arbitrary code execution."
        )

    def test_severity_delegates_to_severity_from_semgrep(self, findings):
        # ERROR -> HIGH, WARNING -> MEDIUM, INFO -> LOW (D28, severity.py,
        # not reimplemented here).
        assert findings[0].severity is Severity.HIGH  # ERROR
        assert findings[1].severity is Severity.MEDIUM  # WARNING
        assert findings[2].severity is Severity.LOW  # INFO

    def test_out_of_table_native_severity_falls_to_the_shared_floor(self, findings):
        # `severity_from_semgrep` is total (RT-4) -- an out-of-table raw
        # value (here "UNSCORED") falls to the shared unknown-severity floor
        # rather than raising, exercised end-to-end through normalize here.
        assert findings[3].severity is Severity.MEDIUM

    def test_native_autofix_patch_present_sets_remediation_kind_semgrep_autofix(self, findings):
        remediation = findings[0].remediation
        assert remediation is not None
        assert isinstance(remediation, Remediation)
        assert remediation.kind == "semgrep_autofix"
        assert remediation.patch == "ast.literal_eval(user_input)"
        assert remediation.target_version is None
        assert remediation.lockfile_managed is False

    def test_no_native_fix_field_leaves_remediation_none(self, findings):
        # Finding 1 (javascript.lang.security.detect-child-process) has no
        # `extra.fix` key at all.
        assert findings[1].remediation is None

    def test_malformed_empty_fix_string_leaves_remediation_none(self, findings):
        # Finding 2 (hardcoded-tmp-path) has `extra.fix = ""` -- an empty
        # string is not a usable native patch, so it must not be treated as
        # one (edge-case matrix: "autofix patch present but malformed").
        assert findings[2].remediation is None

    def test_cwe_extracted_from_metadata_cwe_list(self, findings):
        assert findings[0].cwe_or_category == "CWE-95"

    def test_cwe_extracted_from_metadata_cwe_string(self, findings):
        assert findings[1].cwe_or_category == "CWE-78"

    def test_falls_back_to_owasp_category_when_no_cwe_present(self, findings):
        assert findings[2].cwe_or_category == "A01:2021 - Broken Access Control"

    def test_falls_back_to_rule_id_when_no_metadata_present(self, findings):
        assert findings[3].cwe_or_category == "generic.secrets.unscored-check"

    def test_raw_ref_points_into_the_raw_output_by_index(self, findings):
        assert findings[0].raw_ref == "semgrep#0"
        assert findings[3].raw_ref == "semgrep#3"


# ---------------------------------------------------------------------------
# normalize_semgrep() -- unparseable input (PRD requirement 18)
# ---------------------------------------------------------------------------


class TestNormalizeSemgrepUnparseableInput:
    def test_invalid_json_raises_json_decode_error(self):
        with pytest.raises(json.JSONDecodeError):
            normalize_semgrep("not valid json{{{")

    def test_missing_results_key_raises_key_error(self):
        with pytest.raises(KeyError):
            normalize_semgrep(json.dumps({"errors": [], "paths": {}}))
