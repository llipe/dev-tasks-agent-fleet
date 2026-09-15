"""
Normalized finding schema (spec S8.1).

``Finding`` is the single shape every scanner's ``normalize_<tool>()``
function (S-128-S-132) converts its tool-native output into -- the common
currency every downstream stage (fingerprinting, cross-tool dedup,
classification, fix application, the re-scan gate, and PR body rendering)
operates on. ``Remediation`` is its nested, optional (``None`` for an
unscannable candidate) sub-record describing how -- if at all -- a finding
can be mechanically fixed.

Both are frozen (immutable) dataclasses: a ``Finding`` is a fact about a
point-in-time scan result, never mutated in place once constructed --
downstream stages that need a modified view (e.g. dedup's merged record)
build a new value rather than assigning back into an existing ``Finding``.
"""

from __future__ import annotations

from dataclasses import dataclass

from severity import Severity


@dataclass(frozen=True)
class Remediation:
    """How (if at all) a ``Finding`` can be mechanically fixed (spec S8.1).

    ``kind`` is one of ``"semgrep_autofix"`` | ``"version_bump"`` |
    ``"structural"`` | ``"none"`` -- the classifier (S-134) is the sole
    writer of this field's value; this module only defines the shape.
    """

    kind: str
    patch: str | None
    target_version: str | None
    lockfile_managed: bool


@dataclass(frozen=True)
class Finding:
    """A single normalized security finding, tool-agnostic (spec S8.1).

    ``remediation`` is ``None`` for an unscannable candidate (no mechanical
    fix path exists); ``raw_ref`` is a pointer into the raw per-tool output
    artifact for traceability -- the raw payload itself is never embedded
    here, keeping this record small and stable across tools.
    """

    tool: str
    rule_id: str
    severity: Severity
    file_path: str
    line_start: int
    line_end: int
    message: str
    cwe_or_category: str
    remediation: Remediation | None
    raw_ref: str
