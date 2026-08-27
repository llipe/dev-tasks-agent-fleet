"""
Shared pytest fixtures — temp-dir JS project shapes for toolchain/validator tests.

Each fixture returns the path to a freshly-built project directory under the
test's ``tmp_path``, covering the package-manager and script-contract cases the
detection code must handle:

    pnpm_project     — packageManager: pnpm + pnpm-lock.yaml + full script set
    npm_project      — package-lock.json + full script set
    no_lockfile      — package.json only, no lockfile (NO_PACKAGE_MANAGER)
    no_test_project  — has a lockfile but no `test` script (NO_TEST_SCRIPT)
    minimal_test     — has a lockfile and only a `test` script (optional absent)
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


def pytest_collection_modifyitems(config, items):
    """Auto-apply layer markers based on the test's directory.

    Tests under ``tests/unit/`` get the ``unit`` marker and those under
    ``tests/component/`` get ``component`` so the canonical
    ``pytest -m unit`` / ``pytest -m component`` selectors work without each
    test declaring the marker by hand.
    """
    for item in items:
        path = str(item.fspath)
        if f"{os.sep}tests{os.sep}unit{os.sep}" in path:
            item.add_marker(pytest.mark.unit)
        elif f"{os.sep}tests{os.sep}component{os.sep}" in path:
            item.add_marker(pytest.mark.component)


_FULL_SCRIPTS = {
    "test": "vitest run",
    "lint": "eslint .",
    "format": "prettier --check .",
    "typecheck": "tsc --noEmit",
    "lint:fix": "eslint . --fix",
    "format:fix": "prettier --write .",
}


def _write_pkg(root: Path, data: dict) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "package.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


@pytest.fixture
def pnpm_project(tmp_path: Path) -> str:
    root = tmp_path / "pnpm_project"
    _write_pkg(
        root, {"name": "pnpm-fixture", "packageManager": "pnpm@9.1.0", "scripts": _FULL_SCRIPTS}
    )
    (root / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
    return str(root)


@pytest.fixture
def npm_project(tmp_path: Path) -> str:
    root = tmp_path / "npm_project"
    _write_pkg(root, {"name": "npm-fixture", "scripts": _FULL_SCRIPTS})
    (root / "package-lock.json").write_text('{"lockfileVersion": 3}', encoding="utf-8")
    return str(root)


@pytest.fixture
def no_lockfile_project(tmp_path: Path) -> str:
    root = tmp_path / "no_lockfile"
    _write_pkg(root, {"name": "no-lock", "scripts": _FULL_SCRIPTS})
    return str(root)


@pytest.fixture
def no_test_project(tmp_path: Path) -> str:
    root = tmp_path / "no_test"
    _write_pkg(root, {"name": "no-test", "scripts": {"lint": "eslint ."}})
    (root / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
    return str(root)


@pytest.fixture
def minimal_test_project(tmp_path: Path) -> str:
    root = tmp_path / "minimal_test"
    _write_pkg(root, {"name": "minimal", "scripts": {"test": "vitest run"}})
    (root / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
    return str(root)
