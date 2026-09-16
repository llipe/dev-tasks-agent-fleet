"""
Finding classifier -- `mechanical` / `manual` / `unscannable` (spec §8.4,
PRD requirements 23-25/27, D22/D24, story S-134).

Per the story's own framing, this is "the single most product-defining
logic in the agent": it is where the D22 three-bucket model, the D24/
requirement 54 boundary with the sibling `dependency-update` agent, and
requirement 27's major-version guard all converge into one function.
`classify()` consumes `dedupe.py`'s (S-133) `MergedFinding` and
`trivy_runner.py`'s (S-130) `Remediation.lockfile_managed` field verbatim --
it does not redefine or recompute either.

`classify()` is a pure function: deterministic parsing of each tool's own
`Remediation` metadata only, no LLM call and no I/O (PRD requirement 25).

Branch order (spec §8.4's own pseudocode, reproduced exactly, precedence
top-to-bottom):

  1. `finding.remediation is None` -> `UNSCANNABLE` (checked first).
  2. `remediation.kind == "semgrep_autofix"` -> `MECHANICAL` (unconditional).
  3. `remediation.kind == "version_bump"`:
       a. `lockfile_managed` -> `MANUAL` (D24 -- dependency-update's lane).
       b. else, a confirmed major-version bump on a clean-semver
          `target_version` -> `MANUAL` (requirement 27's guard).
       c. else -> `MECHANICAL`.
  4. Everything else (`"structural"`, an unrecognized `kind`, or any shape
     this function cannot confidently parse) -> `MANUAL` -- the safe
     default; `classify()` never guesses a finding into `MECHANICAL`.

Two branch-order decisions are worth calling out explicitly, since they are
the two hardest cases this story's own task list flags:

  - **The `lockfile_managed=True` + major-bump-simultaneously case.** Both
    3a and 3b could independently justify `MANUAL` for the same finding.
    Spec §8.4's pseudocode checks 3a (`lockfile_managed`) strictly before
    3b (the major-bump guard) and returns immediately on a match -- so when
    both apply, the classification is still just `MANUAL` (never a third
    outcome), and the *reason* a downstream PR-body/audit-report renderer
    (S-135, out of this story's scope) would attribute is the lockfile
    boundary, not the major-bump guard, because that is the branch that
    actually fired. This is a deliberate, documented choice, not an
    accidental default: the lockfile boundary is the more specific,
    ownership-transferring reason ("this is dependency-update's job"),
    while the major-bump guard is this agent's own conservatism about a
    fix it *could* attempt but chooses not to -- when both are true, "it's
    not even our finding to own" is the more informative signal to a human
    reviewer than "and also it would have been a major bump."
  - **Unparseable-but-otherwise-eligible `target_version`/`current_version`
    strings.** `_is_major_bump()`/`_is_semver()` never raise -- an
    unparseable version (e.g. Trivy's own Debian-style
    `"2.36-9+deb12u4"`, or a missing `current_version`) makes
    `_is_major_bump()` return `False` (cannot positively confirm a major
    bump), so branch 3b's guard does not fire and the finding falls through
    to 3c (`MECHANICAL`) when otherwise eligible. This matches spec §8.4's
    literal `if _is_major_bump(f) and _is_semver(target_version)` guard
    (both conjuncts must hold for the guard to fire) and keeps AC10's "Trivy
    finding on a container base image ... clean version-bump -> mechanical"
    reachable for real-world OS-package version strings, which are rarely
    strict three-part semver. This is a "safe default" in the *permissive*
    direction for this one guard specifically -- distinct from branch 4's
    "safe default", which is deliberately conservative (`MANUAL`) for any
    `remediation.kind` this function does not recognize at all. The two
    are not in tension: 3b's guard only ever narrows an already-eligible
    `version_bump` finding, so failing open on that one guard cannot
    misclassify a `structural`/unrecognized-`kind` finding into
    `MECHANICAL` -- that guarantee is what branch 4 exists to enforce.
"""

