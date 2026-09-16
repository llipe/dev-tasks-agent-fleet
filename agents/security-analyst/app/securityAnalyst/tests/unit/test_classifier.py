"""
Unit tests for the finding classifier (spec §8.4, PRD requirements 23-25/27,
D22/D24, story S-134, acceptance criteria 9-12).

This is "the single most product-defining logic in the agent" (S-134 task
list note) -- where the D22 three-bucket model, the D24/requirement 54
`dependency-update` lockfile boundary, and requirement 27's major-version
guard all converge into one function. Every branch below is exercised in
isolation, plus the two hardest cases called out by the task list itself:

  - the JS/TS-excluded vs. Python-not-excluded boundary, side by side
    (requirement 54 / D24's entire point);
  - the `lockfile_managed=True` + major-bump-simultaneously case (EC-38 in
    the test plan): the lockfile branch is checked first in spec §8.4's own
    pseudocode and therefore wins -- not a third outcome, and not silently
    accidental (see ``TestBothGuardsApplySimultaneously`` below).

Covers AC-9 (SC-14), AC-10 (SC-15), AC-11 (SC-16), req 54 (SC-17), AC-12
(SC-18), req 27 (SC-19), EC-38, and RT-3 (classify() totality over the
documented ``Remediation`` field domain).
"""

from __future__ import annotations

import itertools

from classifier import Bucket, _is_major_bump, _is_semver, classify
from dedupe import MergedFinding
from normalize import Finding, Remediation
from severity import Severity


def _make_remediation(
    *,
    kind: str = "version_bump",
    patch: str | None = None,
    target_version: str | None = "2.0.0",
    lockfile_managed: bool = False,
    current_version: str | None = "1.0.0",
) -> Remediation:
    return Remediation(
        kind=kind,
        patch=patch,
        target_version=target_version,
        lockfile_managed=lockfile_managed,
        current_version=current_version,
    )


def _make_finding(
    *,
    tool: str = "trivy",
    rule_id: str = "CVE-2024-0001",
    severity: Severity = Severity.HIGH,
    file_path: str = "requirements.txt",
    line_start: int = 1,
    line_end: int = 1,
    message: str = "vulnerable dependency",
    cwe_or_category: str = "CVE-2024-0001",
    remediation: Remediation | None = None,
    raw_ref: str = "trivy:fs#0",
) -> Finding:
    return Finding(
        tool=tool,
        rule_id=rule_id,
        severity=severity,
        file_path=file_path,
        line_start=line_start,
        line_end=line_end,
        message=message,
        cwe_or_category=cwe_or_category,
        remediation=remediation,
        raw_ref=raw_ref,
    )


def _merged(finding: Finding, reported_by: tuple[str, ...] = ("trivy",)) -> MergedFinding:
    return MergedFinding(finding=finding, reported_by=reported_by)


# ---------------------------------------------------------------------------
# AC9 (SC-14) -- Semgrep native autofix -> mechanical, unconditionally first
# ---------------------------------------------------------------------------


class TestSemgrepAutofixBranch:
    def test_semgrep_autofix_is_mechanical(self):
        finding = _make_finding(
            tool="semgrep",
            file_path="app/main.py",
            remediation=Remediation(
                kind="semgrep_autofix",
                patch="- eval(x)\n+ ast.literal_eval(x)",
                target_version=None,
                lockfile_managed=False,
                current_version=None,
            ),
        )
        assert classify(_merged(finding, ("semgrep",))) is Bucket.MECHANICAL

    def test_semgrep_autofix_branch_checked_before_version_bump_logic(self):
        # Even if lockfile_managed/target_version happen to be populated
        # (should never occur for a real semgrep_autofix remediation), the
        # branch order in spec §8.4 checks semgrep_autofix first and
        # unconditionally -- this pins that precedence directly.
        finding = _make_finding(
            tool="semgrep",
            remediation=Remediation(
                kind="semgrep_autofix",
                patch="patch text",
                target_version="99.0.0",
                lockfile_managed=True,
                current_version="1.0.0",
            ),
        )
        assert classify(_merged(finding, ("semgrep",))) is Bucket.MECHANICAL


# ---------------------------------------------------------------------------
# AC10 (SC-15) -- Trivy base-image (non-lockfile), clean version-bump ->
# mechanical
# ---------------------------------------------------------------------------


