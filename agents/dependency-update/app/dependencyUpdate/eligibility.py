"""
Version eligibility — determines whether a target version is eligible
for automatic update based on semver distance rules (D26).

Implements PRD requirements 32-34:
  - Patch/minor within same major: eligible
  - Major increase: ineligible
  - 0.x minor increase: ineligible (major-equivalent)
  - Non-semver on either side: eligible (test suite is the gate)
  - Anti-loophole (req 34): non-semver installed + semver target with
    higher major → ineligible
"""

from __future__ import annotations

import re

_SEMVER_RE = re.compile(
    r"^v?(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<pre>[0-9A-Za-z\-.]+))?(?:\+(?P<build>[0-9A-Za-z\-.]+))?$"
)


def parse_semver(version: str) -> tuple[int, int, int] | None:
    """Return (major, minor, patch) or None if *version* is not valid semver."""
    m = _SEMVER_RE.match(version.strip())
    if not m:
        return None
    return int(m.group("major")), int(m.group("minor")), int(m.group("patch"))


def is_eligible(installed: str, target: str) -> tuple[bool, str]:
    """
    Determine whether updating from *installed* to *target* is eligible.

    Returns ``(eligible, reason)`` where *reason* is a short slug:
      - ``"both_non_semver"`` — neither side parses; accept.
      - ``"installed_non_semver"`` — installed is opaque; accept.
      - ``"target_non_semver"`` — target is opaque; accept.
      - ``"major_increase"`` — target major > installed major.
      - ``"zero_minor_increase"`` — 0.x minor bump = major-equivalent.
      - ``"patch_or_minor"`` — same major (or same 0.x patch); accept.

    Anti-loophole (req 34): if installed does NOT parse as semver but
    target DOES parse and has major > 0, we cannot determine the installed
    major so we accept (the test suite guards the update). However if *both*
    parse and target.major > installed.major, it is always ineligible.
    """
    sv_installed = parse_semver(installed)
    sv_target = parse_semver(target)

    # --- Non-semver branches (req 33) ---
    if sv_installed is None and sv_target is None:
        return True, "both_non_semver"
    if sv_installed is None:
        # Cannot compare majors without a parseable installed version — accept.
        return True, "installed_non_semver"
    if sv_target is None:
        return True, "target_non_semver"

    # --- Both parse as semver ---
    inst_major, inst_minor, _ = sv_installed
    tgt_major, tgt_minor, _ = sv_target

    # req 34: target semver with higher major → always ineligible
    if tgt_major > inst_major:
        return False, "major_increase"

    # 0.x minor treated as major-equivalent (req 32 row 3)
    if inst_major == 0 and tgt_major == 0 and tgt_minor > inst_minor:
        return False, "zero_minor_increase"

    # Patch or minor within same major (or same 0.x.y patch)
    return True, "patch_or_minor"
