"""
Unit tests for CodeQL normalization + the JS/TS-Python trigger-condition
matrix (spec S8.1/S8.5, PRD requirements 14/17/51/58 row 5, story S-132
AC bullets, task 8.10).

Covers:
  - ``detect_languages()``'s 4-way trigger matrix: JS/TS only, Python only,
    both, neither (requirement 17/51 -- no third branch).
  - ``normalize_codeql()`` against the JS/TS and Python SARIF fixtures
    separately, including the rule-level (not result-level)
    `security-severity`/`tags` lookup (module docstring Deviation 2) and the
    `level` dual-fallback path (result-level, then rule
    `defaultConfiguration.level`, then the shared unknown-severity floor).
  - `remediation.kind = "structural"` unconditionally, never `None`.
  - `raw_ref` prefixed with the language, not a bare tool name.
  - Vendored/VCS directories never trip either trigger.
  - Unparseable input (PRD requirement 18).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from normalize import Finding, Remediation
from scanners.codeql_runner import (
    _QUERY_PACKS,
    TOOL_NAME,
    detect_languages,
    normalize_codeql,
)
from severity import Severity

_FIXTURES = Path(__file__).parent.parent / "fixtures"


def _load_fixture(name: str) -> str:
    return (_FIXTURES / name).read_text()


# ---------------------------------------------------------------------------
# _QUERY_PACKS -- PRD requirement 51's exact two-entry table, no third.
# ---------------------------------------------------------------------------


class TestQueryPacksTable:
    def test_exactly_two_entries(self):
        assert len(_QUERY_PACKS) == 2

    def test_entries_match_the_pinned_pack_names(self):
        assert _QUERY_PACKS == {
            "javascript-typescript": "codeql/javascript-queries",
            "python": "codeql/python-queries",
        }


# ---------------------------------------------------------------------------
# detect_languages() -- the 4-way trigger-condition matrix (task 8.2, 8.10).
# ---------------------------------------------------------------------------


class TestDetectLanguagesJsTsOnly:
    def test_ts_extension_triggers_js_ts(self, tmp_path):
        (tmp_path / "index.ts").write_text("export {};")
        assert detect_languages(tmp_path) == ["javascript-typescript"]

    def test_jsx_extension_triggers_js_ts(self, tmp_path):
        (tmp_path / "App.jsx").write_text("export default {};")
        assert detect_languages(tmp_path) == ["javascript-typescript"]

    def test_tsx_extension_triggers_js_ts(self, tmp_path):
        (tmp_path / "App.tsx").write_text("export default {};")
        assert detect_languages(tmp_path) == ["javascript-typescript"]

    def test_package_json_alone_triggers_js_ts(self, tmp_path):
        (tmp_path / "package.json").write_text("{}")
        assert detect_languages(tmp_path) == ["javascript-typescript"]


class TestDetectLanguagesPythonOnly:
    def test_py_extension_triggers_python(self, tmp_path):
        (tmp_path / "main.py").write_text("print('hi')")
        assert detect_languages(tmp_path) == ["python"]

    def test_pyproject_toml_alone_triggers_python(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
        assert detect_languages(tmp_path) == ["python"]

    def test_requirements_txt_alone_triggers_python(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("requests==2.31.0\n")
        assert detect_languages(tmp_path) == ["python"]


class TestDetectLanguagesBoth:
    def test_both_languages_detected_in_canonical_order(self, tmp_path):
        (tmp_path / "main.py").write_text("print('hi')")
        (tmp_path / "index.js").write_text("console.log('hi');")
        # Canonical dispatch order is always JS/TS first, Python second --
        # never dependent on filesystem walk/creation order.
        assert detect_languages(tmp_path) == ["javascript-typescript", "python"]

    def test_both_languages_detected_regardless_of_which_file_exists_first(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("flask==3.0.0\n")
        (tmp_path / "package.json").write_text("{}")
        assert detect_languages(tmp_path) == ["javascript-typescript", "python"]


class TestDetectLanguagesNeither:
    def test_empty_workspace_is_skipped(self, tmp_path):
        assert detect_languages(tmp_path) == []

    def test_unrelated_file_content_is_skipped(self, tmp_path):
        (tmp_path / "README.md").write_text("# hello")
        (tmp_path / "Dockerfile").write_text("FROM python:3.13-slim\n")
        assert detect_languages(tmp_path) == []

    def test_vendored_directories_never_trip_the_trigger(self, tmp_path):
        # A dependency's own bundled JS/Python fixtures, or the agent's own
        # virtualenv content, must not cause a false-positive detection.
        vendored = tmp_path / "node_modules" / "some-pkg"
        vendored.mkdir(parents=True)
        (vendored / "index.js").write_text("module.exports = {};")

        venv = tmp_path / ".venv" / "lib"
        venv.mkdir(parents=True)
        (venv / "site.py").write_text("pass")

        assert detect_languages(tmp_path) == []


# ---------------------------------------------------------------------------
# normalize_codeql() -- JS/TS fixture.
# ---------------------------------------------------------------------------


class TestNormalizeCodeqlJsTs:
    @pytest.fixture
    def findings(self) -> list[Finding]:
        raw_output = _load_fixture("codeql_js_ts.json")
        return normalize_codeql(raw_output, language="javascript-typescript")

    def test_normalizes_every_result_into_a_finding(self, findings):
        assert len(findings) == 2
        assert all(isinstance(f, Finding) for f in findings)
        assert all(f.tool == "codeql" for f in findings)

    def test_security_severity_resolved_from_the_rule_definition(self, findings):
        # security-severity = "9.3" lives on the RULE, not the result --
        # module docstring Deviation 2.
        sql_injection = findings[0]
        assert sql_injection.rule_id == "js/sql-injection"
        assert sql_injection.severity is Severity.CRITICAL

    def test_neither_security_severity_nor_usable_level_falls_to_medium_floor(self, findings):
        # js/useless-assignment-to-local: no security-severity anywhere, no
        # result-level `level`, no rule `defaultConfiguration.level` either.
        useless_assignment = findings[1]
        assert useless_assignment.rule_id == "js/useless-assignment-to-local"
        assert useless_assignment.severity is Severity.MEDIUM

    def test_cwe_extracted_from_rule_tags(self, findings):
        assert findings[0].cwe_or_category == "CWE-089"

    def test_cwe_falls_back_to_rule_id_when_no_cwe_tag_present(self, findings):
        assert findings[1].cwe_or_category == "js/useless-assignment-to-local"

    def test_line_range_taken_from_region(self, findings):
        assert findings[0].line_start == 42
        assert findings[0].line_end == 44

    def test_end_line_defaults_to_start_line_when_absent(self, findings):
        # SARIF's single-line shorthand omits endLine -- must default to
        # startLine, not the generic (1, 1) placeholder.
        assert findings[1].line_start == 10
        assert findings[1].line_end == 10

    def test_file_path_taken_from_artifact_location_uri(self, findings):
        assert findings[0].file_path == "src/db/query.js"
        assert findings[1].file_path == "src/util/helpers.js"

    def test_message_taken_from_result_message_text(self, findings):
        assert findings[0].message == "This query string depends on a user-provided value."

    def test_remediation_is_always_structural(self, findings):
        assert all(f.remediation is not None for f in findings)
        assert all(f.remediation.kind == "structural" for f in findings)
        assert all(f.remediation.patch is None for f in findings)
        assert all(f.remediation.target_version is None for f in findings)
        assert all(f.remediation.lockfile_managed is False for f in findings)

    def test_raw_ref_is_prefixed_with_the_language(self, findings):
        assert findings[0].raw_ref == "codeql:javascript-typescript#0"
        assert findings[1].raw_ref == "codeql:javascript-typescript#1"


# ---------------------------------------------------------------------------
# normalize_codeql() -- Python fixture.
# ---------------------------------------------------------------------------


class TestNormalizeCodeqlPython:
    @pytest.fixture
    def findings(self) -> list[Finding]:
        raw_output = _load_fixture("codeql_python.json")
        return normalize_codeql(raw_output, language="python")

    def test_normalizes_every_result_into_a_finding(self, findings):
        assert len(findings) == 2

    def test_security_severity_resolved_from_the_rule_definition(self, findings):
        command_injection = findings[0]
        assert command_injection.rule_id == "py/command-line-injection"
        # security-severity = "8.8" -> high (>= 7.0, < 9.0).
        assert command_injection.severity is Severity.HIGH

    def test_level_falls_back_to_rule_default_configuration_when_absent_on_result(self, findings):
        # py/clear-text-logging-sensitive-data has no security-severity and
        # no result-level `level` -- must fall back to the RULE's own
        # `defaultConfiguration.level` ("warning" -> medium), not straight to
        # the unknown-severity floor.
        clear_text_logging = findings[1]
        assert clear_text_logging.rule_id == "py/clear-text-logging-sensitive-data"
        assert clear_text_logging.severity is Severity.MEDIUM

    def test_cwe_extracted_from_rule_tags(self, findings):
        assert findings[0].cwe_or_category == "CWE-078"
        assert findings[1].cwe_or_category == "CWE-312"

    def test_raw_ref_is_prefixed_with_python(self, findings):
        assert findings[0].raw_ref == "codeql:python#0"


# ---------------------------------------------------------------------------
# normalize_codeql() -- clean fixture (SARIF's native "nothing found" shape).
# ---------------------------------------------------------------------------


class TestNormalizeCodeqlCleanFixture:
    def test_empty_results_normalizes_to_no_findings(self):
        raw_output = _load_fixture("codeql_clean.json")
        findings = normalize_codeql(raw_output, language="javascript-typescript")
        assert findings == []


# ---------------------------------------------------------------------------
# Rule resolution -- ruleId lookup vs. rule.index fallback addressing.
# ---------------------------------------------------------------------------


class TestRuleIndexFallbackAddressing:
    def _sarif(self, result: dict) -> str:
        return json.dumps(
            {
                "runs": [
                    {
                        "tool": {
                            "driver": {
                                "rules": [
                                    {
                                        "id": "py/example-rule",
                                        "properties": {
                                            "security-severity": "9.9",
                                            "tags": ["external/cwe/cwe-020"],
                                        },
                                    }
                                ]
                            }
                        },
                        "results": [result],
                    }
                ]
            }
        )

    def test_rule_resolved_via_rule_index_when_ruleid_absent(self):
        # SARIF's alternate rule-addressing mode: no `ruleId` on the result,
        # only `rule.index` pointing into the run's `rules[]` array.
        raw_output = self._sarif({"rule": {"index": 0}, "message": {"text": "x"}})
        findings = normalize_codeql(raw_output, language="python")
        assert findings[0].severity is Severity.CRITICAL
        assert findings[0].cwe_or_category == "CWE-020"

    def test_out_of_range_rule_index_resolves_to_no_rule(self):
        raw_output = self._sarif({"rule": {"index": 5}, "message": {"text": "x"}})
        findings = normalize_codeql(raw_output, language="python")
        # No ruleId, no resolvable rule.index -- degrades to the unknown
        # floor and the rule_id fallback for both severity and category.
        assert findings[0].severity is Severity.MEDIUM
        assert findings[0].rule_id == "unknown"
        assert findings[0].cwe_or_category == "codeql-unknown"

    def test_result_with_no_locations_falls_back_to_1_1_placeholder(self):
        raw_output = self._sarif({"ruleId": "py/example-rule", "message": {"text": "x"}})
        findings = normalize_codeql(raw_output, language="python")
        assert findings[0].file_path == ""
        assert findings[0].line_start == 1
        assert findings[0].line_end == 1


# ---------------------------------------------------------------------------
# normalize_codeql() -- unparseable input (PRD requirement 18).
# ---------------------------------------------------------------------------


class TestNormalizeCodeqlUnparseableInput:
    def test_invalid_json_raises_json_decode_error(self):
        with pytest.raises(json.JSONDecodeError):
            normalize_codeql("not valid json{{{", language="python")

    def test_missing_runs_key_raises_key_error(self):
        with pytest.raises(KeyError):
            normalize_codeql(json.dumps({"version": "2.1.0"}), language="python")


# ---------------------------------------------------------------------------
# Remediation shape sanity -- consistent with `normalize.py`'s dataclass.
# ---------------------------------------------------------------------------


class TestRemediationShape:
    def test_structural_remediation_is_a_remediation_instance(self):
        findings = normalize_codeql(
            _load_fixture("codeql_js_ts.json"), language="javascript-typescript"
        )
        assert isinstance(findings[0].remediation, Remediation)

    def test_tool_name_is_codeql(self):
        assert TOOL_NAME == "codeql"
