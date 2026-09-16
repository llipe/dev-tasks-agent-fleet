"""
Trivy version-bump application (spec S8.6, PRD requirement 27's second
bullet / D23, story S-136).

``apply_trivy_bump()`` applies the already-decided `Remediation.target_version`
(computed by `trivy_runner.py`'s `_lowest_fixed_version()`, S-130 -- "the
lowest of comma-separated `FixedVersion` candidates") to the manifest file
that carries the pinned version, for every `mechanical` Trivy finding. This
module's job is to APPLY that decision, never to re-derive or re-rank
version candidates itself.

**Lockfile reconciliation (task 12.2/12.6) -- the mechanism chosen and why.**
Per S-134's boundary (`classifier.py`'s `_JS_LOCKFILES`), only Python
manifests (`requirements.txt`, `poetry.lock`, `Pipfile.lock`) ever reach
this fixer as `mechanical` -- JS/TS lockfile findings are always `manual`
(`dependency-update`'s lane, D24), so this module never needs npm/pnpm
lockfile-specific reconciliation logic at all.

Among the three Python target-file basenames, two (`poetry.lock`,
`Pipfile.lock`) are *generated* lock artifacts, not hand-editable manifests
-- they embed dependency-resolution graphs and content hashes a naive
string substitution would silently corrupt. The PRD's own requirement 30
(sibling agent's `reconcile_lockfile()`, `agents/dependency-update/app/
dependencyUpdate/updater.py`) establishes the precedent this story is asked
to mirror: bump the *source* manifest (`pyproject.toml` for Poetry,
`Pipfile` for Pipenv), then run that ecosystem's own lock command (``poetry
lock``, ``pipenv lock``) to regenerate the lockfile from the bumped
constraint -- never hand-edit the lockfile's own bytes. `requirements.txt`,
by contrast, is not a generated lock artifact in the same sense (no
companion "source manifest" it is compiled from, in the common case this
story scopes to) -- it is edited in place directly, with no reconciliation
step, mirroring how the sibling agent's `install_deps(frozen=False)` step
only exists to reconcile a *derived* file against a constraint change, and
there is no derived file here.

This is a **deliberate, documented interpretation**, flagged per this
story's "if the spec is ambiguous, implement the most defensible
interpretation" instruction: the spec text itself only says "lockfile
reconciliation runs after a Python manifest bump," without naming
`poetry`/`pipenv` as the concrete mechanism. `poetry lock` / `pipenv lock`
are those two ecosystems' own standard, first-party commands for exactly
this operation (analogous to the sibling agent's `pnpm install`/`npm
install` reconciliation step for npm/pnpm), so this is the natural,
minimal-surprise choice rather than inventing a custom mechanism (e.g.
`pip-compile`, which assumes a `requirements.in`/`pip-tools` workflow this
codebase has no signal the target repository uses).

**Dockerfile / container base-image findings.** PRD requirement 27 also
describes "updating the resolved package/base-image reference" for a
base-image finding (AC10's `mechanical` base-image case, S-134). This
module does not special-case `Dockerfile`/base-image targets: `_bump_manifest_text()`
below is purely name/version-pattern-driven, so a base-image finding whose
`file_path` does not contain a `<package_name> = <version>`-shaped line
(the common case -- a `FROM <image>:<tag>` line names an image reference,
not `remediation.package_name`) simply finds no match and falls through to
`unresolved`, the same path PRD requirement 29 already describes for "a
Trivy version bump requires a source edit beyond the version string
itself." No separate Dockerfile-editing mechanism is invented here since
neither the spec nor this story's own task list describes one concretely --
the LLM escape hatch (`fix_agent.py`, S-138, out of this story's scope) is
the documented next step for exactly this shape of unresolved finding.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from config import SCANNER_TIMEOUT
from dedupe import MergedFinding
from fingerprint import fingerprint
from fixers.types import FixOutcome
from normalize import Finding

# basename -> (companion source-manifest basename, lock-regeneration command)
# Only Python lockfile-backed ecosystems ever reach this fixer as
# `mechanical` (module docstring) -- npm/pnpm are excluded by construction
# via `classifier.py`'s D24 boundary, not re-checked here.
_PYTHON_LOCKFILES: dict[str, tuple[str, tuple[str, ...]]] = {
    "poetry.lock": ("pyproject.toml", ("poetry", "lock")),
    "Pipfile.lock": ("Pipfile", ("pipenv", "lock")),
}

# First version-shaped substring on a line -- deliberately permissive (not
# `classifier.py`'s stricter three-part `_SEMVER_RE`): manifest version
# pins span many shapes (`==2.31.0`, `^2.11.2`, `>=1.2,<2.0`, Debian-style
# `2.36-9+deb12u4`), and this only needs to find *a* version-like token to
# replace on an already name-matched line, not validate semver-ness (that
# judgment already happened at classification time, S-134).
_VERSION_RE = re.compile(r"\d+(?:\.\d+){1,2}(?:[-.][0-9A-Za-z]+)*")


def _mechanical_trivy_findings(mechanical_findings: list[MergedFinding]) -> list[MergedFinding]:
    """Defensive re-filter (PRD requirement 28) -- mirrors
    `semgrep_autofix._mechanical_semgrep_findings()`'s same-purpose filter.

    Keeps only Trivy findings with a non-lockfile-managed `version_bump`
    remediation -- excludes `lockfile_managed=True` (D24, `dependency-update`'s
    lane) even if a caller mistakenly includes one, so this fixer
    structurally cannot touch a JS/TS lockfile finding regardless of what
    it is handed.
    """
    return [
        mf
        for mf in mechanical_findings
        if mf.finding.tool == "trivy"
        and mf.finding.remediation is not None
        and mf.finding.remediation.kind == "version_bump"
        and not mf.finding.remediation.lockfile_managed
    ]


def _name_pattern(package_name: str) -> re.Pattern[str]:
    """Compile a case-insensitive, start-of-line pattern matching a manifest
    line that declares `package_name` (PEP 503-style normalization: `-`/`_`
    are treated as interchangeable, e.g. so `remediation.package_name ==
    "some-package"` still matches a `some_package = "..."` TOML line).

    Matches the common manifest shapes this story targets:
      - ``requests==2.25.0`` (requirements.txt)
      - ``requests>=2.25.0,<3`` (requirements.txt, range pin)
      - ``jinja2 = "^2.11.2"`` (pyproject.toml, Poetry table)
      - ``pyyaml = "==5.3"`` (Pipfile)
    """
    escaped = re.escape(package_name).replace(r"\-", "[-_]").replace(r"\_", "[-_]")
    return re.compile(rf"^\s*[\"\']?{escaped}[\"\']?\s*[=:]", re.IGNORECASE)


def _bump_line(line: str, current_version: str | None, target_version: str) -> str | None:
    """Substitute the version substring on an already name-matched `line`.

    Prefers an exact `current_version` occurrence (precise, avoids
    accidentally rewriting an unrelated numeric token on the same line)
    when `current_version` is known and present; falls back to the first
    generic version-shaped substring (`_VERSION_RE`) otherwise. Returns
    `None` when neither strategy finds anything to replace (e.g. a
    `package = "*"` unpinned Pipfile entry) -- the caller treats this as
    "requires an edit beyond the version string" (PRD requirement 29's
    unresolved-handoff case), never a silent no-op mistaken for success.
    """
    if current_version and current_version in line:
        return line.replace(current_version, target_version, 1)
    match = _VERSION_RE.search(line)
    if match is None:
        return None
    return line[: match.start()] + target_version + line[match.end() :]


def _bump_manifest_text(
    text: str, package_name: str, current_version: str | None, target_version: str
) -> str | None:
    """Pure function: substitute `package_name`'s pinned version with
    `target_version` in manifest file `text` (task 12.7's "Trivy bump
    target-version selection as a pure function" -- no I/O, unit-testable
    directly against fixture strings).

    Only the *first* line matching `package_name` is edited (manifests do
    not legitimately declare the same package twice). Returns `None`,
    changing nothing, when no matching line is found at all, or a matching
    line is found but `_bump_line()` cannot locate a version substring to
    replace on it.
    """
    pattern = _name_pattern(package_name)
    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if pattern.match(line):
            bumped = _bump_line(line, current_version, target_version)
            if bumped is None:
                return None
            lines[index] = bumped
            return "".join(lines)
    return None


def _apply_bump_to_file(
    path: Path, package_name: str, current_version: str | None, target_version: str
) -> bool:
    """Read `path`, bump `package_name`'s pin via `_bump_manifest_text()`,
    and write the result back if a substitution was made. Returns whether
    the file was changed. `path` not existing is treated as "nothing to
    bump" (`False`), never a raised exception -- a Trivy finding naming a
    file that no longer exists in the current checkout state is an
    unresolved-handoff case, not a fixer crash.
    """
    if not path.is_file():
        return False
    bumped = _bump_manifest_text(path.read_text(), package_name, current_version, target_version)
    if bumped is None:
        return False
    path.write_text(bumped)
    return True


def _reconcile_lockfile(directory: Path, cmd: tuple[str, ...]) -> str:
    """Run the ecosystem's own lock-regeneration command (module docstring)
    in `directory` after its companion manifest was bumped.

    **Timeout/crash handling (pre-authorized "apply proactively" correctness
    fix, same class as `semgrep_autofix.py`'s deviation).** Neither this
    story's task list nor spec S8.6 describes what happens if the
    reconciliation command itself hangs or the `poetry`/`pipenv` binary is
    missing from the image -- both are caught here and folded into the
    returned audit-trail string rather than propagating an exception that
    would crash the whole `fix` step over one lockfile's reconciliation
    failure. A reconciliation failure does NOT unwind the manifest bump
    that already succeeded, nor does it retroactively mark that finding's
    fingerprint as unapplied -- the re-scan gate (S-137) is the actual
    authority on whether the end state is clean; this function's only job
    is to attempt the reconciliation and report what happened.
    """
    try:
        result = subprocess.run(
            list(cmd),
            cwd=directory,
            capture_output=True,
            text=True,
            timeout=SCANNER_TIMEOUT,
            check=False,
        )
        return (result.stdout or "") + (result.stderr or "")
    except subprocess.TimeoutExpired as exc:
        return f"{' '.join(cmd)} timed out after {SCANNER_TIMEOUT}s in {directory}: {exc}"
    except OSError as exc:
        return f"{' '.join(cmd)} failed to start in {directory}: {exc}"


def _apply_one(
    workspace: Path, finding: Finding
) -> tuple[bool, Path | None, tuple[str, ...] | None]:
    """Apply one finding's version bump. Returns
    `(applied, lockfile_dir_to_reconcile, lock_cmd)`.

    Dispatches on `Path(finding.file_path).name`: a `poetry.lock`/`Pipfile.lock`
    target bumps the companion source manifest (sibling directory) and
    reports that directory + lock command back to the caller for a single,
    deduplicated reconciliation pass (see `apply_trivy_bump()`'s docstring
    for why reconciliation is batched rather than run per-finding); every
    other target (`requirements.txt`, or any other basename -- including a
    `Dockerfile`, module docstring's last section) is bumped in place
    directly, with no reconciliation.
    """
    remediation = finding.remediation
    assert remediation is not None  # narrowed by _mechanical_trivy_findings
    target_version = remediation.target_version
    package_name = remediation.package_name

    if target_version is None or package_name is None:
        # No package identifier or no decided target -- cannot safely locate
        # what to bump (module docstring's Dockerfile/base-image note).
        return False, None, None

    basename = Path(finding.file_path).name
    lockfile_entry = _PYTHON_LOCKFILES.get(basename)

    if lockfile_entry is not None:
        manifest_basename, lock_cmd = lockfile_entry
        lockfile_dir = (workspace / finding.file_path).parent
        manifest_path = lockfile_dir / manifest_basename
        applied = _apply_bump_to_file(
            manifest_path, package_name, remediation.current_version, target_version
        )
        return (applied, lockfile_dir, lock_cmd) if applied else (False, None, None)

    manifest_path = workspace / finding.file_path
    applied = _apply_bump_to_file(
        manifest_path, package_name, remediation.current_version, target_version
    )
    return applied, None, None


def apply_trivy_bump(workspace: Path, mechanical_findings: list[MergedFinding]) -> FixOutcome:
    """Apply Trivy version bumps for every `mechanical` Trivy finding in
    `mechanical_findings` (PRD requirement 27, second bullet).

    A zero-mechanical-Trivy-findings input is a no-op: no file I/O and no
    subprocess call is made, and an empty `FixOutcome` is returned
    immediately -- mirrors `apply_semgrep_autofix()`'s same no-op contract.

    Lockfile reconciliation (module docstring) is batched: every targeted
    finding's manifest bump is applied first (a companion `poetry.lock`/
    `Pipfile.lock` directory may receive several package bumps into the
    same `pyproject.toml`/`Pipfile`), and each distinct lockfile directory
    is reconciled exactly once afterward -- running the ecosystem's lock
    command once per bumped package would be both wasteful and, for some
    lock tools, not safe to run repeatedly against the same lockfile within
    one invocation.
    """
    targeted = _mechanical_trivy_findings(mechanical_findings)
    if not targeted:
        return FixOutcome(applied_fingerprints=frozenset(), unresolved=(), output="")

    applied_fingerprints: set[str] = set()
    unresolved: list[MergedFinding] = []
    pending_reconciliation: dict[Path, tuple[str, ...]] = {}

    for mf in targeted:
        finding = mf.finding
        applied, lockfile_dir, lock_cmd = _apply_one(workspace, finding)
        if not applied:
            unresolved.append(mf)
            continue
        applied_fingerprints.add(fingerprint(finding))
        if lockfile_dir is not None and lock_cmd is not None:
            pending_reconciliation[lockfile_dir] = lock_cmd

    output_parts = [
        _reconcile_lockfile(directory, cmd) for directory, cmd in pending_reconciliation.items()
    ]

    return FixOutcome(
        applied_fingerprints=frozenset(applied_fingerprints),
        unresolved=tuple(unresolved),
        output="\n".join(part for part in output_parts if part),
    )
