"""
Unit tests for Checkov normalization + IaC-file detection (spec §8.1/§8.5,
PRD requirement 17/23/58 row 4, D30, story S-131 AC1-AC3).

This story is where the `medium` unknown-severity floor (S-126) is first
exercised against real tool output: Checkov's OSS checks (the vast majority
of its ruleset) carry no native `severity` field at all -- only
Bridgecrew-assigned or custom-policy checks do.

Covers:
  - `normalize_checkov()` against both fixture shapes: a multi-framework
    JSON array (Checkov's real-world output shape when more than one
    framework -- e.g. Terraform + Dockerfile -- matches in the same scan)
    and a single-framework JSON object (Checkov's shape when only one
    framework matches), each exercising both the present- and
    absent-severity cases (PRD requirement 58 row 4 / D30).
  - `remediation.kind = "structural"` unconditionally -- Checkov is never
    mechanical in v1 (PRD requirement 23 table, non-goal); this is a hard
    rule the classifier (S-134) depends on.
  - `file_path` is normalized to repo-relative (Checkov's own `file_path`
    is scan-root-relative but leads with `/`; that leading separator is
    stripped here so it matches every other tool's repo-relative
    convention -- see module docstring for the full reasoning).
  - `_has_iac_files()` (the requirement 17 skip-condition detector) directly,
    across Terraform/Dockerfile/CloudFormation/Kubernetes/mixed/none cases.
  - Unparseable input (PRD requirement 18).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from normalize import Finding, Remediation
from scanners.checkov_runner import TOOL_NAME, has_iac_files, normalize_checkov
from severity import Severity

_FIXTURES = Path(__file__).parent.parent / "fixtures"


def _load_fixture(name: str) -> str:
    return (_FIXTURES / name).read_text()


# ---------------------------------------------------------------------------
# normalize_checkov() -- multi-framework array fixture (Terraform + Dockerfile)
# ---------------------------------------------------------------------------


class TestNormalizeCheckovMultiFramework:
    @pytest.fixture
    def findings(self) -> list[Finding]:
        raw_output = _load_fixture("checkov_findings.json")
        return normalize_checkov(raw_output)

    def test_normalizes_every_failed_check_across_all_frameworks(self, findings):
        # 2 terraform failed_checks + 1 dockerfile failed_check = 3.
        assert len(findings) == 3
        assert all(isinstance(f, Finding) for f in findings)
        assert all(f.tool == "checkov" for f in findings)

    def test_severity_present_case_passes_through(self, findings):
        assert findings[0].severity is Severity.CRITICAL
        assert findings[2].severity is Severity.MEDIUM

    def test_severity_absent_case_falls_to_medium_floor(self, findings):
        # CKV_AWS_21 carries `"severity": null` -- the common OSS case.
        assert findings[1].rule_id == "CKV_AWS_21"
        assert findings[1].severity is Severity.MEDIUM

    def test_remediation_kind_is_always_structural(self, findings):
        assert all(f.remediation is not None for f in findings)
        assert all(f.remediation.kind == "structural" for f in findings)

    def test_structural_remediation_carries_no_patch_or_target_version(self, findings):
        for f in findings:
            assert f.remediation.patch is None
            assert f.remediation.target_version is None
            assert f.remediation.lockfile_managed is False

    def test_file_path_strips_leading_separator(self, findings):
        assert findings[0].file_path == "main.tf"
        assert findings[2].file_path == "Dockerfile"

    def test_line_range_taken_from_file_line_range(self, findings):
        assert findings[0].line_start == 12
        assert findings[0].line_end == 18
        assert findings[1].line_start == 20
        assert findings[1].line_end == 24

    def test_rule_id_is_check_id(self, findings):
        assert findings[0].rule_id == "CKV_AWS_20"
        assert findings[2].rule_id == "CKV_DOCKER_2"

    def test_cwe_or_category_falls_back_to_rule_id(self, findings):
        # Checkov carries no CWE/OWASP metadata.
        assert findings[0].cwe_or_category == "CKV_AWS_20"

    def test_message_is_check_name(self, findings):
        assert findings[0].message == "S3 Bucket has an ACL defined which allows public READ access"

    def test_raw_ref_is_prefixed_and_indexed_across_frameworks(self, findings):
        assert findings[0].raw_ref == "checkov#0"
        assert findings[1].raw_ref == "checkov#1"
        assert findings[2].raw_ref == "checkov#2"


# ---------------------------------------------------------------------------
# normalize_checkov() -- single-framework object fixture, no severity at all
# (the common OSS case D30/severity.py's floor was introduced for).
# ---------------------------------------------------------------------------


class TestNormalizeCheckovNoSeverity:
    @pytest.fixture
    def findings(self) -> list[Finding]:
        raw_output = _load_fixture("checkov_no_severity.json")
        return normalize_checkov(raw_output)

    def test_normalizes_every_failed_check(self, findings):
        assert len(findings) == 2

    def test_every_finding_falls_to_the_medium_floor(self, findings):
        assert all(f.severity is Severity.MEDIUM for f in findings)

    def test_remediation_kind_is_structural(self, findings):
        assert all(f.remediation.kind == "structural" for f in findings)


# ---------------------------------------------------------------------------
# normalize_checkov() -- clean fixture (zero failed checks)
# ---------------------------------------------------------------------------


class TestNormalizeCheckovCleanFixture:
    def test_no_failed_checks_normalizes_to_no_findings(self):
        raw_output = _load_fixture("checkov_clean.json")
        findings = normalize_checkov(raw_output)
        assert findings == []

    def test_null_failed_checks_normalizes_to_no_findings(self):
        raw = json.dumps(
            {
                "check_type": "terraform",
                "results": {"failed_checks": None, "passed_checks": []},
            }
        )
        assert normalize_checkov(raw) == []


# ---------------------------------------------------------------------------
# normalize_checkov() -- unparseable input (PRD requirement 18)
# ---------------------------------------------------------------------------


class TestNormalizeCheckovUnparseableInput:
    def test_invalid_json_raises_json_decode_error(self):
        with pytest.raises(json.JSONDecodeError):
            normalize_checkov("not valid json{{{")

    def test_missing_results_key_raises_key_error(self):
        with pytest.raises(KeyError):
            normalize_checkov(json.dumps({"check_type": "terraform"}))

    def test_failed_check_missing_check_id_raises_key_error(self):
        raw = json.dumps(
            {
                "check_type": "terraform",
                "results": {"failed_checks": [{"file_path": "/main.tf"}]},
            }
        )
        with pytest.raises(KeyError):
            normalize_checkov(raw)

    def test_top_level_neither_object_nor_array_raises_type_error(self):
        with pytest.raises(TypeError):
            normalize_checkov(json.dumps("not a report shape"))

    def test_array_of_non_report_entries_raises_type_error(self):
        with pytest.raises(TypeError):
            normalize_checkov(json.dumps(["not", "reports"]))


# ---------------------------------------------------------------------------
# Remediation shape sanity + tool name.
# ---------------------------------------------------------------------------


class TestRemediationShapeAndToolName:
    def test_structural_remediation_is_a_remediation_instance(self):
        findings = normalize_checkov(_load_fixture("checkov_findings.json"))
        assert isinstance(findings[0].remediation, Remediation)

    def test_tool_name_is_checkov(self):
        assert TOOL_NAME == "checkov"


# ---------------------------------------------------------------------------
# has_iac_files() -- the requirement 17 skip-condition detector, directly.
# ---------------------------------------------------------------------------


class TestHasIacFiles:
    def test_empty_workspace_has_no_iac(self, tmp_path):
        assert has_iac_files(tmp_path) is False

    def test_non_iac_content_has_no_iac(self, tmp_path):
        (tmp_path / "README.md").write_text("# hello\n")
        (tmp_path / "app.py").write_text("print('hi')\n")
        assert has_iac_files(tmp_path) is False

    def test_terraform_file_is_detected(self, tmp_path):
        (tmp_path / "main.tf").write_text('resource "aws_s3_bucket" "example" {}\n')
        assert has_iac_files(tmp_path) is True

    def test_terraform_json_variant_is_detected(self, tmp_path):
        (tmp_path / "main.tf.json").write_text("{}\n")
        assert has_iac_files(tmp_path) is True

    def test_dockerfile_is_detected(self, tmp_path):
        (tmp_path / "Dockerfile").write_text("FROM python:3.13-slim\n")
        assert has_iac_files(tmp_path) is True

    def test_dockerfile_variant_suffix_is_detected(self, tmp_path):
        (tmp_path / "Dockerfile.prod").write_text("FROM python:3.13-slim\n")
        assert has_iac_files(tmp_path) is True

    def test_cloudformation_template_is_detected(self, tmp_path):
        (tmp_path / "stack.yaml").write_text(
            "AWSTemplateFormatVersion: '2010-09-09'\nResources:\n  Bucket:\n    Type: AWS::S3::Bucket\n"
        )
        assert has_iac_files(tmp_path) is True

    def test_kubernetes_manifest_is_detected(self, tmp_path):
        (tmp_path / "deployment.yaml").write_text(
            "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: example\n"
        )
        assert has_iac_files(tmp_path) is True

    def test_ordinary_yaml_with_no_iac_signal_is_not_detected(self, tmp_path):
        (tmp_path / "config.yaml").write_text("some: value\nother: thing\n")
        assert has_iac_files(tmp_path) is False

    def test_mixed_terraform_and_dockerfile_is_detected(self, tmp_path):
        (tmp_path / "main.tf").write_text('resource "aws_s3_bucket" "example" {}\n')
        (tmp_path / "Dockerfile").write_text("FROM python:3.13-slim\n")
        assert has_iac_files(tmp_path) is True

    def test_skips_vendored_and_vcs_directories(self, tmp_path):
        vendored = tmp_path / "node_modules" / "some-pkg"
        vendored.mkdir(parents=True)
        (vendored / "main.tf").write_text('resource "x" "y" {}\n')
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "config.tf").write_text('resource "x" "y" {}\n')
        assert has_iac_files(tmp_path) is False
