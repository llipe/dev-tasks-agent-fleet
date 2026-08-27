"""Unit tests for toolchain detection module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from toolchain import (
    ToolchainError,
    detect_package_manager,
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
