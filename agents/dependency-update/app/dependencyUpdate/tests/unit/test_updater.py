"""
Unit tests for updater.py — install / update / lockfile reconciliation.

Focus: the package-manager command contract. The dep-type set pnpm installs
with must stay consistent across install → update → reconcile, otherwise pnpm
aborts with ERR_PNPM_INCLUDED_DEPS_CONFLICT (found by the issue #77 E2E run on
a real repo).
"""

from __future__ import annotations

import subprocess

import pytest

from updater import (
    UpdaterError,
    has_changes,
    install_deps,
    reconcile_lockfile,
    update_packages,
)


class _Recorder:
    """Captures the commands subprocess.run was called with."""

    def __init__(self, returncode=0, stdout="", stderr=""):
        self.calls: list[list[str]] = []
        self._returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    def __call__(self, cmd, **kwargs):
        self.calls.append(cmd)
        if self._returncode != 0:
            raise subprocess.CalledProcessError(
                self._returncode, cmd, output=self._stdout, stderr=self._stderr
            )
        return subprocess.CompletedProcess(cmd, 0, self._stdout, self._stderr)


# ---------------------------------------------------------------------------
# install_deps
# ---------------------------------------------------------------------------


class TestInstallDeps:
    def test_pnpm_frozen(self, monkeypatch):
        rec = _Recorder(stdout="ok")
        monkeypatch.setattr(subprocess, "run", rec)
        install_deps("/ws", "pnpm", frozen=True)
        assert rec.calls[0] == ["pnpm", "install", "--frozen-lockfile"]

    def test_pnpm_mutable(self, monkeypatch):
        rec = _Recorder()
        monkeypatch.setattr(subprocess, "run", rec)
        install_deps("/ws", "pnpm", frozen=False)
        assert rec.calls[0] == ["pnpm", "install"]

    def test_npm_frozen_uses_ci(self, monkeypatch):
        rec = _Recorder()
        monkeypatch.setattr(subprocess, "run", rec)
        install_deps("/ws", "npm", frozen=True)
        assert rec.calls[0] == ["npm", "ci"]

    def test_npm_mutable(self, monkeypatch):
        rec = _Recorder()
        monkeypatch.setattr(subprocess, "run", rec)
        install_deps("/ws", "npm", frozen=False)
        assert rec.calls[0] == ["npm", "install"]

    def test_failure_raises_install_failed(self, monkeypatch):
        rec = _Recorder(returncode=1, stderr="boom")
        monkeypatch.setattr(subprocess, "run", rec)
        with pytest.raises(UpdaterError) as exc:
            install_deps("/ws", "pnpm")
        assert exc.value.code == "INSTALL_FAILED"
        assert "boom" in exc.value.message


# ---------------------------------------------------------------------------
# update_packages — the ERR_PNPM_INCLUDED_DEPS_CONFLICT regression
# ---------------------------------------------------------------------------


class TestUpdatePackages:
    def test_pnpm_update_does_not_exclude_optional(self, monkeypatch):
        """
        Regression (issue #77): `pnpm update --no-optional` after a full
        `pnpm install --frozen-lockfile` aborts with
        ERR_PNPM_INCLUDED_DEPS_CONFLICT, because the modules directory was
        installed with optionalDependencies but the update wants a narrower set.
        The update MUST use the same dep-type set as the install.
        """
        rec = _Recorder()
        monkeypatch.setattr(subprocess, "run", rec)
        update_packages("/ws", "pnpm")
        assert "--no-optional" not in rec.calls[0], (
            "pnpm update must not narrow the dep-type set relative to install "
            "(ERR_PNPM_INCLUDED_DEPS_CONFLICT)"
        )
        assert rec.calls[0] == ["pnpm", "update"]

    def test_npm_update(self, monkeypatch):
        rec = _Recorder()
        monkeypatch.setattr(subprocess, "run", rec)
        update_packages("/ws", "npm")
        assert rec.calls[0] == ["npm", "update"]

    def test_failure_raises_update_failed(self, monkeypatch):
        rec = _Recorder(returncode=1, stderr="ERR_PNPM_INCLUDED_DEPS_CONFLICT")
        monkeypatch.setattr(subprocess, "run", rec)
        with pytest.raises(UpdaterError) as exc:
            update_packages("/ws", "pnpm")
        assert exc.value.code == "UPDATE_FAILED"


class TestInstallUpdateConsistency:
    """The install and update commands must agree on which dep types are included."""

    def test_pnpm_install_and_update_share_dep_type_flags(self, monkeypatch):
        rec = _Recorder()
        monkeypatch.setattr(subprocess, "run", rec)
        install_deps("/ws", "pnpm", frozen=True)
        update_packages("/ws", "pnpm")
        reconcile_lockfile("/ws", "pnpm")

        dep_flags = {"--no-optional", "--prod", "--no-dev"}
        for cmd in rec.calls:
            assert not (dep_flags & set(cmd)), (
                f"dep-type-narrowing flag in {cmd} would desync node_modules/.modules.yaml"
            )


# ---------------------------------------------------------------------------
# has_changes / reconcile_lockfile
# ---------------------------------------------------------------------------


class TestHasChanges:
    def test_true_when_porcelain_output(self, monkeypatch):
        rec = _Recorder(stdout=" M package.json\n")
        monkeypatch.setattr(subprocess, "run", rec)
        assert has_changes("/ws") is True

    def test_false_when_clean(self, monkeypatch):
        rec = _Recorder(stdout="")
        monkeypatch.setattr(subprocess, "run", rec)
        assert has_changes("/ws") is False

    def test_whitespace_only_is_clean(self, monkeypatch):
        rec = _Recorder(stdout="   \n  ")
        monkeypatch.setattr(subprocess, "run", rec)
        assert has_changes("/ws") is False


class TestReconcileLockfile:
    def test_runs_mutable_install(self, monkeypatch):
        rec = _Recorder()
        monkeypatch.setattr(subprocess, "run", rec)
        reconcile_lockfile("/ws", "pnpm")
        assert rec.calls[0] == ["pnpm", "install"]
        assert "--frozen-lockfile" not in rec.calls[0]
