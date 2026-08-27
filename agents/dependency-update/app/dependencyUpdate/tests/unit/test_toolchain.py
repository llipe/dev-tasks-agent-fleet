"""Unit tests for toolchain detection module."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from toolchain import (
    ToolchainError,
    detect_package_manager,
    detect_pnpm_version,
    detect_scripts,
    ensure_pnpm_version,
)


def _write_package_json(workspace: Path, data: dict) -> None:
    (workspace / "package.json").write_text(json.dumps(data), encoding="utf-8")


class TestDetectPackageManager:
    def test_detects_pnpm_from_package_manager_field(self, tmp_path: Path):
        _write_package_json(tmp_path, {"packageManager": "pnpm@9.1.0"})
        # A stray lockfile must not override the explicit packageManager field.
        (tmp_path / "package-lock.json").write_text("{}", encoding="utf-8")
        assert detect_package_manager(str(tmp_path)) == "pnpm"

    def test_detects_npm_from_package_manager_field(self, tmp_path: Path):
        _write_package_json(tmp_path, {"packageManager": "npm@10.2.0"})
        assert detect_package_manager(str(tmp_path)) == "npm"

    def test_detects_pnpm_from_lockfile(self, tmp_path: Path):
        _write_package_json(tmp_path, {"name": "x"})
        (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
        assert detect_package_manager(str(tmp_path)) == "pnpm"

    def test_detects_npm_from_lockfile(self, tmp_path: Path):
        _write_package_json(tmp_path, {"name": "x"})
        (tmp_path / "package-lock.json").write_text("{}", encoding="utf-8")
        assert detect_package_manager(str(tmp_path)) == "npm"

    def test_pnpm_lock_takes_precedence_over_npm_lock(self, tmp_path: Path):
        _write_package_json(tmp_path, {"name": "x"})
        (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
        (tmp_path / "package-lock.json").write_text("{}", encoding="utf-8")
        assert detect_package_manager(str(tmp_path)) == "pnpm"

    def test_no_lockfile_raises_no_package_manager(self, tmp_path: Path):
        _write_package_json(tmp_path, {"name": "x"})
        with pytest.raises(ToolchainError) as exc_info:
            detect_package_manager(str(tmp_path))
        assert exc_info.value.code == "NO_PACKAGE_MANAGER"

    def test_missing_package_json_raises_no_package_manager(self, tmp_path: Path):
        with pytest.raises(ToolchainError) as exc_info:
            detect_package_manager(str(tmp_path))
        assert exc_info.value.code == "NO_PACKAGE_MANAGER"

    def test_error_message_names_what_was_searched(self, tmp_path: Path):
        _write_package_json(tmp_path, {"name": "x"})
        with pytest.raises(ToolchainError) as exc_info:
            detect_package_manager(str(tmp_path))
        msg = exc_info.value.message
        assert "pnpm-lock.yaml" in msg
        assert "package-lock.json" in msg

    def test_unrecognized_package_manager_field_falls_back_to_lockfile(self, tmp_path: Path):
        # yarn is not supported; detection should ignore the field and use the lockfile.
        _write_package_json(tmp_path, {"packageManager": "yarn@4.0.0"})
        (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
        assert detect_package_manager(str(tmp_path)) == "pnpm"

    def test_malformed_package_json_falls_back_to_lockfile(self, tmp_path: Path):
        (tmp_path / "package.json").write_text("{ not valid json", encoding="utf-8")
        (tmp_path / "package-lock.json").write_text("{}", encoding="utf-8")
        assert detect_package_manager(str(tmp_path)) == "npm"


class TestDetectPnpmVersion:
    def test_from_package_manager_field(self, tmp_path: Path):
        _write_package_json(tmp_path, {"packageManager": "pnpm@9.1.0"})
        assert detect_pnpm_version(str(tmp_path)) == 9

    def test_package_manager_field_wins_over_lockfile(self, tmp_path: Path):
        _write_package_json(tmp_path, {"packageManager": "pnpm@8.15.0"})
        (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
        assert detect_pnpm_version(str(tmp_path)) == 8

    def test_from_lockfile_version_9(self, tmp_path: Path):
        _write_package_json(tmp_path, {"name": "x"})
        (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
        assert detect_pnpm_version(str(tmp_path)) == 9

    def test_from_lockfile_version_6_maps_to_pnpm_8(self, tmp_path: Path):
        _write_package_json(tmp_path, {"name": "x"})
        (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '6.0'\n", encoding="utf-8")
        assert detect_pnpm_version(str(tmp_path)) == 8

    def test_from_lockfile_version_5_maps_to_pnpm_7(self, tmp_path: Path):
        _write_package_json(tmp_path, {"name": "x"})
        (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: 5.4\n", encoding="utf-8")
        assert detect_pnpm_version(str(tmp_path)) == 7

    def test_lockfile_version_without_quotes(self, tmp_path: Path):
        _write_package_json(tmp_path, {"name": "x"})
        (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: 9.0\n", encoding="utf-8")
        assert detect_pnpm_version(str(tmp_path)) == 9

    def test_returns_none_when_undeterminable(self, tmp_path: Path):
        _write_package_json(tmp_path, {"name": "x"})
        (tmp_path / "pnpm-lock.yaml").write_text("packages:\n  foo: {}\n", encoding="utf-8")
        assert detect_pnpm_version(str(tmp_path)) is None

    def test_returns_none_when_no_pnpm_evidence(self, tmp_path: Path):
        _write_package_json(tmp_path, {"name": "x"})
        assert detect_pnpm_version(str(tmp_path)) is None

    def test_unknown_lockfile_version_returns_none(self, tmp_path: Path):
        _write_package_json(tmp_path, {"name": "x"})
        (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '3.0'\n", encoding="utf-8")
        assert detect_pnpm_version(str(tmp_path)) is None


class TestEnsurePnpmVersion:
    @patch("toolchain._current_pnpm_major", return_value=9)
    @patch("toolchain._run")
    def test_no_install_when_version_matches(self, mock_run, mock_current, tmp_path: Path):
        _write_package_json(tmp_path, {"packageManager": "pnpm@9.1.0"})
        ensure_pnpm_version(str(tmp_path))
        mock_run.assert_not_called()

    @patch("toolchain._current_pnpm_major", return_value=9)
    @patch("toolchain._run")
    def test_installs_when_major_differs(self, mock_run, mock_current, tmp_path: Path):
        _write_package_json(tmp_path, {"packageManager": "pnpm@8.15.0"})
        ensure_pnpm_version(str(tmp_path))
        assert mock_run.call_count == 1
        args = mock_run.call_args[0][0]
        # Installs the required major, e.g. `npm install -g pnpm@8`.
        assert any("pnpm@8" in str(a) for a in args)

    @patch("toolchain._current_pnpm_major", return_value=9)
    @patch("toolchain._run")
    def test_noop_when_required_version_undeterminable(
        self, mock_run, mock_current, tmp_path: Path
    ):
        _write_package_json(tmp_path, {"name": "x"})
        ensure_pnpm_version(str(tmp_path))
        mock_run.assert_not_called()

    @patch("toolchain._current_pnpm_major", return_value=None)
    @patch("toolchain._run")
    def test_installs_when_current_unknown(self, mock_run, mock_current, tmp_path: Path):
        _write_package_json(tmp_path, {"packageManager": "pnpm@8.15.0"})
        ensure_pnpm_version(str(tmp_path))
        assert mock_run.call_count == 1


class TestDetectScripts:
    def test_test_script_required_present(self, tmp_path: Path):
        _write_package_json(tmp_path, {"scripts": {"test": "vitest run"}})
        contract = detect_scripts(str(tmp_path))
        assert contract.test == "test"

    def test_missing_test_raises_no_test_script(self, tmp_path: Path):
        _write_package_json(tmp_path, {"scripts": {"lint": "eslint ."}})
        with pytest.raises(ToolchainError) as exc_info:
            detect_scripts(str(tmp_path))
        assert exc_info.value.code == "NO_TEST_SCRIPT"

    def test_no_scripts_at_all_raises_no_test_script(self, tmp_path: Path):
        _write_package_json(tmp_path, {"name": "x"})
        with pytest.raises(ToolchainError) as exc_info:
            detect_scripts(str(tmp_path))
        assert exc_info.value.code == "NO_TEST_SCRIPT"

    def test_detects_all_optional_scripts(self, tmp_path: Path):
        _write_package_json(
            tmp_path,
            {"scripts": {"test": "t", "lint": "l", "format": "f", "typecheck": "tc"}},
        )
        contract = detect_scripts(str(tmp_path))
        assert contract.lint == "lint"
        assert contract.format == "format"
        assert contract.typecheck == "typecheck"
        assert contract.missing_optional == []

    def test_detects_lint_fix_variant(self, tmp_path: Path):
        _write_package_json(tmp_path, {"scripts": {"test": "t", "lint": "l", "lint:fix": "lf"}})
        contract = detect_scripts(str(tmp_path))
        assert contract.lint_fix == "lint:fix"

    def test_detects_format_check_variant(self, tmp_path: Path):
        _write_package_json(tmp_path, {"scripts": {"test": "t", "format:check": "fc"}})
        contract = detect_scripts(str(tmp_path))
        # format:check satisfies the "format" logical check
        assert contract.format == "format:check"

    def test_detects_format_fix_variant(self, tmp_path: Path):
        _write_package_json(tmp_path, {"scripts": {"test": "t", "format": "f", "format:fix": "ff"}})
        contract = detect_scripts(str(tmp_path))
        assert contract.format_fix == "format:fix"

    def test_detects_type_check_hyphen_variant(self, tmp_path: Path):
        _write_package_json(tmp_path, {"scripts": {"test": "t", "type-check": "tsc --noEmit"}})
        contract = detect_scripts(str(tmp_path))
        assert contract.typecheck == "type-check"

    def test_missing_optional_scripts_listed(self, tmp_path: Path):
        _write_package_json(tmp_path, {"scripts": {"test": "t"}})
        contract = detect_scripts(str(tmp_path))
        assert set(contract.missing_optional) == {"lint", "format", "typecheck"}
        assert contract.lint is None
        assert contract.format is None
        assert contract.typecheck is None

    def test_canonical_name_preferred_over_variant(self, tmp_path: Path):
        # When both `format` and `format:check` exist, prefer canonical `format`.
        _write_package_json(
            tmp_path, {"scripts": {"test": "t", "format": "f", "format:check": "fc"}}
        )
        contract = detect_scripts(str(tmp_path))
        assert contract.format == "format"


class TestAcceptanceCriteria:
    """AC verification via the shared temp-dir project fixtures (conftest.py)."""

    def test_ac_pnpm_project_detected(self, pnpm_project):
        assert detect_package_manager(pnpm_project) == "pnpm"
        assert detect_pnpm_version(pnpm_project) == 9

    def test_ac_npm_project_detected(self, npm_project):
        assert detect_package_manager(npm_project) == "npm"

    def test_ac_no_package_manager_on_empty_fixture(self, no_lockfile_project):
        # AC (2.11): NO_PACKAGE_MANAGER when no lockfile matches.
        with pytest.raises(ToolchainError) as exc_info:
            detect_package_manager(no_lockfile_project)
        assert exc_info.value.code == "NO_PACKAGE_MANAGER"

    def test_ac_no_test_script_fixture(self, no_test_project):
        # AC (2.12): NO_TEST_SCRIPT when the test script is absent.
        with pytest.raises(ToolchainError) as exc_info:
            detect_scripts(no_test_project)
        assert exc_info.value.code == "NO_TEST_SCRIPT"

    def test_ac_absent_optional_scripts_surfaced_for_warnings(self, minimal_test_project):
        # AC (2.13): the contract exposes absent optional scripts so the
        # orchestrator can emit a warn event per missing script.
        contract = detect_scripts(minimal_test_project)
        assert set(contract.missing_optional) == {"lint", "format", "typecheck"}
