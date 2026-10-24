"""L1 source scan: no label, owner or project default in agent code (TC-184-11; D-82, D-93).

Issue mode has no label or assignee params, and the agent invents no
``project`` default. Budget, cap and status-name defaults are allowed in code
only as ``params.DEFAULTS``, which CT-21 checks against the seed.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[2]

# probe.py is the S-182 spike probe (D-105): it targets the fixed board-probe
# repo `llipe/dev-tasks` by design and runs only with ALLOW_PROBE=1 (D-70). It
# is never on a real run's path, so the owner literal is allowed there only.
OWNER_LITERAL_ALLOWED = {"probe.py"}

SOURCES = sorted(p for p in PKG.glob("*.py") if p.name != "__init__.py")

LABEL_LITERALS = ["status: ready", "type: bug", "status: in-progress", "status: needs-refinement"]


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_no_label_literal(path: Path) -> None:
    text = path.read_text().lower()
    for label in LABEL_LITERALS:
        assert label not in text, f"{path.name} holds the label literal {label!r}"


@pytest.mark.parametrize(
    "path", [p for p in SOURCES if p.name not in OWNER_LITERAL_ALLOWED], ids=lambda p: p.name
)
def test_no_owner_literal(path: Path) -> None:
    assert '"llipe' not in path.read_text(), f"{path.name} holds an owner literal"


def test_params_has_no_project_or_label_default() -> None:
    text = (PKG / "params.py").read_text()
    assert not re.search(r'"project"\s*:', text), "params.py must not default `project`"
    assert "label" not in text.lower(), "params.py must not mention label params"
    assert "assignee" not in text.lower(), "params.py must not mention an assignee param"


def test_sources_were_found() -> None:
    assert any(p.name == "params.py" for p in SOURCES)
