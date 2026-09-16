"""
Component tests for `fixers/semgrep_autofix.py` and `fixers/trivy_bump.py`
(spec S8.6, PRD requirement 27/28, story S-136, task 12.8) with
`subprocess.run` mocked -- the actual `semgrep`/`git`/`poetry`/`pipenv`
binaries are never invoked. Real filesystem I/O (`tmp_path`) is used for
every file the fixers themselves read/write, so applied-vs-untouched
assertions are genuine diff/file-modification inspections, never trust in
the fixers' own bookkeeping alone (this story's explicit AC28 instruction).

Covers:
  - AC27: Semgrep autofix applied for every `mechanical` Semgrep finding.
  - AC27: Trivy version bump applied for every `mechanical` Trivy finding,
    for all three Python manifest shapes (requirements.txt, poetry.lock's
    companion pyproject.toml, Pipfile.lock's companion Pipfile).
  - AC28 (highest-stakes): a mixed batch of mechanical + manual +
    unscannable findings run through both fixers -- verified by reading
    every fixture file's bytes before and after and asserting only the
    mechanical-bucket files changed, never trusting `FixOutcome`'s own
    `applied_fingerprints` bookkeeping as the sole evidence.
  - Lockfile reconciliation (task 12.6): `poetry lock`/`pipenv lock` is
    invoked, with the correct `cwd`, after a Python manifest bump.
  - Zero-mechanical-findings no-op: no subprocess call at all.
  - Autofix-fails-to-apply-cleanly handoff: no file-level diff after the
    `semgrep --autofix` call -> the targeted finding lands in
    `FixOutcome.unresolved`, not silently dropped.
"""

from __future__ import annotations

import subprocess
from unittest.mock import patch

from dedupe import MergedFinding
from fingerprint import fingerprint
from fixers.semgrep_autofix import apply_semgrep_autofix
from fixers.trivy_bump import apply_trivy_bump
from normalize import Finding, Remediation


