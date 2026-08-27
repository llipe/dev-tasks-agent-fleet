"""
Advisory classification — classifies security advisories by update eligibility (D25).

Uses the same eligibility rules as ``eligibility.py`` (req 37 — no drift).
Implements naive major extraction (PRD OQ#4 option A): regex for >=X.Y.Z patterns,
fallback to first version string, None on failure → ``unknown`` bucket.

Buckets:
  - ``in_range``: the patched version is reachable via patch/minor update.
  - ``major_required``: the patched version requires a major version bump.
  - ``unknown``: cannot determine (empty range, unparseable, non-semver installed).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from eligibility import parse_semver

# Matches >=X.Y.Z or >X.Y.Z at start of a range segment
_LOWER_BOUND_RE = re.compile(r">=?\s*(\d+\.\d+\.\d+(?:-[0-9A-Za-z\-.]+)?)")


@dataclass
class ClassifiedAdvisory:
    """A single advisory with its classification bucket and metadata."""

    id: str | int
    module: str
    severity: str
    title: str
    url: str
    cves: list[str] = field(default_factory=list)
    patched_versions: str = ""
    bucket: str = "unknown"  # "in_range" | "major_required" | "unknown"
    reason: str = ""
    lowest_patched: str | None = None


def _extract_lowest_version(patched_range: str) -> str | None:
    """
    Naive extraction: find the lowest version mentioned in a >=X.Y.Z bound.

    Falls back to the first version-like string found.
    Does NOT do full range satisfaction — uses 'unknown' bucket on failure.
    """
    # Try >=X.Y.Z patterns first (most common in audit output)
    bounds = _LOWER_BOUND_RE.findall(patched_range)
    if bounds:
        # Return the lowest (first, in most audit formats)
        return bounds[0]

    # Fallback: any version-like string
    fallback = re.findall(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z\-.]+)?", patched_range)
    if fallback:
        return fallback[0]

    return None


def classify_advisory(
    advisory: dict,
    installed_version: str,
) -> ClassifiedAdvisory:
    """
    Classify one advisory into in_range / major_required / unknown.

    Uses same eligibility rules as requirement 32 (no drift — req 37).

    Parameters
    ----------
    advisory : dict
        Raw advisory dict from audit JSON (normalized by extract_advisories).
    installed_version : str
        The currently-installed version of the affected package.
    """
    patched = advisory.get("patched_versions", "")
    module = advisory.get("module_name", advisory.get("name", "unknown"))

    base = ClassifiedAdvisory(
        id=advisory.get("id", advisory.get("github_advisory_id", "")),
        module=module,
        severity=advisory.get("severity", "unknown"),
        title=advisory.get("title", ""),
        url=advisory.get("url", ""),
        cves=advisory.get("cves", []),
        patched_versions=patched,
        bucket="unknown",
        reason="",
    )

    if not patched or patched == "<0.0.0":
        base.reason = "no_patched_range"
        return base

    sv_installed = parse_semver(installed_version)
    if sv_installed is None:
        base.reason = "installed_not_semver"
        return base

    # Extract lowest version from the patched range
    lowest = _extract_lowest_version(patched)
    if lowest is None:
        base.reason = "patched_range_unparseable"
        return base

    base.lowest_patched = lowest

    sv_target = parse_semver(lowest)
    if sv_target is None:
        base.reason = "patched_version_not_semver"
        return base

    # Use eligibility check (same rules as req 32)
    inst_major, inst_minor, _ = sv_installed
    tgt_major, tgt_minor, _ = sv_target

    if tgt_major > inst_major:
        base.bucket = "major_required"
        base.reason = "major_increase"
        return base

    if inst_major == 0 and tgt_major == 0 and tgt_minor > inst_minor:
        base.bucket = "major_required"
        base.reason = "zero_minor_increase"
        return base

    base.bucket = "in_range"
    base.reason = "patch_or_minor"
    return base
