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

    ``current_version`` (added by S-134, defaulted so every existing
    ``Remediation(...)`` call site across the four already-merged scanner
    normalizers stays valid unchanged) is the finding's pre-fix resolved
    version -- e.g. Trivy's own ``InstalledVersion`` field -- paired with
    ``target_version`` so ``classifier.py``'s ``_is_major_bump()`` can
    determine whether a ``version_bump`` remediation crosses a major
    version (spec §8.4, PRD requirement 27) without re-deriving it from
    scanner-specific raw output. Spec §8.4's own pseudocode calls
    ``_is_major_bump(f)`` with the whole `Finding` and expects it to know
    "the bump," but neither `normalize.py` nor `trivy_runner.py` (S-130,
    already merged) previously carried a pre-fix version anywhere on the
    normalized schema -- `Finding.message` is free text (a CVE title/
    description) with no reliably-parseable version in it. This field is
    the minimal, additive fix: `None` for every remediation kind that has
    no notion of "current version" (``semgrep_autofix``, ``structural``),
    and populated only by ``trivy_runner.py``'s ``version_bump`` branch
    (updated in this same story) from Trivy's ``InstalledVersion``. This is
    the same class of pre-authorized "apply proactively" correctness fix as
    prior stories' scanner-runner deviations (flagged in this story's
    completion report for `verifier`'s audit).

    ``package_name`` (added by S-136, defaulted for the same backward-
    compatibility reason as ``current_version`` above) is the ecosystem
    package identifier a ``version_bump`` remediation applies to -- e.g.
    Trivy's own ``PkgName`` field. Neither spec §8.1's `Remediation` shape
    nor any existing field on `Finding` carries this: `rule_id` is the
    advisory/CVE identifier (not the package), and `message` is free text
    with no reliably-parseable package name in it. Without it,
    `fixers/trivy_bump.py` (this same story) would have no deterministic
    way to locate *which* line of a manifest file to edit -- it cannot
    safely infer the package from `file_path` (a manifest lists many
    packages) or from `current_version` alone (two packages can coincide
    on the same pinned version). This is the same class of minimal,
    additive schema fix as `current_version` (S-134) -- populated only by
    `trivy_runner.py`'s `version_bump` branch (this story), `None` for
    every other remediation kind and for the four other scanner
    normalizers, which stay unchanged.
    """

    kind: str
    patch: str | None
    target_version: str | None
    lockfile_managed: bool
    current_version: str | None = None
    package_name: str | None = None


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