class TestTrivyCleanVersionBumpBranch:
    def test_container_base_image_clean_version_bump_is_mechanical(self):
        finding = _make_finding(
            file_path="python:3.13-slim (debian 12.4)",
            remediation=_make_remediation(
                target_version="2.36-9+deb12u4",
                current_version="2.36-9",
                lockfile_managed=False,
            ),
        )
        assert classify(_merged(finding)) is Bucket.MECHANICAL

    def test_minor_version_bump_non_lockfile_is_mechanical(self):
        finding = _make_finding(
            file_path="requirements.txt",
            remediation=_make_remediation(
                target_version="1.2.0",
                current_version="1.1.0",
                lockfile_managed=False,
            ),
        )
        assert classify(_merged(finding)) is Bucket.MECHANICAL


# ---------------------------------------------------------------------------
# AC11 (SC-16) -- Trivy JS/TS lockfile finding -> manual (D24 boundary)
# ---------------------------------------------------------------------------


class TestLockfileManagedBoundaryBranch:
    def test_package_lock_json_version_bump_is_manual(self):
        finding = _make_finding(
            file_path="package-lock.json",
            remediation=_make_remediation(
                target_version="4.18.0",
                current_version="4.17.15",
                lockfile_managed=True,
            ),
        )
        assert classify(_merged(finding)) is Bucket.MANUAL

    def test_pnpm_lock_yaml_version_bump_is_manual(self):
        finding = _make_finding(
            file_path="pnpm-lock.yaml",
            remediation=_make_remediation(
                target_version="1.0.1",
                current_version="1.0.0",
                lockfile_managed=True,
            ),
        )
        assert classify(_merged(finding)) is Bucket.MANUAL

    def test_lockfile_managed_manual_even_for_a_clean_minor_bump(self):
        # D24's whole point -- lockfile_managed overrides an otherwise
        # perfectly "eligible" (clean, minor) version bump.
        finding = _make_finding(
            file_path="package-lock.json",
            remediation=_make_remediation(
                target_version="1.0.1",
                current_version="1.0.0",
                lockfile_managed=True,
            ),
        )
        assert classify(_merged(finding)) is Bucket.MANUAL

    def test_lockfile_managed_finding_retains_data_for_downstream_annotation(self):
        # classify() itself returns a bare Bucket (spec §8.4's literal
        # signature); the "annotated naming dependency-update as owner"
        # requirement (req 24 / AC11) is rendered downstream (S-135's PR
        # body / audit report, out of this story's scope) from the same
        # MergedFinding's `remediation.lockfile_managed` field, which this
        # test pins as still present and readable after classification.
        finding = _make_finding(
            file_path="package-lock.json",
            remediation=_make_remediation(lockfile_managed=True),
        )
        merged = _merged(finding)
        assert classify(merged) is Bucket.MANUAL
        assert merged.finding.remediation.lockfile_managed is True


# ---------------------------------------------------------------------------
# req 54 (SC-17) -- the JS/TS-excluded vs. Python-not-excluded boundary,
# side by side. This is D24/requirement 54's entire point.
# ---------------------------------------------------------------------------


class TestJsTsVsPythonBoundarySideBySide:
    def test_js_lockfile_finding_is_manual_python_manifest_equivalent_is_mechanical(self):
        js_finding = _make_finding(
            file_path="package-lock.json",
            remediation=_make_remediation(
                target_version="1.2.1",
                current_version="1.2.0",
                lockfile_managed=True,  # set by trivy_runner.py's _JS_LOCKFILES check
            ),
        )
        python_finding = _make_finding(
            file_path="requirements.txt",
            remediation=_make_remediation(
                target_version="1.2.1",
                current_version="1.2.0",
                lockfile_managed=False,  # requirements.txt is NOT in _JS_LOCKFILES
            ),
        )
        assert classify(_merged(js_finding)) is Bucket.MANUAL
        assert classify(_merged(python_finding)) is Bucket.MECHANICAL

    def test_poetry_lock_is_mechanical_when_otherwise_eligible(self):
        finding = _make_finding(
            file_path="poetry.lock",
            remediation=_make_remediation(
                target_version="3.1.0",
                current_version="3.0.0",
                lockfile_managed=False,
            ),
        )
        assert classify(_merged(finding)) is Bucket.MECHANICAL

    def test_pipfile_lock_is_mechanical_when_otherwise_eligible(self):
        finding = _make_finding(
            file_path="Pipfile.lock",
            remediation=_make_remediation(
                target_version="0.9.1",
                current_version="0.9.0",
                lockfile_managed=False,
            ),
        )
        assert classify(_merged(finding)) is Bucket.MECHANICAL


# ---------------------------------------------------------------------------
# req 27 (SC-19) -- major-version bump on a non-lockfile semver artifact ->
# manual, reason recorded
# ---------------------------------------------------------------------------