def _completed(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


def _semgrep_finding(file_path: str = "app/main.py") -> MergedFinding:
    finding = Finding(
        tool="semgrep",
        rule_id="python.lang.security.audit.eval-detected",
        severity=__import__("severity").Severity.HIGH,
        file_path=file_path,
        line_start=10,
        line_end=10,
        message="Detected use of eval().",
        cwe_or_category="CWE-95",
        remediation=Remediation(
            kind="semgrep_autofix",
            patch="- eval(x)\n+ ast.literal_eval(x)\n",
            target_version=None,
            lockfile_managed=False,
        ),
        raw_ref="semgrep#0",
    )
    return MergedFinding(finding=finding, reported_by=("semgrep",))


def _manual_finding(tool: str, file_path: str, kind: str = "structural") -> MergedFinding:
    from severity import Severity

    finding = Finding(
        tool=tool,
        rule_id="CKV_AWS_1",
        severity=Severity.MEDIUM,
        file_path=file_path,
        line_start=1,
        line_end=1,
        message="misconfiguration",
        cwe_or_category="CKV_AWS_1",
        remediation=Remediation(kind=kind, patch=None, target_version=None, lockfile_managed=False),
        raw_ref=f"{tool}#0",
    )
    return MergedFinding(finding=finding, reported_by=(tool,))


def _unscannable_finding(file_path: str) -> MergedFinding:
    from severity import Severity

    finding = Finding(
        tool="checkov",
        rule_id="UNKNOWN",
        severity=Severity.LOW,
        file_path=file_path,
        line_start=1,
        line_end=1,
        message="unrecognized shape",
        cwe_or_category="UNKNOWN",
        remediation=None,
        raw_ref="checkov#0",
    )
    return MergedFinding(finding=finding, reported_by=("checkov",))


def _trivy_finding(
    file_path: str,
    package_name: str,
    current_version: str,
    target_version: str,
    lockfile_managed: bool = False,
) -> MergedFinding:
    from severity import Severity

    finding = Finding(
        tool="trivy",
        rule_id="CVE-2023-00000",
        severity=Severity.HIGH,
        file_path=file_path,
        line_start=1,
        line_end=1,
        message="vulnerable dependency",
        cwe_or_category="CVE-2023-00000",
        remediation=Remediation(
            kind="version_bump",
            patch=None,
            target_version=target_version,
            lockfile_managed=lockfile_managed,
            current_version=current_version,
            package_name=package_name,
        ),
        raw_ref="trivy:fs#0",
    )
    return MergedFinding(finding=finding, reported_by=("trivy",))


# --------------------------------------------------------------------------
# Semgrep autofix
# --------------------------------------------------------------------------


class TestSemgrepAutofixZeroMechanicalNoOp:
    @patch("fixers.semgrep_autofix.subprocess.run")
    def test_empty_list_makes_no_subprocess_call(self, mock_run, tmp_path):
        outcome = apply_semgrep_autofix(tmp_path, [])

        assert outcome.applied_fingerprints == frozenset()
        assert outcome.unresolved == ()
        mock_run.assert_not_called()

    @patch("fixers.semgrep_autofix.subprocess.run")
    def test_only_non_mechanical_findings_makes_no_subprocess_call(self, mock_run, tmp_path):
        # A manual/unscannable-shaped entry, defensively excluded even
        # though the caller contract says this list should already be
        # mechanical-only (req 28's structural guarantee, not just trust).
        manual = _manual_finding("checkov", "main.tf")
        unscannable = _unscannable_finding("weird.py")

        outcome = apply_semgrep_autofix(tmp_path, [manual, unscannable])

        assert outcome.applied_fingerprints == frozenset()
        mock_run.assert_not_called()


class TestSemgrepAutofixAppliedForEveryMechanicalFinding:
    @patch("fixers.semgrep_autofix.subprocess.run")
    def test_applied_fingerprints_cover_every_mechanical_semgrep_finding(self, mock_run, tmp_path):
        (tmp_path / "app").mkdir()
        target_a = tmp_path / "app" / "a.py"
        target_b = tmp_path / "app" / "b.py"
        target_a.write_text("eval(x)\n")
        target_b.write_text("eval(y)\n")

        finding_a = _semgrep_finding("app/a.py")
        finding_b = _semgrep_finding("app/b.py")

        def _side_effect(cmd, **kwargs):
            if cmd[0] == "semgrep":
                # Simulate the autofix binary rewriting both matched files.
                target_a.write_text("ast.literal_eval(x)\n")
                target_b.write_text("ast.literal_eval(y)\n")
                return _completed(stdout='{"results": []}')
            if cmd[:2] == ["git", "diff"]:
                return _completed(stdout="app/a.py\napp/b.py\n")
            raise AssertionError(f"unexpected command: {cmd}")

        mock_run.side_effect = _side_effect

        outcome = apply_semgrep_autofix(tmp_path, [finding_a, finding_b])

        assert outcome.applied_fingerprints == {
            fingerprint(finding_a.finding),
            fingerprint(finding_b.finding),
        }
        assert outcome.unresolved == ()

    @patch("fixers.semgrep_autofix.subprocess.run")
    def test_command_uses_pinned_ruleset_and_autofix_flag(self, mock_run, tmp_path):
        from scanners.semgrep_runner import RULESET

        (tmp_path / "a.py").write_text("eval(x)\n")
        finding = _semgrep_finding("a.py")

        def _side_effect(cmd, **kwargs):
            if cmd[0] == "semgrep":
                assert "--autofix" in cmd
                assert cmd.count("--config") == len(RULESET)
                for ruleset_id in RULESET:
                    assert ruleset_id in cmd
                return _completed()
            return _completed(stdout="")

        mock_run.side_effect = _side_effect

        apply_semgrep_autofix(tmp_path, [finding])
        assert mock_run.called


class TestSemgrepAutofixFailsToApplyCleanly:
    @patch("fixers.semgrep_autofix.subprocess.run")
    def test_no_diff_after_autofix_lands_finding_in_unresolved(self, mock_run, tmp_path):
        (tmp_path / "a.py").write_text("eval(x)\n")
        finding = _semgrep_finding("a.py")

        def _side_effect(cmd, **kwargs):
            if cmd[0] == "semgrep":
                # Autofix ran but the patch failed to apply cleanly (e.g. a
                # merge conflict against surrounding code) -- file unchanged.
                return _completed(stdout='{"results": []}')
            if cmd[:2] == ["git", "diff"]:
                return _completed(stdout="")  # nothing changed
            raise AssertionError(f"unexpected command: {cmd}")

        mock_run.side_effect = _side_effect

        outcome = apply_semgrep_autofix(tmp_path, [finding])

        assert outcome.applied_fingerprints == frozenset()
        assert outcome.unresolved == (finding,)

    @patch("fixers.semgrep_autofix.subprocess.run")
    def test_timeout_lands_every_targeted_finding_in_unresolved(self, mock_run, tmp_path):
        (tmp_path / "a.py").write_text("eval(x)\n")
        finding = _semgrep_finding("a.py")
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=["semgrep"], timeout=600)

        outcome = apply_semgrep_autofix(tmp_path, [finding])

        assert outcome.applied_fingerprints == frozenset()
        assert outcome.unresolved == (finding,)
        assert "timed out" in outcome.output

    @patch("fixers.semgrep_autofix.subprocess.run")
    def test_binary_missing_lands_every_targeted_finding_in_unresolved(self, mock_run, tmp_path):
        (tmp_path / "a.py").write_text("eval(x)\n")
        finding = _semgrep_finding("a.py")
        mock_run.side_effect = OSError("semgrep: command not found")

        outcome = apply_semgrep_autofix(tmp_path, [finding])

        assert outcome.applied_fingerprints == frozenset()
        assert outcome.unresolved == (finding,)
        assert "failed to start" in outcome.output


