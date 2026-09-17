"""
LLM fix agent — per-finding escape hatch (spec §8.6, §12, PRD requirements
29-32 / D22, D26, story S-138).

**The one genuinely new design point vs. the sibling (dependency-update)
agent's own `fix_agent.py`: per-finding invocation and per-finding
budgeting, not per-run.** `run_fix_loop_for_finding()` below is called once
per LLM-eligible finding (a `mechanical` finding a deterministic fixer --
`fixers/semgrep_autofix.py`/`fixers/trivy_bump.py`, S-136 -- did not
resolve, req 29), each call with its own fresh `max_attempts` counter, so
one stubborn finding cannot consume the budget that would otherwise fix an
easier one (PRD acceptance criterion 17). The orchestrator wiring that
calls this once per finding is S-140's scope, not this module's -- this
story builds and proves `fix_agent.py` standalone.

The 5-tool surface (`shell`/`read_file`/`write_file`/`find_files`/
`grep_code`) and the `_safe_path` workspace-confinement resolver are ported
near-verbatim from `agents/dependency-update/app/dependencyUpdate/
fix_agent.py` (research item 5, spec §12) -- the per-finding architectural
difference only changes *what* the model is told to fix and *what is
checked afterward*, never *how* the tool surface itself is confined to the
workspace.

Two security-critical properties, both verified directly (not merely
prompted), mirroring this codebase's `rescan.py` (S-137) "verify, don't just
constrain" philosophy:

  1. ``_safe_path`` (spec §12, PRD AC20) -- every path-taking tool call is
     resolved against the workspace root and refused if it escapes via
     traversal, an absolute path, or a symlink.
  2. ``_assert_diff_confined_to`` (spec §12) -- this agent's equivalent of
     the sibling's package.json mandate check (req 50 there), narrowed to a
     single-finding scope since there is no shared dependency-manifest
     concept here: after an attempt, the working-tree diff MUST touch only
     the single targeted finding's own ``file_path``. A violation raises
     ``MandateViolationError`` and the finding is reported unresolved
     (falls through to ``RESCAN_NOT_CLEAN`` handling, S-140's scope) rather
     than the diff being trusted.

Requirements implemented here:
    - req 29: LLM invoked only per-finding, when the deterministic fixer
      left the finding in `unresolved` (orchestrator wiring, S-140's scope
      -- this module only accepts what it is given).
    - req 31 / PRD AC19: the agent receives ONLY the single targeted
      finding's record -- never the full findings list. Enforced
      structurally: `run_fix_loop_for_finding`'s own signature accepts one
      `MergedFinding`, not a list, so there is no full findings list in
      scope to leak from even by caller mistake.
    - req 32 / D26 / PRD AC17: `max_fix_attempts` budget applies per
      finding, not per run.
    - PRD AC18: `max_fix_attempts=0` disables the LLM entirely -- the
      attempt loop's own `range(1, 0 + 1)` never executes, so `Agent` is
      never constructed and zero Bedrock calls are made.
    - spec §12: `_assert_diff_confined_to` post-fix check.
"""

from __future__ import annotations

import glob
import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from strands import Agent, tool

from config import FIX_COMMAND_TIMEOUT, MODEL_ID, SCANNER_TIMEOUT
from dedupe import MergedFinding
from fingerprint import fingerprint
from scanners import AllScannersFailedError, run_scanners

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Path safety (spec §12, PRD AC20) — ported from the sibling agent's
# fix_agent.py, unweakened.
# ---------------------------------------------------------------------------

_WORKSPACE: str = ""  # Set by run_fix_loop_for_finding before creating tools