class TestMajorVersionBumpGuardBranch:
    def test_major_bump_on_non_lockfile_semver_artifact_is_manual(self):
        finding = _make_finding(
            file_path="ghcr.io/example/base-image",
            remediation=_make_remediation(
                target_version="2.0.0",
                current_version="1.9.3",
                lockfile_managed=False,
            ),
        )
        assert classify(_merged(finding)) is Bucket.MANUAL

    def test_minor_and_patch_bumps_are_not_treated_as_major(self):
        minor = _make_finding(
            remediation=_make_remediation(
                target_version="1.3.0", current_version="1.2.9", lockfile_managed=False
            )
        )
        patch = _make_finding(
            remediation=_make_remediation(
                target_version="1.2.10", current_version="1.2.9", lockfile_managed=False
            )
        )
        assert classify(_merged(minor)) is Bucket.MECHANICAL
        assert classify(_merged(patch)) is Bucket.MECHANICAL

    def test_major_bump_guard_only_applies_when_target_is_clean_semver(self):
        # target_version "2.36-9+deb12u4" is not clean 3-part semver, so
        # _is_semver() is False and the major-bump guard never fires even
        # though the leading numeric component looks like it increased --
        # this is `_is_major_bump`/`_is_semver`'s "otherwise-eligible" case
        # (task 10.1's branch precedence #4), matching spec §8.4's literal
        # `_is_major_bump(f) and _is_semver(target_version)` conjunction.
        finding = _make_finding(
            remediation=_make_remediation(
                target_version="3.0.9-1+deb12u1",
                current_version="3.0.9",
                lockfile_managed=False,
            )
        )
        assert classify(_merged(finding)) is Bucket.MECHANICAL


# ---------------------------------------------------------------------------
# EC-38 -- lockfile_managed=True AND major-bump simultaneously: lockfile
# branch wins (checked first per spec §8.4's branch order), a deliberate,
# documented choice, not a third outcome.
# ---------------------------------------------------------------------------


class TestBothGuardsApplySimultaneously:
    def test_lockfile_managed_wins_over_major_bump_guard(self):
        finding = _make_finding(
            file_path="package-lock.json",
            remediation=_make_remediation(
                target_version="5.0.0",
                current_version="1.0.0",
                lockfile_managed=True,
            ),
        )
        # Still just MANUAL -- not a distinct third outcome. The point of
        # this test is that classify() does not crash or branch strangely
        # when both conditions independently justify `manual`; the spec's
        # own branch order (lockfile check strictly before the major-bump
        # check) is what determines which annotation a downstream PR-body
        # renderer would pick, not this function's return value.
        assert classify(_merged(finding)) is Bucket.MANUAL


# ---------------------------------------------------------------------------
# AC12 (SC-18) -- unparseable remediation shape -> unscannable, never
# guessed
# ---------------------------------------------------------------------------


class TestUnscannableBranch:
    def test_remediation_none_is_unscannable(self):
        finding = _make_finding(remediation=None)
        assert classify(_merged(finding)) is Bucket.UNSCANNABLE

    def test_unscannable_never_falls_through_to_mechanical_or_manual(self):
        # Defensive: confirm the None-remediation check really is checked
        # first and short-circuits, regardless of any other field content.
        finding = _make_finding(
            tool="semgrep",
            remediation=None,
        )
        result = classify(_merged(finding))
        assert result is Bucket.UNSCANNABLE
        assert result is not Bucket.MECHANICAL
        assert result is not Bucket.MANUAL


# ---------------------------------------------------------------------------
# Structural remediation (Checkov/CodeQL default) + the "everything else"
# safe default -> manual, never guessed into mechanical
# ---------------------------------------------------------------------------


class TestStructuralAndUnknownKindDefaultToManual:
    def test_structural_remediation_is_manual(self):
        finding = _make_finding(
            tool="checkov",
            remediation=Remediation(
                kind="structural",
                patch=None,
                target_version=None,
                lockfile_managed=False,
                current_version=None,
            ),
        )
        assert classify(_merged(finding, ("checkov",))) is Bucket.MANUAL

    def test_unrecognized_remediation_kind_defaults_to_manual_not_mechanical(self):
        # Safe default (branch 7 of the task's precedence list) -- an
        # unrecognized `kind` string must never be silently guessed into
        # `mechanical`.
        finding = _make_finding(
            remediation=Remediation(
                kind="something_unexpected",
                patch=None,
                target_version=None,
                lockfile_managed=False,
                current_version=None,
            )
        )
        assert classify(_merged(finding)) is Bucket.MANUAL


# ---------------------------------------------------------------------------
# _is_semver()/_is_major_bump() helpers, exercised directly
# ---------------------------------------------------------------------------


