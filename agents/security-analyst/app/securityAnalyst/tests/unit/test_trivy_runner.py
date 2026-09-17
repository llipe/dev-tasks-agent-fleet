"""
Unit tests for Trivy normalization + the `lockfile_managed` boundary (spec
§8.1/§8.4, PRD requirements 16/17/53/54, story S-130 AC1-AC4).

This is the single most consequential test module in the whole build per the
task list's own note: `lockfile_managed` decides the classifier's (S-134)
entire mechanical/manual split for Trivy findings (D24). Every target-file
type Trivy's `fs` mode can report against is exercised here, not just the
two headline cases (`package-lock.json` / `requirements.txt`).

Covers:
  - ``normalize_trivy()`` against all four fixture shapes: `fs`(npm),
    `fs`(python), `config`, `image`.
  - The `lockfile_managed` boundary (PRD requirement 54) -- `True` only for
    `package-lock.json`/`pnpm-lock.yaml` targets, `False` for every other
    target-file type Trivy's `fs` mode can report against (`requirements.txt`,
    `poetry.lock`, `Pipfile.lock`, a container-image target string, and an
    IaC file target), even though several of those are themselves also
    "lockfiles" in the general sense (D24's boundary is narrower than that).
  - `remediation.kind = "version_bump"` applied identically to npm/pnpm and
    Python findings (the boundary is enforced later, at classification --
    not here).
  - Vulnerability entries with no `FixedVersion` published yet normalize to
    `remediation = None` (no mechanical fix path exists yet).
  - Misconfiguration entries (Class == "config") always normalize to
    `remediation.kind = "structural"`, `lockfile_managed = False`, never
    version-bumped and never JS/TS-lockfile-boundaried.
  - `Status == "PASS"` misconfiguration rows are excluded (Trivy's config
    scan reports passing checks too when asked; only `FAIL` rows are real
    findings).
  - `FixedVersion`'s comma-separated multi-version form resolves to the
    lowest closing version.
  - Unparseable input (PRD requirement 18).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from normalize import Finding, Remediation
from scanners.trivy_runner import _JS_LOCKFILES, TOOL_NAME, _lowest_fixed_version, normalize_trivy
from severity import Severity

_FIXTURES = Path(__file__).parent.parent / "fixtures"


def _load_fixture(name: str) -> str:
    return (_FIXTURES / name).read_text()


# ---------------------------------------------------------------------------
# _JS_LOCKFILES -- the exact D24/req 54 boundary set.
# ---------------------------------------------------------------------------


class TestJsLockfilesSet:
    def test_js_lockfiles_is_exactly_the_two_documented_files(self):
        assert {"package-lock.json", "pnpm-lock.yaml"} == _JS_LOCKFILES

    def test_python_manifests_are_not_members(self):
        # D24/req 54 -- these are lockfiles in the general sense but are
        # deliberately NOT in the boundary set (dependency-update has no
        # Python support; Python version-bump findings must stay MECHANICAL,
        # not fall into this agent's JS/TS-lockfile MANUAL lane).
        for manifest in ("requirements.txt", "poetry.lock", "Pipfile.lock"):
            assert manifest not in _JS_LOCKFILES


# ---------------------------------------------------------------------------
# normalize_trivy() -- fs(npm) fixture
# ---------------------------------------------------------------------------


class TestNormalizeTrivyFsNpm:
    @pytest.fixture
    def findings(self) -> list[Finding]:
        raw_output = _load_fixture("trivy_fs_npm.json")
        return normalize_trivy(raw_output, mode="fs")

    def test_normalizes_every_vulnerability_into_a_finding(self, findings):
        assert len(findings) == 3
        assert all(isinstance(f, Finding) for f in findings)
        assert all(f.tool == "trivy" for f in findings)

    def test_lockfile_managed_true_for_package_lock_json(self, findings):
        lodash = findings[0]
        assert lodash.file_path == "package-lock.json"
        assert lodash.remediation.lockfile_managed is True

    def test_lockfile_managed_true_for_pnpm_lock_yaml_even_when_nested(self, findings):
        # Nested monorepo path -- membership is checked on the basename, not
        # exact full-path equality.
        axios = findings[2]
        assert axios.file_path == "frontend/pnpm-lock.yaml"
        assert axios.remediation.lockfile_managed is True

    def test_remediation_kind_is_version_bump(self, findings):
        assert findings[0].remediation.kind == "version_bump"
        assert findings[2].remediation.kind == "version_bump"

    def test_target_version_resolves_to_lowest_comma_separated_fixed_version(self, findings):
        # FixedVersion = "4.17.21, 4.18.0" -> lowest is 4.17.21.
        assert findings[0].remediation.target_version == "4.17.21"

    def test_single_fixed_version_used_verbatim(self, findings):
        assert findings[2].remediation.target_version == "0.21.4"

    def test_empty_fixed_version_yields_no_remediation(self, findings):
        # minimist: FixedVersion == "" -- no mechanical fix path exists yet.
        minimist = findings[1]
        assert minimist.remediation is None

    def test_severity_delegates_to_severity_from_trivy(self, findings):
        assert findings[0].severity is Severity.HIGH
        assert findings[1].severity is Severity.MEDIUM
        assert findings[2].severity is Severity.CRITICAL

    def test_rule_id_is_the_cve(self, findings):
        assert findings[0].rule_id == "CVE-2023-11111"

    def test_cwe_or_category_taken_from_cwe_ids(self, findings):
        assert findings[0].cwe_or_category == "CWE-1321"

    def test_cwe_or_category_falls_back_to_rule_id_when_absent(self, findings):
        # minimist has no CweIDs field.
        assert findings[1].cwe_or_category == "CVE-2023-22222"

    def test_message_prefers_title(self, findings):
        assert findings[0].message == "lodash: prototype pollution"

    def test_raw_ref_is_prefixed_with_mode(self, findings):
        assert findings[0].raw_ref == "trivy:fs#0"
        assert findings[2].raw_ref == "trivy:fs#2"


# ---------------------------------------------------------------------------
# normalize_trivy() -- fs(python) fixture -- the AC1/req53/req54 headline case.
# ---------------------------------------------------------------------------


class TestNormalizeTrivyFsPython:
    @pytest.fixture
    def findings(self) -> list[Finding]:
        raw_output = _load_fixture("trivy_fs_python.json")
        return normalize_trivy(raw_output, mode="fs")

    def test_normalizes_every_vulnerability_into_a_finding(self, findings):
        assert len(findings) == 3

    def test_requirements_txt_is_lockfile_managed_false(self, findings):
        requests_finding = findings[0]
        assert requests_finding.file_path == "requirements.txt"
        assert requests_finding.remediation.lockfile_managed is False

    def test_poetry_lock_is_lockfile_managed_false(self, findings):
        jinja_finding = findings[1]
        assert jinja_finding.file_path == "poetry.lock"
        assert jinja_finding.remediation.lockfile_managed is False

    def test_pipfile_lock_is_lockfile_managed_false(self, findings):
        pyyaml_finding = findings[2]
        assert pyyaml_finding.file_path == "Pipfile.lock"
        assert pyyaml_finding.remediation.lockfile_managed is False

    def test_remediation_kind_is_version_bump_same_as_npm(self, findings):
        # req 53/6.3 -- the boundary is NOT applied here; Python findings get
        # the identical version_bump treatment as npm/pnpm findings.
        assert all(f.remediation.kind == "version_bump" for f in findings)

    def test_target_versions_set_correctly(self, findings):
        assert findings[0].remediation.target_version == "2.31.0"
        assert findings[1].remediation.target_version == "2.11.3"
        assert findings[2].remediation.target_version == "5.4"


# ---------------------------------------------------------------------------
# lockfile_managed boundary -- exhaustive, side-by-side (PRD req 54, task 6.6)
# ---------------------------------------------------------------------------


class TestLockfileManagedBoundary:
    def test_lockfile_managed_boundary(self):
        """The single most important assertion in this story (see module +
        task-list note): every target-file type Trivy's `fs` mode can report
        against, exercised side by side, so the D24 boundary can never
        silently regress.
        """
        npm_findings = normalize_trivy(_load_fixture("trivy_fs_npm.json"), mode="fs")
        python_findings = normalize_trivy(_load_fixture("trivy_fs_python.json"), mode="fs")

        # minimist's FixedVersion is empty (no fix published yet) -> its
        # remediation is `None` (no boundary decision to make) -- excluded
        # here, covered separately by
        # `TestNormalizeTrivyFsNpm::test_empty_fixed_version_yields_no_remediation`.
        boundary_true = {
            f.file_path: f.remediation.lockfile_managed
            for f in npm_findings
            if f.remediation is not None
        }
        boundary_false = {f.file_path: f.remediation.lockfile_managed for f in python_findings}

        assert boundary_true == {
            "package-lock.json": True,
            "frontend/pnpm-lock.yaml": True,
        }
        assert boundary_false == {
            "requirements.txt": False,
            "poetry.lock": False,
            "Pipfile.lock": False,
        }

    def test_config_and_image_targets_are_also_lockfile_managed_false(self):
        # Non-JS-lockfile targets outside the fs/Python set entirely (an IaC
        # file, a container image target string) must never accidentally
        # trip the boundary either.
        config_findings = normalize_trivy(_load_fixture("trivy_config.json"), mode="config")
        image_findings = normalize_trivy(_load_fixture("trivy_image.json"), mode="image")

        assert all(f.remediation.lockfile_managed is False for f in config_findings)
        assert all(
            f.remediation.lockfile_managed is False
            for f in image_findings
            if f.remediation is not None
        )


# ---------------------------------------------------------------------------
# normalize_trivy() -- config fixture (Misconfigurations, always structural)
# ---------------------------------------------------------------------------


class TestNormalizeTrivyConfig:
    @pytest.fixture
    def findings(self) -> list[Finding]:
        raw_output = _load_fixture("trivy_config.json")
        return normalize_trivy(raw_output, mode="config")

    def test_pass_status_rows_are_excluded(self, findings):
        # trivy_config.json's Dockerfile target has 3 Misconfigurations, one
        # Status == "PASS" -- only the 2 FAIL rows become findings.
        dockerfile_findings = [f for f in findings if f.file_path == "Dockerfile"]
        assert len(dockerfile_findings) == 2
        assert all(f.rule_id != "DS001" for f in dockerfile_findings)

    def test_remediation_kind_is_always_structural(self, findings):
        assert all(f.remediation is not None for f in findings)
        assert all(f.remediation.kind == "structural" for f in findings)

    def test_structural_remediation_carries_no_patch_or_target_version(self, findings):
        for f in findings:
            assert f.remediation.patch is None
            assert f.remediation.target_version is None

    def test_structural_remediation_is_never_lockfile_managed(self, findings):
        assert all(f.remediation.lockfile_managed is False for f in findings)

    def test_line_range_taken_from_cause_metadata_when_present(self, findings):
        terraform_finding = next(f for f in findings if f.file_path == "main.tf")
        assert terraform_finding.line_start == 12
        assert terraform_finding.line_end == 18

    def test_line_range_defaults_when_cause_metadata_absent_or_empty(self, findings):
        healthcheck = next(f for f in findings if f.rule_id == "DS026")
        assert healthcheck.line_start == 1
        assert healthcheck.line_end == 1

    def test_rule_id_is_the_misconfiguration_id(self, findings):
        assert any(f.rule_id == "AVD-AWS-0031" for f in findings)

    def test_cwe_or_category_falls_back_to_rule_id(self, findings):
        # Misconfigurations carry no CWE metadata.
        root_user_finding = next(f for f in findings if f.rule_id == "DS002")
        assert root_user_finding.cwe_or_category == "DS002"

    def test_message_prefers_message_field_over_title(self, findings):
        root_user_finding = next(f for f in findings if f.rule_id == "DS002")
        assert root_user_finding.message == (
            "Specify at least 1 USER command in Dockerfile with non-root user as argument"
        )

    def test_severity_delegates_to_severity_from_trivy(self, findings):
        s3_finding = next(f for f in findings if f.rule_id == "AVD-AWS-0031")
        assert s3_finding.severity is Severity.CRITICAL


# ---------------------------------------------------------------------------
# normalize_trivy() -- image fixture (os-pkgs Vulnerabilities, version_bump)
# ---------------------------------------------------------------------------


class TestNormalizeTrivyImage:
    @pytest.fixture
    def findings(self) -> list[Finding]:
        raw_output = _load_fixture("trivy_image.json")
        return normalize_trivy(raw_output, mode="image")

    def test_normalizes_every_vulnerability_across_all_results(self, findings):
        # Two Results entries (2 + 1 vulnerabilities) -- both aggregated.
        assert len(findings) == 3

    def test_os_package_vulnerabilities_are_version_bump_not_structural(self, findings):
        # Deviation from a literal reading of the issue's AC bullet grouping
        # "config/image findings" together as structural -- see module
        # docstring and scanners/trivy_runner.py's module docstring for the
        # full reasoning: classification is driven by Trivy's own `Class`
        # field (`os-pkgs`/`lang-pkgs` -> version_bump; `config` ->
        # structural), not by which subprocess mode produced the payload.
        # This is required for spec §8.4's own classifier walkthrough
        # ("Trivy finding on a container base image (non-lockfile) with
        # clean version-bump -> mechanical", PRD AC10) to be reachable at
        # all -- a structural-only image finding could never take that
        # branch. (findings[1], the openssl entry, has no FixedVersion yet
        # and so is `None` -- excluded here, covered by its own test below.)
        with_remediation = [f for f in findings if f.remediation is not None]
        assert len(with_remediation) == 2
        assert all(f.remediation.kind == "version_bump" for f in with_remediation)

    def test_image_target_never_matches_the_js_lockfile_boundary(self, findings):
        with_remediation = [f for f in findings if f.remediation is not None]
        assert all(f.remediation.lockfile_managed is False for f in with_remediation)

    def test_no_fixed_version_yields_no_remediation(self, findings):
        openssl_finding = findings[1]
        assert openssl_finding.rule_id == "CVE-2023-88888"
        assert openssl_finding.remediation is None

    def test_raw_ref_is_prefixed_with_image_mode(self, findings):
        assert findings[0].raw_ref == "trivy:image#0"


# ---------------------------------------------------------------------------
# normalize_trivy() -- null Results (Trivy's "nothing found" shape)
# ---------------------------------------------------------------------------


class TestNormalizeTrivyCleanFixture:
    def test_null_results_normalizes_to_no_findings(self):
        raw_output = _load_fixture("trivy_clean.json")
        findings = normalize_trivy(raw_output, mode="fs")
        assert findings == []

    def test_missing_results_key_normalizes_to_no_findings(self):
        # S-141 real-invocation finding: the real trivy v0.74.0 binary omits
        # the "Results" key entirely (not null) when zero config files are
        # detected -- confirmed against the real binary, not a fixture.
        findings = normalize_trivy(json.dumps({"SchemaVersion": 2}), mode="fs")
        assert findings == []


# ---------------------------------------------------------------------------
# normalize_trivy() -- unparseable input (PRD requirement 18)
# ---------------------------------------------------------------------------


class TestNormalizeTrivyUnparseableInput:
    def test_invalid_json_raises_json_decode_error(self):
        with pytest.raises(json.JSONDecodeError):
            normalize_trivy("not valid json{{{", mode="fs")

    def test_results_entry_missing_target_raises_key_error(self):
        with pytest.raises(KeyError):
            normalize_trivy(
                json.dumps({"Results": [{"Class": "lang-pkgs", "Vulnerabilities": []}]}),
                mode="fs",
            )


# ---------------------------------------------------------------------------
# Remediation shape sanity -- consistent with `normalize.py`'s dataclass.
# ---------------------------------------------------------------------------


class TestRemediationShape:
    def test_version_bump_remediation_is_a_remediation_instance(self):
        findings = normalize_trivy(_load_fixture("trivy_fs_npm.json"), mode="fs")
        assert isinstance(findings[0].remediation, Remediation)

    def test_tool_name_is_trivy(self):
        assert TOOL_NAME == "trivy"


# ---------------------------------------------------------------------------
# _lowest_fixed_version() -- FixedVersion parsing edge cases, directly.
# ---------------------------------------------------------------------------


class TestLowestFixedVersion:
    def test_none_or_empty_returns_none(self):
        assert _lowest_fixed_version("") is None
        assert _lowest_fixed_version("   ") is None

    def test_single_version_returned_verbatim(self):
        assert _lowest_fixed_version("2.31.0") == "2.31.0"

    def test_comma_separated_versions_resolve_to_lowest(self):
        assert _lowest_fixed_version("4.17.21, 4.18.0") == "4.17.21"
        assert _lowest_fixed_version("4.18.0, 4.17.21") == "4.17.21"

    def test_whitespace_only_candidates_between_commas_are_ignored(self):
        assert _lowest_fixed_version("1.0.0, , 2.0.0") == "1.0.0"

    def test_all_commas_no_real_candidates_returns_none(self):
        assert _lowest_fixed_version(", , ,") is None

    def test_all_unparseable_candidates_fall_back_to_the_first_one_verbatim(self):
        # Neither candidate has a leading numeric group -- falls back to the
        # first listed one rather than raising or silently dropping the fix.
        assert _lowest_fixed_version("unstable, next") == "unstable"

    def test_debian_style_version_still_parses_a_leading_numeric_group(self):
        assert _lowest_fixed_version("2.36-9+deb12u4") == "2.36-9+deb12u4"

    def test_mixed_parseable_and_unparseable_candidates_prefers_the_parseable_one(self):
        assert _lowest_fixed_version("unstable, 1.2.3") == "1.2.3"
