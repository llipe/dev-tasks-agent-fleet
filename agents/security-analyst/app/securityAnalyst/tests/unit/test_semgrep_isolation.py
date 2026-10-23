"""Pins semgrep's isolation from the agent's dependency tree (issue #360, path B).

semgrep pins its transitive dependencies exactly or narrowly (``mcp==1.29.0``,
``opentelemetry-api~=1.37.0``) in every release through 1.182.1, which kept
CVE-2026-59951 and CVE-2026-114603 in the agent's resolved environment and
failed ``pip-audit --strict``. semgrep is only ever run as a CLI subprocess
(``scanners/semgrep_runner.py``, ``fixers/semgrep_autofix.py``), so it lives in
its own venv in the image, like gitleaks/trivy/CodeQL live outside the
resolver. These tests keep it from drifting back.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parents[2]


def _dependency_names() -> set[str]:
    project = tomllib.loads((PKG_DIR / "pyproject.toml").read_text())["project"]
    specs = list(project["dependencies"])
    for extra in project.get("optional-dependencies", {}).values():
        specs.extend(extra)
    return {re.split(r"[\s<>=!~\[;]", spec, maxsplit=1)[0].lower() for spec in specs}


def test_semgrep_is_not_a_python_dependency() -> None:
    assert "semgrep" not in _dependency_names()


def test_dockerfile_installs_semgrep_in_its_own_venv_on_path() -> None:
    dockerfile = (PKG_DIR / "Dockerfile").read_text()
    assert re.search(r"python -m venv /opt/semgrep\b", dockerfile)
    assert re.search(
        r"/opt/semgrep/bin/pip install [^\n]*semgrep==\$\{SEMGREP_VERSION\}", dockerfile
    )
    assert re.search(r"ARG SEMGREP_VERSION=\d+\.\d+\.\d+\n", dockerfile)
    assert "ln -s /opt/semgrep/bin/semgrep /usr/local/bin/semgrep" in dockerfile
    # The venv install is the only one: a `pip install semgrep` into the
    # image's main Python would pass pip-audit (it audits declared deps only)
    # while putting the pinned CVEs back next to the agent.
    assert len(re.findall(r"semgrep==", dockerfile)) == 1


def test_audit_runs_strict_with_no_ignored_vulnerabilities() -> None:
    makefile = (PKG_DIR / "Makefile").read_text()
    assert "\tpip-audit . --strict\n" in makefile
    assert "--ignore-vuln" not in makefile
    assert "AUDIT_EXCEPTION_EXPIRES" not in makefile