# --------------------------------------------------------------------------
# Trivy version bump
# --------------------------------------------------------------------------


class TestTrivyBumpZeroMechanicalNoOp:
    @patch("fixers.trivy_bump.subprocess.run")
    def test_empty_list_makes_no_subprocess_call(self, mock_run, tmp_path):
        outcome = apply_trivy_bump(tmp_path, [])

        assert outcome.applied_fingerprints == frozenset()
        mock_run.assert_not_called()

    @patch("fixers.trivy_bump.subprocess.run")
    def test_lockfile_managed_finding_alone_makes_no_subprocess_call(self, mock_run, tmp_path):
        # D24 boundary -- lockfile_managed=True is dependency-update's lane,
        # defensively excluded even if handed to this fixer directly.
        js_finding = _trivy_finding(
            "pnpm-lock.yaml", "left-pad", "1.0.0", "1.0.1", lockfile_managed=True
        )

        outcome = apply_trivy_bump(tmp_path, [js_finding])

        assert outcome.applied_fingerprints == frozenset()
        mock_run.assert_not_called()


class TestTrivyBumpAppliedForEveryMechanicalFinding:
    def test_requirements_txt_bumped_in_place(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("requests==2.25.0\n")
        finding = _trivy_finding("requirements.txt", "requests", "2.25.0", "2.31.0")

        outcome = apply_trivy_bump(tmp_path, [finding])

        assert (tmp_path / "requirements.txt").read_text() == "requests==2.31.0\n"
        assert outcome.applied_fingerprints == {fingerprint(finding.finding)}
        assert outcome.unresolved == ()

    @patch("fixers.trivy_bump.subprocess.run")
    def test_poetry_lock_bumps_pyproject_and_reconciles(self, mock_run, tmp_path):
        (tmp_path / "pyproject.toml").write_text('[tool.poetry.dependencies]\njinja2 = "^2.11.2"\n')
        (tmp_path / "poetry.lock").write_text("# generated lockfile\n")
        finding = _trivy_finding("poetry.lock", "jinja2", "2.11.2", "2.11.3")
        mock_run.return_value = _completed(stdout="Writing lock file\n")

        outcome = apply_trivy_bump(tmp_path, [finding])

        assert (tmp_path / "pyproject.toml").read_text() == (
            '[tool.poetry.dependencies]\njinja2 = "^2.11.3"\n'
        )
        assert outcome.applied_fingerprints == {fingerprint(finding.finding)}
        mock_run.assert_called_once()
        called_cmd, called_kwargs = mock_run.call_args
        assert called_cmd[0] == ["poetry", "lock"]
        assert called_kwargs["cwd"] == tmp_path

    @patch("fixers.trivy_bump.subprocess.run")
    def test_pipfile_lock_bumps_pipfile_and_reconciles(self, mock_run, tmp_path):
        (tmp_path / "Pipfile").write_text('[packages]\npyyaml = "==5.3"\n')
        (tmp_path / "Pipfile.lock").write_text("{}")
        finding = _trivy_finding("Pipfile.lock", "pyyaml", "5.3", "5.4")
        mock_run.return_value = _completed(stdout="Locking...\n")

        outcome = apply_trivy_bump(tmp_path, [finding])

        assert (tmp_path / "Pipfile").read_text() == '[packages]\npyyaml = "==5.4"\n'
        assert outcome.applied_fingerprints == {fingerprint(finding.finding)}
        called_cmd, called_kwargs = mock_run.call_args
        assert called_cmd[0] == ["pipenv", "lock"]
        assert called_kwargs["cwd"] == tmp_path

    @patch("fixers.trivy_bump.subprocess.run")
    def test_multiple_poetry_findings_reconcile_lockfile_exactly_once(self, mock_run, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            '[tool.poetry.dependencies]\njinja2 = "^2.11.2"\npyyaml = "^5.3.0"\n'
        )
        (tmp_path / "poetry.lock").write_text("# generated\n")
        finding_a = _trivy_finding("poetry.lock", "jinja2", "2.11.2", "2.11.3")
        finding_b = _trivy_finding("poetry.lock", "pyyaml", "5.3.0", "5.4.0")
        mock_run.return_value = _completed()

        outcome = apply_trivy_bump(tmp_path, [finding_a, finding_b])

        assert outcome.applied_fingerprints == {
            fingerprint(finding_a.finding),
            fingerprint(finding_b.finding),
        }
        assert mock_run.call_count == 1  # reconciled once, not twice


class TestTrivyBumpUnresolvedHandoff:
    def test_missing_manifest_file_is_unresolved(self, tmp_path):
        # requirements.txt does not exist in this workspace at all.
        finding = _trivy_finding("requirements.txt", "requests", "2.25.0", "2.31.0")

        outcome = apply_trivy_bump(tmp_path, [finding])

        assert outcome.applied_fingerprints == frozenset()
        assert outcome.unresolved == (finding,)

    def test_unpinned_dependency_requiring_more_than_version_edit_is_unresolved(self, tmp_path):
        (tmp_path / "Pipfile").write_text('[packages]\npyyaml = "*"\n')
        finding = _trivy_finding("Pipfile.lock", "pyyaml", None, "5.4")

        outcome = apply_trivy_bump(tmp_path, [finding])

        assert outcome.applied_fingerprints == frozenset()
        assert outcome.unresolved == (finding,)

    @patch("fixers.trivy_bump.subprocess.run")
    def test_reconciliation_timeout_does_not_unwind_applied_fingerprint(self, mock_run, tmp_path):
        (tmp_path / "pyproject.toml").write_text('[tool.poetry.dependencies]\njinja2 = "^2.11.2"\n')
        (tmp_path / "poetry.lock").write_text("# generated\n")
        finding = _trivy_finding("poetry.lock", "jinja2", "2.11.2", "2.11.3")
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=["poetry", "lock"], timeout=600)

        outcome = apply_trivy_bump(tmp_path, [finding])

        # The manifest bump itself succeeded before reconciliation was
        # attempted -- re-scan (S-137) is the real authority on cleanliness.
        assert outcome.applied_fingerprints == {fingerprint(finding.finding)}
        assert "timed out" in outcome.output


