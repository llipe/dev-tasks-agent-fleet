"""
LLM fix agent — Strands-based agent with bounded tool access for
resolving lint/format/typecheck/test failures after dependency updates.

Requirements (from PRD §7.6):
    - req 44: LLM invoked only when validation fails after a dependency update
    - req 45: exactly 5 tools: shell, read_file, write_file, find_files, grep_code
    - req 46: every path-taking tool resolves against workspace root; escapes refused
    - req 47: system prompt forbids weakening tests, rolling back deps, widening ranges
    - req 48: fix loop bounded by max_fix_attempts; re-validates after each attempt
    - req 49: on success, re-run lint/format/typecheck (model may have touched source)
    - req 50: mandate check — package.json version specifiers must be unchanged
    - req 52: record llm_used and fix_attempts in metrics
"""

from __future__ import annotations

import glob
import json
import logging
import os
import subprocess
from dataclasses import dataclass

from strands import Agent, tool

from config import MODEL_ID, TOOL_COMMAND_TIMEOUT
from toolchain import ScriptContract
from validator import ValidationResult, run_validation

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Path safety (req 46)
# ---------------------------------------------------------------------------

_WORKSPACE: str = ""  # Set by run_fix_loop before creating tools


def _safe_path(rel: str) -> str:
    """
    Resolve a relative path against the workspace root.

    Raises ValueError if the resolved path escapes the workspace via traversal,
    absolute paths, or symlinks.
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
# Tools (req 45 — exactly these 5, no others)
# ---------------------------------------------------------------------------


@tool
def shell(command: str) -> str:
    """
    Run a shell command inside the workspace checkout.

    The command runs with cwd set to the workspace root. Use this for running
    build commands, installing packages, or other operations that need a shell.
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
            timeout=TOOL_COMMAND_TIMEOUT,
        )
        output = (result.stdout or "") + (result.stderr or "")
        # Truncate very long output to avoid context overflow
        if len(output) > 16000:
            output = output[:8000] + "\n...[truncated]...\n" + output[-8000:]
        if result.returncode != 0:
            return f"EXIT CODE {result.returncode}\n{output.strip()}"
        return output.strip() or "(no output)"
    except subprocess.TimeoutExpired:
        return f"ERROR: Command timed out after {TOOL_COMMAND_TIMEOUT}s"
    except Exception as exc:
        return f"ERROR: {exc}"


@tool
def read_file(path: str) -> str:
    """
    Read the contents of a file inside the workspace.

    The path must be relative to the workspace root. Absolute paths and paths
    that escape the workspace (e.g. ../) are rejected.
    """
    try:
        resolved = _safe_path(path)
    except ValueError as exc:
        return f"ERROR: {exc}"

    try:
        with open(resolved, encoding="utf-8", errors="replace") as f:
            content = f.read()
        # Truncate very large files
        if len(content) > 64000:
            content = content[:32000] + "\n...[truncated]...\n" + content[-32000:]
        return content
    except OSError as exc:
        return f"ERROR: Cannot read file: {exc}"


@tool
def write_file(path: str, content: str) -> str:
    """
    Write content to a file inside the workspace.

    The path must be relative to the workspace root. Absolute paths and paths
    that escape the workspace (e.g. ../) are rejected. Parent directories are
    created if needed.
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
    Example patterns: '**/*.ts', 'src/**/*.py', '*.json'
    """
    if not _WORKSPACE:
        return "ERROR: Workspace not set"

    try:
        matches = glob.glob(pattern, root_dir=_WORKSPACE, recursive=True)
        # Filter out node_modules and .git for sanity
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
        # Cap results to prevent flooding
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
                     Defaults to all files. Example: '**/*.ts'

    Returns matching lines with file:line_number:content format.
    """
    if not _WORKSPACE:
        return "ERROR: Workspace not set"

    try:
        # Use grep for efficiency when available
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
        # Truncate
        lines = output.split("\n")
        if len(lines) > 100:
            return "\n".join(lines[:100]) + f"\n... ({len(lines) - 100} more matches)"
        return output
    except subprocess.TimeoutExpired:
        return "ERROR: grep timed out"
    except Exception as exc:
        return f"ERROR: {exc}"


# ---------------------------------------------------------------------------
# System prompt (req 47)
# ---------------------------------------------------------------------------

FIX_AGENT_SYSTEM_PROMPT = """\
You are a code-fix agent. Your job is to fix lint, format, typecheck, or test \
failures that appeared after a dependency update in a JavaScript/TypeScript project.

RULES YOU MUST FOLLOW:
1. Do NOT delete, skip, disable, or weaken any test to make the suite green.
2. Do NOT edit dependency versions in package.json to roll the update back.
3. Do NOT widen a declared semver range or perform a major version bump.
4. Do NOT add, remove, or change entries in the "dependencies" or \
"devDependencies" sections of package.json.
5. Do NOT modify lockfiles (package-lock.json, pnpm-lock.yaml) directly.

Your purpose is to adapt the SOURCE CODE so it works with the updated \
dependencies. Typical fixes include:
- Updating import paths or named exports that changed in a new version.
- Fixing type errors caused by stricter or changed type signatures.
- Adjusting API calls to match new function signatures.
- Updating configuration files (tsconfig, eslint, prettier) if needed.

You have these tools available:
- shell: Run shell commands in the workspace.
- read_file: Read a file by relative path.
- write_file: Write content to a file by relative path.
- find_files: Find files by glob pattern.
- grep_code: Search for patterns in source files.

