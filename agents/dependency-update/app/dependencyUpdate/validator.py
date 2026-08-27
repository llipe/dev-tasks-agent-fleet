"""
Validation runner — executes lint, format, typecheck, and test scripts
with fix-and-retry for lint/format.

The validator is opinionated (D20): ``test`` is the only mandatory check.
Optional checks (lint, format, typecheck) that are absent from the repository's
script contract are recorded as ``SKIPPED`` and never fail the run. Lint and
format support a single fix-and-retry pass when a fix-variant script exists.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from enum import StrEnum

from config import TEST_TIMEOUT, TOOL_COMMAND_TIMEOUT
from toolchain import ScriptContract


class CheckStatus(StrEnum):
    """Outcome of a single validation check."""

    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class CheckResult:
    """Status and captured output for one check."""

    status: CheckStatus
    output: str = ""


@dataclass
class ValidationResult:
    """
    Aggregate result of a validation run.

    ``checks`` maps each logical check name to its :class:`CheckResult`.
    ``passed`` is False as soon as any check is recorded as FAILED; SKIPPED
    checks never cause failure. ``llm_used`` / ``fix_attempts`` are populated
    by the fix agent (issue #75) and are surfaced in the PR body / metrics.
    """

    checks: dict[str, CheckResult] = field(default_factory=dict)
    llm_used: bool = False
    fix_attempts: int = 0

    def record(self, name: str, status: CheckStatus, output: str = "") -> None:
        self.checks[name] = CheckResult(status=status, output=output)

    @property
    def passed(self) -> bool:
        return all(c.status != CheckStatus.FAILED for c in self.checks.values())


# ---------------------------------------------------------------------------
# Command execution
# ---------------------------------------------------------------------------


def _run(cmd: list[str], cwd: str, timeout: int) -> subprocess.CompletedProcess[str]:
    """Run a package-manager script, capturing output. Raises on non-zero exit."""
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
        timeout=timeout,
    )


def _script_cmd(pm: str, script: str) -> list[str]:
    """Build the invocation for a named script under pnpm or npm."""
    return [pm, "run", script]


def _combined_output(source: subprocess.CompletedProcess | subprocess.CalledProcessError) -> str:
    """Concatenate stdout+stderr from a process result or error."""
    out = source.stdout or ""
    err = source.stderr or ""
    return (out + ("\n" if out and err else "") + err).strip()


def _run_check(
    workspace: str,
    pm: str,
    script: str,
    timeout: int,
) -> tuple[bool, str]:
    """Run one script; return (passed, output)."""
    try:
        proc = _run(_script_cmd(pm, script), workspace, timeout)
        return True, _combined_output(proc)
    except subprocess.CalledProcessError as exc:
        return False, _combined_output(exc)
    except subprocess.SubprocessError as exc:  # timeout, etc.
        return False, str(exc)


def _run_fixable_check(
    workspace: str,
    pm: str,
    name: str,
    script: str,
    fix_script: str | None,
    result: ValidationResult,
) -> None:
    """
    Run a check that supports a single fix-and-retry pass.

    If the initial check fails and a ``fix_script`` exists, run the fix once and
    re-check. Records the final status in ``result``.
    """
    passed, output = _run_check(workspace, pm, script, TOOL_COMMAND_TIMEOUT)
    if passed:
        result.record(name, CheckStatus.PASSED, output)
        return

    if fix_script is None:
        result.record(name, CheckStatus.FAILED, output)
        return

    # Attempt the fix once, then re-check regardless of the fix's own exit code.
    _fixed, fix_output = _run_check(workspace, pm, fix_script, TOOL_COMMAND_TIMEOUT)
    passed, output = _run_check(workspace, pm, script, TOOL_COMMAND_TIMEOUT)
    if passed:
        result.record(name, CheckStatus.PASSED, output)
    else:
        result.record(
            name,
            CheckStatus.FAILED,
            f"{output}\n--- after {fix_script} ---\n{fix_output}".strip(),
        )


# ---------------------------------------------------------------------------
# Individual runners
# ---------------------------------------------------------------------------


def run_lint(workspace: str, pm: str, scripts: ScriptContract, result: ValidationResult) -> None:
    """Run lint with a fix-and-retry pass when ``lint:fix`` exists."""
    if scripts.lint is None:
        result.record("lint", CheckStatus.SKIPPED, "no lint script")
        return
    _run_fixable_check(workspace, pm, "lint", scripts.lint, scripts.lint_fix, result)


def run_format(workspace: str, pm: str, scripts: ScriptContract, result: ValidationResult) -> None:
    """Run format check with a fix-and-retry pass when a format fix script exists."""
    if scripts.format is None:
        result.record("format", CheckStatus.SKIPPED, "no format script")
        return
    _run_fixable_check(workspace, pm, "format", scripts.format, scripts.format_fix, result)


def run_typecheck(
    workspace: str, pm: str, scripts: ScriptContract, result: ValidationResult
) -> None:
    """Run typecheck (no fix-and-retry — type errors need code changes)."""
    if scripts.typecheck is None:
        result.record("typecheck", CheckStatus.SKIPPED, "no typecheck script")
        return
    passed, output = _run_check(workspace, pm, scripts.typecheck, TOOL_COMMAND_TIMEOUT)
    result.record("typecheck", CheckStatus.PASSED if passed else CheckStatus.FAILED, output)


def run_tests(workspace: str, pm: str, scripts: ScriptContract, result: ValidationResult) -> None:
    """Run the mandatory test script with the longer test timeout."""
    passed, output = _run_check(workspace, pm, scripts.test, TEST_TIMEOUT)
    result.record("test", CheckStatus.PASSED if passed else CheckStatus.FAILED, output)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run_validation(workspace: str, pm: str, scripts: ScriptContract) -> ValidationResult:
    """
    Run the full validation pipeline in order: lint -> format -> typecheck -> test.

    Optional checks that are absent are recorded as SKIPPED. All checks run
    (there is no early exit) so the resulting :class:`ValidationResult` reports
    every check's status for the PR body.
    """
    result = ValidationResult()
    run_lint(workspace, pm, scripts, result)
    run_format(workspace, pm, scripts, result)
    run_typecheck(workspace, pm, scripts, result)
    run_tests(workspace, pm, scripts, result)
    return result
