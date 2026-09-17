"""
Unit tests for Gitleaks normalization (spec S8.5, PRD requirements 58 row 2
/ D29, story S-129 AC-12a groundwork + AC-27 message-construction half).

Covers:
  - ``normalize_gitleaks()`` against the fixture corpus (clean + findings).
  - Severity delegation to ``severity.severity_from_gitleaks()`` (D29) --
    always ``CRITICAL``, unconditionally, not reimplemented here.
  - ``remediation`` is always ``None`` (Gitleaks has no native mechanical
    fix path -- PRD spec S8.1a / this story's task 5.2).
  - AC-27's message-construction half: ``Finding.message`` never carries the
    raw ``Secret``/``Match`` value, for every leak in the fixture, including
    the multiple-occurrence case (fixture rows 0/1 share one secret value
    across two files) and the adversarial case where a (hypothetical, future,
    or malicious) rule's own ``Description`` field echoes the matched secret
    text (fixture row 2) -- the defense-in-depth redaction pass must still
    catch that, not just the "never interpolate Secret/Match" construction
    discipline.

See ``test_gitleaks_redaction.py`` for the cross-surface AC-27 sweep (every
reporting surface this module can produce: ``Finding.message``, ``reason``
strings, and anything that would be logged).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from normalize import Finding
from scanners.gitleaks_runner import TOOL_NAME, normalize_gitleaks
from severity import Severity

_FIXTURES = Path(__file__).parent.parent / "fixtures"

# The literal fake token value baked into gitleaks_findings.json /
# gitleaks_fixture_repo/config/settings.py -- an obviously-fake, clearly
# labeled test token, never a real credential (per this story's fixture
# safety instruction).
DUMMY_SECRET = "FIXTURE_DUMMY_SECRET_DO_NOT_USE_9f8e7d6c5b4a3210"


def _load_fixture(name: str) -> str:
    return (_FIXTURES / name).read_text()


# ---------------------------------------------------------------------------
# normalize_gitleaks() -- clean fixture
# ---------------------------------------------------------------------------


class TestNormalizeGitleaksCleanFixture:
    def test_empty_array_normalizes_to_no_findings(self):
        raw_output = _load_fixture("gitleaks_clean.json")
        findings = normalize_gitleaks(raw_output)
        assert findings == []

    def test_null_report_normalizes_to_no_findings(self):
        # Some Gitleaks versions write a bare `null` (not `[]`) when zero
        # leaks are found -- both must be treated identically as "no leaks".
        findings = normalize_gitleaks("null")
        assert findings == []

    def test_empty_stdout_normalizes_to_no_findings(self):
        # Kept as a defensive fallback (normalize_gitleaks is a pure
        # function -- this is not about real gitleaks output shape). The
        # original S-141 finding attributed a zero-byte report to a clean
        # scan, but that was later found (same S-141 pass, see
        # gitleaks_runner.py's module docstring REVERTED section) to be an
        # artifact of the since-removed --report-path /dev/stdout trick
        # silently losing data -- not real gitleaks behavior. A real file
        # report-path (now used unconditionally) writes `[]` on a clean
        # scan, exercised by test_empty_array_normalizes_to_no_findings
        # above.
        findings = normalize_gitleaks("")
        assert findings == []
        findings = normalize_gitleaks("   \n")
        assert findings == []


# ---------------------------------------------------------------------------
# normalize_gitleaks() -- findings fixture
# ---------------------------------------------------------------------------


class TestNormalizeGitleaksFindingsFixture:
    @pytest.fixture
    def findings(self) -> list[Finding]:
        raw_output = _load_fixture("gitleaks_findings.json")
        return normalize_gitleaks(raw_output)

    def test_normalizes_every_leak_into_a_finding(self, findings):
        assert len(findings) == 3
        assert all(isinstance(f, Finding) for f in findings)

    def test_every_finding_carries_the_gitleaks_tool_name(self, findings):
        assert all(f.tool == "gitleaks" for f in findings)
        assert TOOL_NAME == "gitleaks"

    def test_rule_id_taken_from_ruleid(self, findings):
        assert findings[0].rule_id == "generic-api-key"
        assert findings[2].rule_id == "adversarial-description-echo"

    def test_file_path_and_line_range_taken_from_file_and_startline_endline(self, findings):
        assert findings[0].file_path == "config/settings.py"
        assert findings[0].line_start == 12
        assert findings[0].line_end == 12
        assert findings[1].file_path == "scripts/deploy.sh"
        assert findings[1].line_start == 30

    def test_severity_is_always_critical_via_severity_from_gitleaks(self, findings):
        # D29 -- unconditional, no per-rule grading, delegated to severity.py
        # (not reimplemented here).
        assert all(f.severity is Severity.CRITICAL for f in findings)

    def test_remediation_is_always_none(self, findings):
        # Gitleaks has no native mechanical fix path (spec S8.1a / task 5.2).
        assert all(f.remediation is None for f in findings)

    def test_cwe_or_category_falls_back_to_rule_id(self, findings):
        # Gitleaks has no CWE/OWASP metadata -- rule_id is the dedup category
        # key (mirrors Semgrep's own last-resort fallback).
        assert findings[0].cwe_or_category == "generic-api-key"

    def test_raw_ref_points_into_the_raw_output_by_index(self, findings):
        assert findings[0].raw_ref == "gitleaks#0"
        assert findings[2].raw_ref == "gitleaks#2"

    # -- AC-27: message-construction half -----------------------------------

    def test_message_never_contains_the_raw_secret_value(self, findings):
        for finding in findings:
            assert DUMMY_SECRET not in finding.message

    def test_message_never_contains_the_raw_secret_even_when_shared_across_findings(self, findings):
        # Fixture rows 0/1 share the same underlying secret value across two
        # different files -- multiple-occurrence redaction must catch both,
        # not just the first.
        assert DUMMY_SECRET not in findings[0].message
        assert DUMMY_SECRET not in findings[1].message

    def test_adversarial_description_echoing_the_secret_is_still_redacted(self, findings):
        # Fixture row 2's raw Description field itself contains the secret
        # text (simulating a future/malicious rule) -- the defense-in-depth
        # redaction pass (task 5.3, reusing scrubber.scrub()) must strip it
        # even though this module never interpolates Secret/Match directly.
        assert DUMMY_SECRET not in findings[2].message
        # And the message must still be non-empty / informative.
        assert findings[2].message

    def test_message_carries_only_rule_and_description_not_match_or_secret(self, findings):
        message = findings[0].message
        assert "generic-api-key" in message
        assert "api_key" not in message  # never the raw Match text either


# ---------------------------------------------------------------------------
# normalize_gitleaks() -- unparseable input (PRD requirement 18)
# ---------------------------------------------------------------------------


class TestNormalizeGitleaksUnparseableInput:
    def test_invalid_json_raises_json_decode_error(self):
        with pytest.raises(json.JSONDecodeError):
            normalize_gitleaks("not valid json{{{")

    def test_non_list_non_null_payload_raises_type_error(self):
        with pytest.raises(TypeError):
            normalize_gitleaks(json.dumps({"unexpected": "shape"}))

    def test_leak_missing_required_field_raises_key_error(self):
        with pytest.raises(KeyError):
            normalize_gitleaks(json.dumps([{"RuleID": "x"}]))