from __future__ import annotations

import re
from enum import Enum

from dedupe import MergedFinding
from normalize import Finding


class Bucket(Enum):
    """The three classification outcomes (PRD requirement 23 / D22)."""

    MECHANICAL = "mechanical"
    MANUAL = "manual"
    UNSCANNABLE = "unscannable"


# Anchored, three-part semver: MAJOR.MINOR.PATCH with optional pre-release
# and/or build-metadata suffix (an optional leading "v" is tolerated, e.g.
# tags like "v2.0.0"). Deliberately stricter than Trivy's own real-world
# `FixedVersion`/`InstalledVersion` values (Debian/RPM package-version
# syntax, e.g. "2.36-9+deb12u4", does NOT match this pattern) -- see module
# docstring's second bulleted deviation for why that is the intended,
# permissive-by-design behavior for the major-bump guard specifically. No
# external semver library dependency: none is present in `pyproject.toml`,
# and this pattern is sufficient for the one property this module needs
# (comparing MAJOR components of two version strings).
_SEMVER_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:[-+][0-9A-Za-z.-]*)?$")


def _is_semver(version: str | None) -> bool:
    """Whether `version` is a clean, anchored three-part semver string.

    `None` and any non-matching shape (empty string, a bare "5.3", a
    Debian-style package version, "latest", etc.) are `False` -- never
    raises.
    """
    if version is None:
        return False
    return bool(_SEMVER_RE.match(version.strip()))


def _parse_semver_major(version: str | None) -> int | None:
    """The MAJOR component of a clean semver string, or `None` when
    `version` is not clean semver (see `_is_semver`). Never raises.
    """
    if version is None:
        return None
    match = _SEMVER_RE.match(version.strip())
    if not match:
        return None
    return int(match.group(1))


def _is_major_bump(finding: Finding) -> bool:
    """Whether `finding`'s remediation is a confirmed major-version bump.

    Requires both `remediation.current_version` and
    `remediation.target_version` to parse as clean semver (`_is_semver`);
    when either is missing, malformed, or not semver-shaped, this returns
    `False` -- "cannot positively confirm a major bump" is the safe,
    non-crashing default (module docstring's second bulleted deviation),
    never a raised exception.
    """
    remediation = finding.remediation
    if remediation is None:
        return False
    current_major = _parse_semver_major(remediation.current_version)
    target_major = _parse_semver_major(remediation.target_version)
    if current_major is None or target_major is None:
        return False
    return target_major > current_major


def classify(merged: MergedFinding) -> Bucket:
    """Classify one `MergedFinding` into exactly one `Bucket` (spec §8.4,
    PRD requirement 23 / D22). Pure, deterministic, total over the
    documented `Remediation` field domain -- see module docstring for the
    full branch-order rationale.
    """
    finding = merged.finding
    remediation = finding.remediation

    if remediation is None:
        return Bucket.UNSCANNABLE

    if remediation.kind == "semgrep_autofix":
        return Bucket.MECHANICAL

    if remediation.kind == "version_bump":
        if remediation.lockfile_managed:
            # D24 / req 54 -- dependency-update's lane, not ours. Checked
            # before the major-bump guard; see module docstring's first
            # bulleted deviation for the simultaneous-guard precedence.
            return Bucket.MANUAL
        if _is_major_bump(finding) and _is_semver(remediation.target_version):
            # req 27 -- major bump on a non-lockfile semver artifact (e.g.
            # a container base image tag) stays manual, reason recorded
            # for the PR body by a downstream renderer (S-135).
            return Bucket.MANUAL
        return Bucket.MECHANICAL

    # Everything else -- "structural" (Checkov/CodeQL/Gitleaks default) and
    # any unrecognized `kind` this function cannot confidently parse -- is
    # the safe default: `MANUAL`, never guessed into `MECHANICAL`.
    return Bucket.MANUAL
