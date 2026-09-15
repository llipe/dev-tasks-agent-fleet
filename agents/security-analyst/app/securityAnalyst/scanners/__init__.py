"""
Scanner subpackage (spec S8.5) — one module per tool (`semgrep_runner.py`,
and, from S-129-S-132 onward, `gitleaks_runner.py`, `trivy_runner.py`,
`checkov_runner.py`, `codeql_runner.py`), sharing the common
`ScanStatus`/`ScanResult` shape defined in `scanners.types`.

Generalizes the sibling agent's (dependency-update) `validator.py`
`CheckStatus`/multi-check-runner pattern to five independent scanner
subprocess calls, each with its own timeout envelope and non-fatal
crash/timeout/unparseable-output handling (PRD requirements 15-19).
"""

from __future__ import annotations