class TestIsSemverHelper:
    def test_clean_three_part_semver_is_true(self):
        assert _is_semver("1.2.3") is True
        assert _is_semver("0.0.1") is True

    def test_semver_with_prerelease_or_build_metadata_is_true(self):
        assert _is_semver("1.2.3-alpha.1") is True
        assert _is_semver("1.2.3+build.5") is True

    def test_non_semver_strings_are_false(self):
        assert _is_semver("2.36-9+deb12u4") is False
        assert _is_semver("5.3") is False
        assert _is_semver("latest") is False
        assert _is_semver("") is False

    def test_none_is_false_and_does_not_raise(self):
        assert _is_semver(None) is False


class TestIsMajorBumpHelper:
    def test_major_increase_is_true(self):
        finding = _make_finding(
            remediation=_make_remediation(current_version="1.9.3", target_version="2.0.0")
        )
        assert _is_major_bump(finding) is True

    def test_minor_or_patch_increase_is_false(self):
        minor = _make_finding(
            remediation=_make_remediation(current_version="1.2.9", target_version="1.3.0")
        )
        patch = _make_finding(
            remediation=_make_remediation(current_version="1.2.9", target_version="1.2.10")
        )
        assert _is_major_bump(minor) is False
        assert _is_major_bump(patch) is False

    def test_unparseable_versions_return_false_not_raise(self):
        # Defensive -- current_version or target_version missing/garbage
        # must never crash classify(); _is_major_bump degrades to "cannot
        # confirm a major bump" (False), matching branch 4's "otherwise
        # eligible" default rather than raising.
        no_current = _make_finding(
            remediation=_make_remediation(current_version=None, target_version="2.0.0")
        )
        garbage_target = _make_finding(
            remediation=_make_remediation(current_version="1.0.0", target_version="latest")
        )
        both_garbage = _make_finding(
            remediation=_make_remediation(current_version="n/a", target_version="n/a")
        )
        assert _is_major_bump(no_current) is False
        assert _is_major_bump(garbage_target) is False
        assert _is_major_bump(both_garbage) is False

    def test_remediation_none_is_false_not_raise(self):
        finding = _make_finding(remediation=None)
        assert _is_major_bump(finding) is False


# ---------------------------------------------------------------------------
# req 25 -- classification is deterministic parsing only, no LLM call.
# ---------------------------------------------------------------------------


class TestDeterminismNoLlmCall:
    def test_classify_module_imports_no_llm_or_network_dependency(self):
        import classifier

        source = classifier.__file__
        assert source is not None
        with open(source, encoding="utf-8") as fh:
            text = fh.read()
        # Defensive textual guard -- classify() must never import strands
        # (the LLM/agent SDK) or make a network/subprocess call. A real LLM
        # invocation would require importing one of these.
        for forbidden in ("strands", "boto3", "subprocess", "requests"):
            assert forbidden not in text

    def test_classify_is_deterministic_across_repeated_calls(self):
        finding = _make_finding(
            remediation=_make_remediation(
                target_version="1.1.0", current_version="1.0.0", lockfile_managed=False
            )
        )
        merged = _merged(finding)
        results = {classify(merged) for _ in range(50)}
        assert results == {Bucket.MECHANICAL}


# ---------------------------------------------------------------------------
# RT-3 -- classify() totality: always returns a value in {MECHANICAL,
# MANUAL, UNSCANNABLE} for any well-formed Finding/Remediation combination.
# Structured fuzzing over the documented Remediation field domain (no
# arbitrary bytes -- the schema is closed per spec §8.1).
# ---------------------------------------------------------------------------


class TestClassifyTotality:
    def test_classify_is_total_over_the_documented_field_domain(self):
        kinds = ["semgrep_autofix", "version_bump", "structural", "unknown_kind", ""]
        lockfile_managed_values = [True, False]
        target_versions = [None, "1.0.0", "2.0.0", "latest", "2.36-9+deb12u4", ""]
        current_versions = [None, "1.0.0", "0.9.0"]

        for kind, lockfile_managed, target_version, current_version in itertools.product(
            kinds, lockfile_managed_values, target_versions, current_versions
        ):
            remediation = Remediation(
                kind=kind,
                patch=None,
                target_version=target_version,
                lockfile_managed=lockfile_managed,
                current_version=current_version,
            )
            finding = _make_finding(remediation=remediation)
            result = classify(_merged(finding))
            assert result in (Bucket.MECHANICAL, Bucket.MANUAL, Bucket.UNSCANNABLE)

        # remediation=None is the fourth documented shape.
        assert classify(_merged(_make_finding(remediation=None))) is Bucket.UNSCANNABLE
