"""
Severity normalization (spec S8.1a, PRD S7.4b / D28-D30).

Five tools, five native severity taxonomies, two of them (Gitleaks, Checkov's
open-source checks) with no native severity at all. Each ``severity_from_*``
function below is a pure, total, deterministic mapping over the exact
fields named in PRD S7.4b's requirement-58 table -- never a heuristic, never
delegated to the LLM, and never inspecting free-text rule metadata beyond
those named fields (requirement 61).

Deviation from spec S8.1a (confirmed by planner, not a task-list deviation):
the spec's literal ``severity_from_semgrep`` uses raw dict indexing
(``{"ERROR": ...}[raw_severity]``), which raises ``KeyError`` on an
out-of-table value instead of falling to the shared unknown-severity floor.
That is inconsistent with the other four functions' defensive
``.get(..., floor)`` pattern and with requirement 58's own framing that
every ``Finding`` MUST carry a normalized severity. This was flagged by the
S-125 fidelity audit (test plan RT-4) as a discrepancy to fix, not to
replicate -- ``severity_from_semgrep`` below uses the same ``.get(...,
floor)`` pattern as the other four functions.

The same reasoning applies to ``severity_from_checkov``'s present-value
branch: spec S8.1a's literal raw indexing there would equally ``KeyError``
on an out-of-table non-``None`` Checkov severity string. Confirmed by the
S-126 fidelity audit as a second instance of the same fix, not a separate
deviation -- it uses the identical ``.get(..., floor)`` pattern.
"""

from __future__ import annotations

from enum import Enum


class Severity(Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# D30 -- shared across all tools' "no signal" case (Trivy UNKNOWN, Checkov's
# unset OSS severity, CodeQL with neither security-severity nor a usable
# level, and -- per this module's spec-deviation fix -- an out-of-table
# Semgrep value).
_UNKNOWN_SEVERITY_FLOOR = Severity.MEDIUM


def severity_from_semgrep(raw_severity: str) -> Severity:
    """Semgrep `results[].extra.severity` -> Severity (PRD req 58 row 1).

    ``ERROR -> high``, ``WARNING -> medium``, ``INFO -> low``. Semgrep never
    yields ``critical`` on its own. Total: an out-of-table value falls to
    the shared unknown-severity floor rather than raising (see module
    docstring -- deviation from the spec's literal raw-indexing form).
    """
    mapping = {
        "ERROR": Severity.HIGH,
        "WARNING": Severity.MEDIUM,
        "INFO": Severity.LOW,
    }
    return mapping.get(raw_severity, _UNKNOWN_SEVERITY_FLOOR)


def severity_from_gitleaks(_finding: dict) -> Severity:
    """Gitleaks findings carry no native severity field (PRD req 58 row 2).

    Always ``critical``, unconditionally, no per-rule exception -- D29. The
    finding dict is accepted (and ignored) only to keep the call site
    uniform with the other ``normalize_<tool>()`` callers; no field of it,
    named or otherwise, is inspected.
    """
    return Severity.CRITICAL


def severity_from_trivy(raw_severity: str) -> Severity:
    """Trivy `Vulnerabilities[].Severity` / `Misconfigurations[].Severity`
    -> Severity (PRD req 58 row 3).

    Direct pass-through for the four named levels; ``UNKNOWN`` (and any
    other out-of-table value) falls to the shared unknown-severity floor
    (requirement 60).
    """
    mapping = {
        "CRITICAL": Severity.CRITICAL,
        "HIGH": Severity.HIGH,
        "MEDIUM": Severity.MEDIUM,
        "LOW": Severity.LOW,
    }
    return mapping.get(raw_severity, _UNKNOWN_SEVERITY_FLOOR)


def severity_from_checkov(raw_severity: str | None) -> Severity:
    """Checkov `results.failed_checks[].severity` -> Severity (PRD req 58
    row 4).

    Present only when the check carries a Bridgecrew-assigned or custom
    severity; absent on plain OSS checks (the common case). When present,
    direct pass-through; when absent, falls to the shared unknown-severity
    floor (requirement 60). An out-of-table non-``None`` value also falls
    to the floor rather than raising -- the same defensive ``.get(...,
    floor)`` fix as ``severity_from_semgrep`` (see module docstring).
    """
    if raw_severity is None:
        return _UNKNOWN_SEVERITY_FLOOR
    mapping = {
        "CRITICAL": Severity.CRITICAL,
        "HIGH": Severity.HIGH,
        "MEDIUM": Severity.MEDIUM,
        "LOW": Severity.LOW,
    }
    return mapping.get(raw_severity, _UNKNOWN_SEVERITY_FLOOR)


def severity_from_codeql(security_severity: float | None, level: str | None) -> Severity:
    """CodeQL SARIF `results[].properties.security-severity` (a 0.0-10.0
    CVSS-like float) when present, else SARIF `level` -> Severity (PRD req
    58 row 5, AC-12a dual fallback).

    ``security-severity`` thresholds: ``>=9.0 -> critical``, ``>=7.0 ->
    high``, ``>=4.0 -> medium``, else ``low``. When ``security-severity`` is
    absent, falls back to ``level`` (``error -> high``, ``warning ->
    medium``, ``note -> low``). When neither signal is present (or ``level``
    is out-of-table), falls to the shared unknown-severity floor
    (requirement 60).
    """
    if security_severity is not None:
        if security_severity >= 9.0:
            return Severity.CRITICAL
        if security_severity >= 7.0:
            return Severity.HIGH
        if security_severity >= 4.0:
            return Severity.MEDIUM
        return Severity.LOW
    if level is not None:
        return {
            "error": Severity.HIGH,
            "warning": Severity.MEDIUM,
            "note": Severity.LOW,
        }.get(level, _UNKNOWN_SEVERITY_FLOOR)
    return _UNKNOWN_SEVERITY_FLOOR