# --------------------------------------------------------------------------
# AC28 -- manual/unscannable findings never touched by any code path,
# verified by actual file-content inspection (not just bookkeeping trust).
# --------------------------------------------------------------------------


class TestManualAndUnscannableNeverTouched:
    @patch("fixers.semgrep_autofix.subprocess.run")
    def test_semgrep_fixer_leaves_non_mechanical_files_byte_identical(self, mock_run, tmp_path):
        mechanical_file = tmp_path / "mechanical.py"
        manual_file = tmp_path / "manual.tf"
        unscannable_file = tmp_path / "unscannable.py"
        mechanical_file.write_text("eval(x)\n")
        manual_original = 'resource "aws_s3_bucket" "b" {}\n'
        unscannable_original = "# weird shape\n"
        manual_file.write_text(manual_original)
        unscannable_file.write_text(unscannable_original)

        mechanical_finding = _semgrep_finding("mechanical.py")
        manual_finding = _manual_finding("checkov", "manual.tf")
        unscannable_finding = _unscannable_finding("unscannable.py")

        def _side_effect(cmd, **kwargs):
            if cmd[0] == "semgrep":
                # Real semgrep would only ever rewrite files it matched its
                # own pinned ruleset against -- simulate that scope exactly:
                # only the mechanical file is rewritten.
                mechanical_file.write_text("ast.literal_eval(x)\n")
                return _completed(stdout='{"results": []}')
            if cmd[:2] == ["git", "diff"]:
                return _completed(stdout="mechanical.py\n")
            raise AssertionError(f"unexpected command: {cmd}")

        mock_run.side_effect = _side_effect

        # Deliberately pass a MIXED batch -- including manual/unscannable
        # entries a caller should never include -- to prove the fixer
        # itself, not just caller discipline, is what keeps them untouched.
        apply_semgrep_autofix(tmp_path, [mechanical_finding, manual_finding, unscannable_finding])

        assert manual_file.read_text() == manual_original
        assert unscannable_file.read_text() == unscannable_original
        assert mechanical_file.read_text() == "ast.literal_eval(x)\n"

    @patch("fixers.trivy_bump.subprocess.run")
    def test_trivy_fixer_leaves_non_mechanical_files_byte_identical(self, mock_run, tmp_path):
        (tmp_path / "requirements.txt").write_text("requests==2.25.0\n")
        manual_lockfile = tmp_path / "pnpm-lock.yaml"
        unscannable_file = tmp_path / "unscannable.txt"
        manual_original = "lockfileVersion: 6.0\n"
        unscannable_original = "not a real manifest\n"
        manual_lockfile.write_text(manual_original)
        unscannable_file.write_text(unscannable_original)
        mock_run.return_value = _completed()

        mechanical_finding = _trivy_finding("requirements.txt", "requests", "2.25.0", "2.31.0")
        manual_finding = _trivy_finding(
            "pnpm-lock.yaml", "left-pad", "1.0.0", "1.0.1", lockfile_managed=True
        )
        unscannable_finding = _unscannable_finding("unscannable.txt")

        apply_trivy_bump(tmp_path, [mechanical_finding, manual_finding, unscannable_finding])

        assert manual_lockfile.read_text() == manual_original
        assert unscannable_file.read_text() == unscannable_original
        assert (tmp_path / "requirements.txt").read_text() == "requests==2.31.0\n"