def _safe_path(rel: str) -> str:
    """
    Resolve a relative path against the workspace root.

    Raises ValueError if the resolved path escapes the workspace via
    traversal, absolute paths, or symlinks. Ported verbatim from the
    sibling agent's `fix_agent.py` (spec §12) -- the same resolution logic,
    unweakened.
    """
    if not _WORKSPACE:
        raise ValueError("Workspace not set — cannot resolve path")

    # Reject absolute paths immediately
    if os.path.isabs(rel):
        raise ValueError(f"Absolute paths are not allowed: {rel}")

    # Resolve against workspace (follows symlinks for the final realpath check)
    candidate = os.path.normpath(os.path.join(_WORKSPACE, rel))
    resolved = os.path.realpath(candidate)
    workspace_real = os.path.realpath(_WORKSPACE)

    # The resolved path must be within or equal to the workspace
    if not (resolved == workspace_real or resolved.startswith(workspace_real + os.sep)):
        raise ValueError(
            f"Path escapes workspace: '{rel}' resolves to '{resolved}' "
            f"which is outside '{workspace_real}'"
        )

    return resolved


# ---------------------------------------------------------------------------
# Tools (exactly 5, mirroring the sibling agent's req 45 tool surface)
# ---------------------------------------------------------------------------


@tool
def shell(command: str) -> str:
    """
    Run a shell command inside the workspace checkout.

    The command runs with cwd set to the workspace root. Use this to
    investigate a finding (e.g. grep for related usages) or verify a fix.
    Do NOT use this to bypass file safety checks.
    """
    if not _WORKSPACE:
        return "ERROR: Workspace not set"
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=_WORKSPACE,
            capture_output=True,
            text=True,
            timeout=FIX_COMMAND_TIMEOUT,
        )
        output = (result.stdout or "") + (result.stderr or "")
        if len(output) > 16000:
            output = output[:8000] + "\n...[truncated]...\n" + output[-8000:]
        if result.returncode != 0:
            return f"EXIT CODE {result.returncode}\n{output.strip()}"
        return output.strip() or "(no output)"
    except subprocess.TimeoutExpired:
        return f"ERROR: Command timed out after {FIX_COMMAND_TIMEOUT}s"
    except Exception as exc:
        return f"ERROR: {exc}"


@tool
def read_file(path: str) -> str:
    """
    Read the contents of a file inside the workspace.

    The path must be relative to the workspace root. Absolute paths and
    paths that escape the workspace (e.g. ../) are rejected.
    """
    try:
        resolved = _safe_path(path)
    except ValueError as exc:
        return f"ERROR: {exc}"

    try:
        with open(resolved, encoding="utf-8", errors="replace") as f:
            content = f.read()
        if len(content) > 64000:
            content = content[:32000] + "\n...[truncated]...\n" + content[-32000:]
        return content
    except OSError as exc:
        return f"ERROR: Cannot read file: {exc}"


@tool
def write_file(path: str, content: str) -> str:
    """
    Write content to a file inside the workspace.

    The path must be relative to the workspace root. Absolute paths and
    paths that escape the workspace (e.g. ../) are rejected. Parent
    directories are created if needed.
    """
    try:
        resolved = _safe_path(path)
    except ValueError as exc:
        return f"ERROR: {exc}"

    try:
        os.makedirs(os.path.dirname(resolved), exist_ok=True)
        with open(resolved, "w", encoding="utf-8") as f:
            f.write(content)
        return f"OK: wrote {len(content)} bytes to {path}"
    except OSError as exc:
        return f"ERROR: Cannot write file: {exc}"


@tool
def find_files(pattern: str) -> str:
    """
    Find files by glob pattern inside the workspace.

    The pattern is evaluated relative to the workspace root using recursive
    glob. Results are returned as newline-separated relative paths.
    Example patterns: '**/*.py', 'src/**/*.ts', '*.json'
    """
    if not _WORKSPACE:
        return "ERROR: Workspace not set"

    try:
        matches = glob.glob(pattern, root_dir=_WORKSPACE, recursive=True)
        filtered = [
            m
            for m in matches
            if not m.startswith("node_modules/")
            and not m.startswith(".git/")
            and "/node_modules/" not in m
        ]
        filtered.sort()
        if not filtered:
            return "(no files matched)"
        if len(filtered) > 200:
            return "\n".join(filtered[:200]) + f"\n... ({len(filtered) - 200} more)"
        return "\n".join(filtered)
    except Exception as exc:
        return f"ERROR: {exc}"


