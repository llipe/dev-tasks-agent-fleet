"""
Semgrep autofix application (spec S8.6, PRD requirement 27's first bullet /
D23, story S-136).

``apply_semgrep_autofix()`` is one blanket ``semgrep --autofix --config
<RULESET> <workspace>`` invocation -- per spec S8.6's own design, "the
agent does not hand-apply individual patches." `RULESET` is imported
verbatim from `scanners.semgrep_runner` (S-128, already merged) rather than
redefined here, per this story's own instruction and that module's own
docstring note anticipating this reuse.

**Why a blanket, workspace-wide invocation cannot violate PRD requirement 28
(manual/unscannable findings must never be touched by any code path).**
`classify()` (`classifier.py`, S-134) maps *every* Semgrep finding whose
`remediation.kind == "semgrep_autofix"` unconditionally to `Bucket.MECHANICAL`
-- there is no branch under which a Semgrep autofix-kind finding is
`manual`. Conversely, a Semgrep finding classified `unscannable` has
`remediation is None`, which `normalize_semgrep()` (`scanners/semgrep_runner.py`)
only produces when the rule carries no native `extra.fix` patch at scan
time -- i.e. there is nothing for `semgrep --autofix` to apply there in the
first place. And every `manual`/`unscannable` finding from the other four
tools (Gitleaks, Trivy, Checkov, CodeQL) is invisible to the `semgrep`
binary entirely -- it only ever rewrites source it itself matched against
its own pinned `RULESET`. So the set of files `semgrep --autofix` can
possibly rewrite is, by construction, a subset of files containing a
`mechanical`-bucket Semgrep finding. `_mechanical_semgrep_findings()` below
adds a second, defensive layer on top of that structural guarantee: even if
a caller passes a `mechanical_findings` list containing non-Semgrep-autofix
entries (a caller bug, not a designed path), this module's own bookkeeping
(`applied_fingerprints`/`unresolved`) never attributes anything to them --
it structurally cannot decide a manual/unscannable finding was "applied."
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from config import SCANNER_TIMEOUT
from dedupe import MergedFinding
from fingerprint import fingerprint
from fixers.types import FixOutcome
from scanners.semgrep_runner import RULESET

# Local git operation (reading the working tree's own diff), not an
# external-tool call -- bounded independently of SCANNER_TIMEOUT, which is
# reserved for the actual `semgrep --autofix` subprocess call below.
_GIT_DIFF_TIMEOUT = 30


def _mechanical_semgrep_findings(
    mechanical_findings: list[MergedFinding],
) -> list[MergedFinding]:
    """Defensive re-filter (PRD requirement 28) -- module docstring.

    Keeps only findings this fixer can structurally own: Semgrep-sourced,
    with a `semgrep_autofix`-kind remediation. Never raises on a
    differently-shaped `MergedFinding` (e.g. `remediation is None`) --
    such entries are simply excluded, not treated as an error.
    """
    return [
        mf
        for mf in mechanical_findings
        if mf.finding.tool == "semgrep"
        and mf.finding.remediation is not None
        and mf.finding.remediation.kind == "semgrep_autofix"
    ]


def _build_autofix_command(workspace: Path) -> list[str]:
    """`semgrep --autofix --json --config <id> [--config <id> ...] <workspace>`
    -- one `--config` flag per `RULESET` entry, mirroring
    `semgrep_runner._build_command()`'s already-fixed argv shape (a single
    space-joined `--config` value, as spec S8.6's literal pseudocode shows,
    is not valid Semgrep CLI syntax -- see that module's docstring for the
    full rationale, reused verbatim here rather than re-introducing the
    same defect in the fixer).
    """
    cmd = ["semgrep", "--autofix"]
    for ruleset_id in RULESET:
        cmd.extend(["--config", ruleset_id])
    cmd.append(str(workspace))
    return cmd


def _changed_files(workspace: Path) -> set[str]:
    """Repo-relative paths with an uncommitted diff after the autofix call,
    via `git diff --name-only` (unstaged changes only -- semgrep never
    stages what it rewrites). Autofix only ever edits lines inside an
    *existing* matched file, never creates a new one, so untracked-file
    discovery (`git ls-files --others`) is deliberately out of scope here.

    Never raises: a non-git workspace or a `git` binary crash both degrade
    to "no changed files" (empty set) rather than propagating an exception
    out of the fixer -- the whole point of this helper is a best-effort
    signal, not a hard dependency on git being present.
    """
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only"],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=_GIT_DIFF_TIMEOUT,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return set()
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def _diff_applied(workspace: Path, targeted: list[MergedFinding]) -> frozenset[str]:
    """Which of `targeted`'s fingerprints show a file-level diff after the
    autofix subprocess ran (spec S8.6's `_diff_applied` reference).

    File-level, not line-level: a best-effort "something changed in this
    finding's file" signal, not a resolution proof -- the re-scan gate
    (`rescan.py`, S-137) is the actual authority, since it re-runs the
    scanner and checks fingerprint *absence*, which is the only way to
    confirm the underlying issue is gone rather than merely that the file
    changed.
    """
    changed = _changed_files(workspace)
    return frozenset(fingerprint(mf.finding) for mf in targeted if mf.finding.file_path in changed)


def apply_semgrep_autofix(workspace: Path, mechanical_findings: list[MergedFinding]) -> FixOutcome:
    """Apply Semgrep's native autofix patches for every `mechanical`
    Semgrep finding in `mechanical_findings` (PRD requirement 27, first
    bullet).

    A zero-mechanical-Semgrep-findings input (including an empty list, or a
    list containing only non-Semgrep/non-`mechanical` entries after the
    defensive re-filter) is a no-op: no subprocess call is made at all,
    and an empty `FixOutcome` is returned immediately.

    **Timeout/crash handling (pre-authorized "apply proactively"
    correctness fix, same class as `semgrep_runner.py`'s/`trivy_runner.py`'s
    own deviations).** Spec S8.6's literal pseudocode wraps the autofix
    `subprocess.run()` call in no `try`/`except` at all -- a timed-out or
    failed-to-start autofix invocation would propagate an unhandled
    exception and crash the whole `fix` step for the entire run, not just
    this one fixer's contribution. That is inconsistent with every other
    subprocess boundary in this codebase (`run_semgrep()`/`run_trivy()`/etc.,
    all of which convert `subprocess.TimeoutExpired`/`OSError` into a
    non-fatal outcome). Mirrored here: both exceptions are caught and
    converted into a `FixOutcome` reporting every targeted finding as
    `unresolved` (so a later story's orchestrator can still hand them to
    the LLM escape hatch, PRD requirement 29) with a descriptive `output`
    string, never a propagated exception.
    """
    targeted = _mechanical_semgrep_findings(mechanical_findings)
    if not targeted:
        return FixOutcome(applied_fingerprints=frozenset(), unresolved=(), output="")

    cmd = _build_autofix_command(workspace)
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=SCANNER_TIMEOUT,
            check=False,
        )
        output = (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired as exc:
        return FixOutcome(
            applied_fingerprints=frozenset(),
            unresolved=tuple(targeted),
            output=f"semgrep --autofix timed out after {SCANNER_TIMEOUT}s: {exc}",
        )
    except OSError as exc:
        return FixOutcome(
            applied_fingerprints=frozenset(),
            unresolved=tuple(targeted),
            output=f"semgrep --autofix failed to start: {exc}",
        )

    applied = _diff_applied(workspace, targeted)
    unresolved = tuple(mf for mf in targeted if fingerprint(mf.finding) not in applied)
    return FixOutcome(applied_fingerprints=applied, unresolved=unresolved, output=output)