Work methodically:
1. First read the error output to understand what failed.
2. Read the relevant source files.
3. Make targeted, minimal changes to fix the errors.
4. Verify your fix by running the failing command again.
"""


# ---------------------------------------------------------------------------
# Mandate verification (req 50)
# ---------------------------------------------------------------------------


@dataclass
class MandateViolation:
    """Details of a package.json mandate violation."""

    package: str
    field: str  # "dependencies" or "devDependencies"
    before: str | None
    after: str | None
    reason: str


def _read_pkg_dependencies(pkg_json_path: str) -> dict[str, dict[str, str]]:
    """Read dependencies and devDependencies from a package.json file."""
    try:
        with open(pkg_json_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"dependencies": {}, "devDependencies": {}}

    deps = data.get("dependencies", {})
    dev_deps = data.get("devDependencies", {})
    return {
        "dependencies": deps if isinstance(deps, dict) else {},
        "devDependencies": dev_deps if isinstance(dev_deps, dict) else {},
    }


def verify_no_mandate_violation(
    workspace: str, pkg_json_before: dict[str, dict[str, str]]
) -> list[MandateViolation]:
    """
    Verify that package.json version specifiers are unchanged from pre-update state.

    Compares the current package.json against the snapshot taken before the fix
    agent ran. Detects:
      - Widened semver ranges (e.g. ^1.0.0 → ^2.0.0)
      - New dependencies added
      - Removed dependencies
      - Any version specifier change

    Note: changes that the package manager itself makes (e.g. pinning in lockfile)
    do NOT appear in package.json, so this check catches only model misbehavior.

    Returns a list of violations (empty = pass).
    """
    pkg_json_path = os.path.join(workspace, "package.json")
    pkg_json_after = _read_pkg_dependencies(pkg_json_path)

    violations: list[MandateViolation] = []

    for field in ("dependencies", "devDependencies"):
        before_deps = pkg_json_before.get(field, {})
        after_deps = pkg_json_after.get(field, {})

        # Check for new dependencies
        for pkg in after_deps:
            if pkg not in before_deps:
                violations.append(
                    MandateViolation(
                        package=pkg,
                        field=field,
                        before=None,
                        after=after_deps[pkg],
                        reason="new dependency added",
                    )
                )

        # Check for removed dependencies
        for pkg in before_deps:
            if pkg not in after_deps:
                violations.append(
                    MandateViolation(
                        package=pkg,
                        field=field,
                        before=before_deps[pkg],
                        after=None,
                        reason="dependency removed",
                    )
                )

        # Check for changed version specifiers
        for pkg in before_deps:
            if pkg in after_deps and before_deps[pkg] != after_deps[pkg]:
                violations.append(
                    MandateViolation(
                        package=pkg,
                        field=field,
                        before=before_deps[pkg],
                        after=after_deps[pkg],
                        reason="version specifier changed",
                    )
                )

    return violations


# ---------------------------------------------------------------------------
# Fix loop (req 48)
# ---------------------------------------------------------------------------


def run_fix_loop(
    workspace: str,
    pm: str,
    scripts: ScriptContract,
    max_attempts: int,
    initial_result: ValidationResult,
) -> ValidationResult:
    """
    Run the LLM fix agent in a bounded loop (req 48).

    1. Create a Strands Agent with the 5 tools and the system prompt.
    2. Feed it the validation failure output.
    3. After each attempt, re-run the validation suite.
    4. Stop when validation passes or attempt budget exhausted.

    Returns the final ValidationResult with llm_used=True and fix_attempts set.
    """
    global _WORKSPACE
    _WORKSPACE = workspace

    if max_attempts <= 0:
        return initial_result

    # Build the failure description for the agent
    failure_description = _build_failure_description(initial_result)

    val_result = initial_result
    val_result.llm_used = True
    val_result.fix_attempts = 0

    for attempt in range(1, max_attempts + 1):
        val_result.fix_attempts = attempt
        log.info("Fix agent attempt %d/%d", attempt, max_attempts)

        try:
            agent = Agent(
                model=MODEL_ID,
                system_prompt=FIX_AGENT_SYSTEM_PROMPT,
                tools=[shell, read_file, write_file, find_files, grep_code],
            )

            prompt = (
                f"The following validation checks failed after a dependency update. "
                f"Fix the source code so these checks pass.\n\n"
                f"{failure_description}"
            )
            if attempt > 1:
                # On retries, include the latest failure output
                failure_description = _build_failure_description(val_result)
                prompt = (
                    f"Previous fix attempt did not resolve all issues. "
                    f"Here are the remaining failures:\n\n"
                    f"{failure_description}"
                )

            # Run the agent
            agent(prompt)

        except Exception as exc:
            log.warning("Fix agent attempt %d failed with error: %s", attempt, exc)
            # Continue to re-validate — the agent may have made partial progress

        # Re-run validation after agent attempt (req 48)
        val_result = run_validation(workspace, pm, scripts)
        val_result.llm_used = True
        val_result.fix_attempts = attempt

        if val_result.passed:
            log.info("Fix agent succeeded on attempt %d", attempt)
            break

    return val_result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_failure_description(result: ValidationResult) -> str:
    """Build a description of failed checks for the fix agent prompt."""
    parts: list[str] = []
    for name, check in result.checks.items():
        if check.status.value == "failed":
            output_preview = check.output[:4000] if check.output else "(no output)"
            parts.append(f"## {name} — FAILED\n```\n{output_preview}\n```")
    return "\n\n".join(parts) if parts else "No specific failure details available."
