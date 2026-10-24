"""CT-32: the marker grammar between runs (D-53, D-80, D-104).

Golden comment bodies under ``tests/fixtures/contract/markers/`` record what a
deployed run's ``markers.py`` writes. A newer parser must read them to the same
(kind, run_id, reason) tuples, and today's builder must still write them byte
for byte, so an older run and a newer one agree on which claims are open.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from markers import Marker, build, parse_block

GOLDEN_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "contract" / "markers"
EXPECTED = json.loads((GOLDEN_DIR / "expected.json").read_text())


def test_every_golden_is_listed():
    files = sorted(p.name for p in GOLDEN_DIR.glob("*.md"))
    assert files == sorted(EXPECTED)
    assert len(files) >= 11  # three kinds, six reasons, a two-marker block, a CRLF body


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_golden_parses_to_recorded_tuples(name):
    body = (GOLDEN_DIR / name).read_bytes().decode("utf-8")
    want = tuple(Marker(k, r, reason) for k, r, reason in EXPECTED[name])
    assert parse_block(body) == want


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_builder_still_writes_the_golden_first_lines(name):
    body = (GOLDEN_DIR / name).read_bytes().decode("utf-8")
    lines = body.replace("\r\n", "\n").split("\n")
    for line, (kind, run_id, reason) in zip(lines, EXPECTED[name], strict=False):
        assert build(kind, run_id, reason) == line