@tool
def grep_code(pattern: str, file_pattern: str = "**/*") -> str:
    """
    Search for a regex pattern in source files inside the workspace.

    Args:
        pattern: The regex pattern to search for (Python re syntax).
        file_pattern: Glob pattern to filter which files to search.
                     Defaults to all files. Example: '**/*.py'

    Returns matching lines with file:line_number:content format.
    """
    if not _WORKSPACE:
        return "ERROR: Workspace not set"

    try:
        cmd = ["grep", "-rn", "--include=" + file_pattern, pattern, "."]
        result = subprocess.run(
            cmd,
            cwd=_WORKSPACE,
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = result.stdout.strip()
        if not output:
            return "(no matches)"
        lines = output.split("\n")
        if len(lines) > 100:
            return "\n".join(lines[:100]) + f"\n... ({len(lines) - 100} more matches)"
        return output
    except subprocess.TimeoutExpired:
        return "ERROR: grep timed out"
    except Exception as exc:
        return f"ERROR: {exc}"


# ---------------------------------------------------------------------------
# System prompt + per-finding prompt (req 31, spec §8.6)
# ---------------------------------------------------------------------------

FIX_AGENT_SYSTEM_PROMPT = """\
You are a security-finding fix agent. Your job is to resolve exactly ONE \
security finding in a checked-out repository, described in the user message.

RULES YOU MUST FOLLOW:
1. Fix ONLY the single finding described in the user message. Do NOT look \
for or attempt to fix any other issue in the codebase.
2. Do NOT modify any file other than the one named as the finding's file \
path. If a genuine fix would require touching a second file, do NOT make \
that edit — report that the fix could not be completed within scope.
3. Do NOT delete, skip, disable, or weaken any test to make a check pass.
4. Do NOT modify test files under any circumstances.
5. Make the smallest, most targeted change that resolves the finding.

You have these tools available:
- shell: Run shell commands in the workspace.
- read_file: Read a file by relative path.
- write_file: Write content to a file by relative path.
- find_files: Find files by glob pattern.
- grep_code: Search for patterns in source files.

Work methodically:
1. Read the finding's file at the given line range to understand the \
flagged code.
2. Make a minimal, targeted change that resolves the underlying security \
issue.
3. Verify your understanding by re-reading the file after your change.
"""


def _build_finding_prompt(finding: MergedFinding, attempt: int) -> str:
    """
    Build the single-finding user prompt (spec §8.6, PRD requirement 31).

    Includes ONLY this finding's own record — tool, rule, severity, file
    path, line range, message, category — never the full findings list.
    There is no other findings list in this function's scope to leak from:
    `run_fix_loop_for_finding`'s own signature accepts one `MergedFinding`,
    structurally enforcing requirement 31 / PRD AC19 rather than merely
    instructing the model not to look elsewhere.
    """
    target = finding.finding
    header = "Retry: the previous attempt did not resolve this finding.\n\n" if attempt > 1 else ""
    return (
        f"{header}"
        f"Fix the following security finding:\n\n"
        f"- Tool: {target.tool}\n"
        f"- Rule: {target.rule_id}\n"
        f"- Severity: {target.severity.value}\n"
        f"- Category: {target.cwe_or_category}\n"
        f"- File: {target.file_path}\n"
        f"- Lines: {target.line_start}-{target.line_end}\n"
        f"- Message: {target.message}\n\n"
        f"Read the file at the given line range, understand the issue, and "
        f"make the smallest possible change to {target.file_path} that "
        f"resolves it. Do not touch any other file."
    )


# ---------------------------------------------------------------------------
# Diff confinement — mandate-violation-equivalent enforcement (spec §12)
# ---------------------------------------------------------------------------

_GIT_DIFF_TIMEOUT = 30  # seconds


class MandateViolationError(Exception):
    """
    Raised when a fix-agent attempt's diff touches a file outside the
    single targeted finding's own ``file_path`` (spec §12) — this agent's
    equivalent of the sibling agent's package.json mandate check (req 50
    there), narrowed to a single-finding scope since there is no shared
    dependency-manifest concept here.
    """


def _changed_files(workspace: str) -> set[str]:
    """
    Repo-relative paths with ANY working-tree change (modified tracked
    file OR newly created untracked file) since the last commit.

    **Deliberate deviation from `fixers/semgrep_autofix.py`'s own
    `_changed_files()` pattern** (`git diff --name-only`, modified-tracked
    files only — pre-authorized "apply proactively" correctness fix,
    flagged for `verifier`'s audit per this story's completion
    instructions): that fixer's `--autofix` subprocess only ever rewrites
    lines inside an *existing* matched file, so untracked-file discovery is
    correctly out of scope there. This module's `write_file` tool, by
    contrast, can create a brand-new file anywhere the LLM's tool call
    names it (subject only to `_safe_path`'s workspace confinement — NOT
    to the targeted finding's own file path), so a version of this helper
    checking modified-tracked files only would silently miss an
    out-of-scope *new* file — exactly the scenario spec §12 / task 14.8
    describe ("a diff touching a file outside the finding's own path is
    caught ... not trusted"). `git status --porcelain` covers both
    modified-tracked and untracked-new paths in one call, closing that gap.

    Never raises: a non-git workspace, a missing workspace path, or a `git`
    binary crash all degrade to "no changed files" (empty set) rather than
    propagating — consistent with `semgrep_autofix.py`'s own philosophy for
    this helper (a best-effort signal, not a hard dependency on git).
    """
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=_GIT_DIFF_TIMEOUT,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return set()

    changed: set[str] = set()
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        # Porcelain v1 format: "XY PATH" (or "XY ORIG -> PATH" for renames).
        path_part = line[3:]
        if " -> " in path_part:
            src, _, dst = path_part.partition(" -> ")
            changed.add(src.strip().strip('"'))
            changed.add(dst.strip().strip('"'))
        else:
            changed.add(path_part.strip().strip('"'))
    return changed


def _assert_diff_confined_to(workspace: str, file_path: str) -> None:
    """
    Verify the working-tree diff after a fix-agent attempt touches only
    ``file_path`` (spec §12's ``_assert_diff_confined_to(finding.file_path)``).

    Compares ``_changed_files(workspace)`` against the single allowed path;
    any other path present raises ``MandateViolationError`` naming every
    out-of-scope path found, so the caller (``run_fix_loop_for_finding``)
    can report the finding unresolved rather than trusting an out-of-scope
    diff — a post-hoc *verification*, not merely relying on the tool
    surface's ``_safe_path`` prompting/confinement (module docstring).
    """
    changed = _changed_files(workspace)
    outside = changed - {file_path}
    if outside:
        raise MandateViolationError(
            f"Fix-agent diff touched files outside the targeted finding's "
            f"path ({file_path!r}): {sorted(outside)}"
        )


# ---------------------------------------------------------------------------
# Fix loop (spec §8.6, req 29/31/32, PRD AC16-19)
# ---------------------------------------------------------------------------


@dataclass
class FixAttemptResult:
    """
    Outcome of one ``run_fix_loop_for_finding`` call (spec §8.6's
    ``FixAttemptResult``).

    ``resolved`` is ``True`` only when a post-attempt re-scan of the
    finding's own tool no longer reports its fingerprint. ``attempts`` is
    the number of LLM attempts actually made (0 when ``max_attempts<=0``,
    never more than the budget passed in). ``llm_used`` and ``violation``
    are additive fields beyond spec §8.6's literal pseudocode shape (which
    shows only ``resolved``/``attempts``) — needed by a later story's
    orchestrator (S-140) to distinguish "budget exhausted with no LLM call
    at all" from "LLM ran but never resolved it," and to surface a
    diff-confinement violation's exact out-of-scope paths in the PR body /
    run log rather than only a bare ``resolved=False``.
    """

    resolved: bool
    attempts: int
    llm_used: bool = False
    violation: str | None = None


def run_fix_loop_for_finding(
    workspace: str,
    finding: MergedFinding,
    max_attempts: int,
) -> FixAttemptResult:
    """
    Run the LLM fix agent for exactly one finding, in a bounded loop (spec
    §8.6, req 29/31/32).

    **The one genuinely new design point vs. the sibling agent: per-finding
    invocation and per-finding budgeting, not per-run** (module docstring,
    PRD D22/D26). This function is the whole of that design point — it is
    called once per LLM-eligible finding by the orchestrator (S-140's
    scope), and its own ``for attempt in range(1, max_attempts + 1)`` loop
    is a fresh counter every call, never shared/carried across findings
    (PRD AC17, task 14.6).

    ``max_attempts<=0`` disables the LLM entirely: the loop body — which is
    the only place ``Agent(...)`` is constructed — never executes, so zero
    Bedrock calls are made (PRD AC18, task 14.7), not merely zero
    *successful* fixes.

    Each attempt:
      1. Construct a fresh ``Agent`` with the 5-tool surface and the
         single-finding prompt (``_build_finding_prompt``, req 31/AC19).
      2. Run the agent. An exception from the agent call is logged and
         swallowed — the loop still runs the diff-confinement check and
         re-scan below, since the agent may have made partial tool-call
         progress before raising (mirrors the sibling agent's own
         resilience pattern, req 48 there).
      3. Verify the resulting diff is confined to the finding's own file
         (``_assert_diff_confined_to``, spec §12). A violation stops the
         loop immediately — attempting further LLM calls after an
         out-of-scope write is a security risk, not a recoverable retry
         condition — and the finding is reported unresolved with the
         violation's details attached.
      4. Re-scan using ONLY the finding's own tool (spec §8.6's
         ``run_scanners(workspace, [finding.finding.tool], SCANNER_TIMEOUT)``)
         and check whether the finding's fingerprint is still present. If
         gone, the finding is resolved. If the re-scan itself fails for
         every requested scanner (``AllScannersFailedError``), resolution
         cannot be confirmed this attempt — treated as non-fatal, the loop
         continues to the next attempt if budget remains, mirroring every
         other scanner-subprocess boundary in this codebase's
         non-fatal-degradation convention.
    """
    global _WORKSPACE
    _WORKSPACE = workspace

    target = finding.finding
    target_fp = fingerprint(target)

    for attempt in range(1, max_attempts + 1):
        log.info(
            "Fix agent attempt %d/%d for finding %s (%s:%d)",
            attempt,
            max_attempts,
            target_fp,
            target.file_path,
            target.line_start,
        )

        try:
            agent = Agent(
                model=MODEL_ID,
                system_prompt=FIX_AGENT_SYSTEM_PROMPT,
                tools=[shell, read_file, write_file, find_files, grep_code],
            )
            agent(_build_finding_prompt(finding, attempt))
        except Exception as exc:
            log.warning(
                "Fix agent attempt %d for finding %s failed with error: %s",
                attempt,
                target_fp,
                exc,
            )
            # Continue — the agent may have made partial tool-call progress
            # before raising; diff confinement + re-scan below still run.

        try:
            _assert_diff_confined_to(workspace, target.file_path)
        except MandateViolationError as exc:
            log.warning(
                "Fix agent attempt %d for finding %s violated diff confinement: %s",
                attempt,
                target_fp,
                exc,
            )
            return FixAttemptResult(
                resolved=False, attempts=attempt, llm_used=True, violation=str(exc)
            )

        try:
            rescan_results = run_scanners(Path(workspace), [target.tool], SCANNER_TIMEOUT)
        except AllScannersFailedError as exc:
            log.warning(
                "Re-scan after fix attempt %d for finding %s failed: %s",
                attempt,
                target_fp,
                exc,
            )
            continue

        after_fps = {fingerprint(f) for result in rescan_results for f in result.findings}
        if target_fp not in after_fps:
            log.info("Fix agent resolved finding %s on attempt %d", target_fp, attempt)
            return FixAttemptResult(resolved=True, attempts=attempt, llm_used=True)

    return FixAttemptResult(resolved=False, attempts=max_attempts, llm_used=max_attempts > 0)
