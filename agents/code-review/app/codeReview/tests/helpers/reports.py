"""
Fidelity-report fixture loader (S-208).

The report fixtures live in ``tests/fixtures/reports/``. ``report_text`` reads
the bytes and decodes UTF-8, so the text is byte-identical to the file
(``Path.read_text`` would translate line endings on some platforms).
"""

from __future__ import annotations

from pathlib import Path

REPORTS = Path(__file__).resolve().parents[1] / "fixtures" / "reports"


def report_text(name: str) -> str:
    """The content of ``tests/fixtures/reports/<name>``, decoded as UTF-8."""
    return (REPORTS / name).read_bytes().decode("utf-8")
