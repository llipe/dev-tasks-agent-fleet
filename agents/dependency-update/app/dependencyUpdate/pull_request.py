"""
Pull request creation — branch management, commit, push with an ephemeral
credential helper, PR body builder, and idempotency check.

Requirements (from PRD §7.7, reqs 53-58; spec §8.9):
    - req 53: branch ``deps/update-YYYYMMDD-HHMMSS``; commit
      ``chore(deps): automated dependency update``; never push to default branch.
    - req 54: idempotency — an existing ``deps/update-*`` PR short-circuits the run
      to ``succeeded / not_applicable`` and records the existing PR URL as artifact.
    - req 55: PR body assembled from sections and passed via ``--body-file``
      (never inline ``--body`` — repo git invariant).
    - req 56: PR body sections — security summary, fixed advisories, major_required,
      unknown, non-semver, package changes (capped 30), validation results, AI warning.
    - req 57: PR recorded as a ``run_artifacts`` row of type ``pull_request``.
    - req 58: token refresh before push if >45 min elapsed; token supplied via an
      ephemeral credential helper, never embedded in the remote URL.
    - req 43 (D25): the PR is opened BEFORE a MAJOR_UPDATE_REQUIRED terminates the run.

The module is deliberately split into a pure PR-body builder (unit-testable with no
I/O) and thin subprocess wrappers around ``git`` / ``gh`` (component-testable with
mocked CLIs). All error output is scrubbed of the installation token before it
propagates, mirroring the clone path in ``main.py``.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime

from audit import PackageChange
from classifier import ClassifiedAdvisory
from scrubber import scrub_process_error
from validator import CheckStatus, ValidationResult

# Cap the package-changes table for readability (req 56).
_PACKAGE_CHANGES_CAP = 30

# Commit message and branch prefix are fixed contract values (req 53).
_COMMIT_MESSAGE = "chore(deps): automated dependency update"
_BRANCH_PREFIX = "deps/update-"
_PR_TITLE = "chore(deps): automated dependency update"


class PullRequestError(Exception):
    """Raised when PR creation fails after the workspace changes are staged."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


@dataclass
class PullRequestResult:
    """Outcome of the open-PR step."""

    url: str | None
    created: bool  # True if this run opened a new PR
    existed: bool  # True if idempotency short-circuited (a PR already existed)
    branch: str | None = None


# ---------------------------------------------------------------------------
# Branch naming (req 53)
# ---------------------------------------------------------------------------


def branch_name(now: datetime | None = None) -> str:
    """Return a ``deps/update-YYYYMMDD-HHMMSS`` branch name (UTC)."""
    ts = (now or datetime.now(UTC)).strftime("%Y%m%d-%H%M%S")
    return f"{_BRANCH_PREFIX}{ts}"


# ---------------------------------------------------------------------------
# Idempotency check (req 54)
# ---------------------------------------------------------------------------


def existing_pr(workspace: str, token: str) -> str | None:
    """
    Return the URL of an existing open ``deps/update-*`` PR, or None.

    Uses ``gh pr list`` filtered to open PRs whose head branch begins with the
    ``deps/update-`` prefix. ``gh`` is authenticated via the per-call ``GH_TOKEN``
    environment variable so the token never lands on the command line.
    """
    env = _gh_env(token)
    try:
        proc = subprocess.run(
            [
                "gh",
                "pr",
                "list",
                "--state",
                "open",
                "--json",
                "url,headRefName",
                "--limit",
                "100",
            ],
            cwd=workspace,
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
            env=env,
        )
    except subprocess.CalledProcessError as exc:
        scrub_process_error(exc, [token])
        raise PullRequestError("PR_LIST_FAILED", f"gh pr list failed: {exc.stderr}") from exc

    if not proc.stdout.strip():
        return None

    try:
        prs = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None

    for pr in prs:
        head = pr.get("headRefName", "")
        if head.startswith(_BRANCH_PREFIX):
            return pr.get("url")
    return None


# ---------------------------------------------------------------------------
# Push with ephemeral credential helper (req 58)
# ---------------------------------------------------------------------------


def _gh_env(token: str) -> dict[str, str]:
    """Return an environment dict with GH_TOKEN set for gh CLI calls."""
    env = os.environ.copy()
    env["GH_TOKEN"] = token
    return env


def _push_with_credential_helper(workspace: str, token: str, branch: str) -> None:
    """
    Push ``branch`` to origin using an ephemeral credential helper (req 58).

    The token is passed to git via ``-c credential.helper=`` set to an inline
    shell snippet that echoes the token as the password for any HTTPS host. This
    keeps the token out of the remote URL and out of ``.git/config`` — the helper
    lives only for the duration of the single push invocation.
    """
    # The helper prints username + password on stdin protocol. `x-access-token`
    # is GitHub's conventional username for App installation tokens.
    helper = f"!f() {{ echo username=x-access-token; echo password={token}; }}; f"
    try:
        subprocess.run(
            [
                "git",
                "-c",
                f"credential.helper={helper}",
                "push",
                "--set-upstream",
                "origin",
                branch,
            ],
            cwd=workspace,
            capture_output=True,
            text=True,
            check=True,
            timeout=120,
        )
    except subprocess.CalledProcessError as exc:
        scrub_process_error(exc, [token])
        raise PullRequestError("PUSH_FAILED", f"git push failed: {exc.stderr}") from exc


# ---------------------------------------------------------------------------
# PR creation (req 53, 55, 58)
# ---------------------------------------------------------------------------


def create_pr(
    workspace: str,
    token: str,
    base: str,
    body: str,
    branch: str | None = None,
    now: datetime | None = None,
) -> str:
    """
    Create a branch, commit the working changes, push, and open a PR.

    Steps:
      1. Create the ``deps/update-*`` branch (never the default branch — req 53).
      2. Stage all changes and commit with the fixed message.
      3. Push via the ephemeral credential helper (req 58).
      4. ``gh pr create --body-file`` (never inline ``--body`` — req 55).

    Returns the created PR URL. The token is scrubbed from any error output.
    """
    br = branch or branch_name(now)

    # 1. Create and switch to the update branch.
    _git(workspace, ["checkout", "-b", br], token)

    # 2. Stage and commit all working-tree changes.
    _git(workspace, ["add", "-A"], token)
    _git(workspace, ["commit", "-m", _COMMIT_MESSAGE], token)

    # 3. Push via ephemeral credential helper.
    _push_with_credential_helper(workspace, token, br)

    # 4. Open the PR with the body passed as a file (never inline).
    body_path = _write_body_file(workspace, body)
    try:
        env = _gh_env(token)
        proc = subprocess.run(
            [
                "gh",
                "pr",
                "create",
                "--base",
                base,
                "--head",
                br,
                "--title",
                _PR_TITLE,
                "--body-file",
                body_path,
            ],
            cwd=workspace,
            capture_output=True,
            text=True,
            check=True,
            timeout=90,
            env=env,
        )
    except subprocess.CalledProcessError as exc:
        scrub_process_error(exc, [token])
        raise PullRequestError("PR_CREATE_FAILED", f"gh pr create failed: {exc.stderr}") from exc
    finally:
        with contextlib.suppress(OSError):
            os.unlink(body_path)

    url = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    return url


def _git(workspace: str, args: list[str], token: str) -> subprocess.CompletedProcess[str]:
    """Run a git subcommand in the workspace, scrubbing the token on failure."""
    try:
        return subprocess.run(
            ["git", *args],
            cwd=workspace,
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
    except subprocess.CalledProcessError as exc:
        scrub_process_error(exc, [token])
        raise PullRequestError("GIT_FAILED", f"git {args[0]} failed: {exc.stderr}") from exc


def _write_body_file(workspace: str, body: str) -> str:
    """Write the PR body to a temp file and return its path (req 55)."""
    fd, path = tempfile.mkstemp(prefix="pr-body-", suffix=".md", dir=workspace)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(body)
    return path


# ---------------------------------------------------------------------------
# PR body builder (req 55, 56; spec §8.9)
# ---------------------------------------------------------------------------


def build_pr_body(
    vuln_before: int,
    vuln_after: int,
    fixed_advisories: list[ClassifiedAdvisory],
    major_required: list[ClassifiedAdvisory],
    unknown_advisories: list[ClassifiedAdvisory],
    non_semver_changes: list[PackageChange],
    upgraded: list[PackageChange],
    validation: ValidationResult,
    llm_used: bool,
    fix_attempts: int,
) -> str:
    """
    Assemble the PR body markdown from conditional sections (spec §8.9).

    Sections 1 (security summary), 6 (package changes), and 7 (validation results)
    are always present. Sections 2-5 and 8 appear only when they carry content.
    """
    sections: list[str] = []

    # 1. Security summary table (always present).
    sections.append(_security_summary(vuln_before, vuln_after, len(fixed_advisories)))

    # 2. Fixed advisories table.
    if fixed_advisories:
        sections.append(_fixed_advisories_table(fixed_advisories))

    # 3. MAJOR_REQUIRED section (prominent).
    if major_required:
        sections.append(_major_required_section(major_required))

    # 4. Unknown advisories section.
    if unknown_advisories:
        sections.append(_unknown_advisories_section(unknown_advisories))

    # 5. Non-semver accepted section.
    if non_semver_changes:
        sections.append(_non_semver_section(non_semver_changes))

    # 6. Package changes table (always present).
    sections.append(_package_changes_table(upgraded))

    # 7. Validation results table (always present).
    sections.append(_validation_table(validation))

    # 8. AI modification warning (only when the LLM fix agent ran).
    if llm_used:
        sections.append(_ai_warning(fix_attempts))

    sections.append("---")
    sections.append("*Generated by `dependency-update` agent. Review before merging.*")

    return "\n\n".join(sections)


def _security_summary(vuln_before: int, vuln_after: int, fixed_count: int) -> str:
    """Section 1 — before/after vulnerability counts and advisories fixed."""
    return (
        "## Security Summary\n\n"
        "| Metric | Value |\n"
        "|---|---|\n"
        f"| Vulnerabilities before | {vuln_before} |\n"
        f"| Vulnerabilities after | {vuln_after} |\n"
        f"| Advisories fixed | {fixed_count} |"
    )


def _fixed_advisories_table(advisories: list[ClassifiedAdvisory]) -> str:
    """Section 2 — advisories closed by this update (in-range)."""
    rows = "\n".join(
        f"| {_md_cell(a.module)} | {_md_cell(a.severity)} | "
        f"{_md_cell(a.title)} | {_md_cell(a.patched_versions)} |"
        for a in advisories
    )
    return (
        "## Fixed Advisories\n\n"
        "| Package | Severity | Title | Patched |\n"
        "|---|---|---|---|\n"
        f"{rows}"
    )


def _major_required_section(advisories: list[ClassifiedAdvisory]) -> str:
    """Section 3 — advisories that need a manual major-version migration."""
    rows = "\n".join(
        f"| {_md_cell(a.module)} | {_md_cell(a.severity)} | "
        f"{_md_cell(a.title)} | {_md_cell(a.patched_versions)} |"
        for a in advisories
    )
    return (
        "## \u26a0\ufe0f Major Version Required\n\n"
        "These advisories are **not fixed** by this PR — they require a major "
        "version bump and manual migration:\n\n"
        "| Package | Severity | Title | Patched |\n"
        "|---|---|---|---|\n"
        f"{rows}"
    )


def _unknown_advisories_section(advisories: list[ClassifiedAdvisory]) -> str:
    """Section 4 — advisories whose eligibility could not be determined."""
    rows = "\n".join(
        f"| {_md_cell(a.module)} | {_md_cell(a.severity)} | "
        f"{_md_cell(a.title)} | {_md_cell(a.patched_versions or '(none)')} |"
        for a in advisories
    )
    return (
        "## Unresolved Advisories\n\n"
        "The classifier could not determine whether these are fixable "
        "automatically — review manually:\n\n"
        "| Package | Severity | Title | Patched |\n"
        "|---|---|---|---|\n"
        f"{rows}"
    )


def _non_semver_section(changes: list[PackageChange]) -> str:
    """Section 5 — packages upgraded to a non-semver version (accepted, warned)."""
    rows = "\n".join(
        f"| {_md_cell(c.name)} | {_md_cell(c.old_version or '(new)')} | "
        f"{_md_cell(c.new_version or '(removed)')} |"
        for c in changes
    )
    return (
        "## Non-semver Version Changes\n\n"
        "These packages moved to a version that does not parse as semver — "
        "accepted but flagged for awareness:\n\n"
        "| Package | Before | After |\n"
        "|---|---|---|\n"
        f"{rows}"
    )


def _package_changes_table(changes: list[PackageChange]) -> str:
    """Section 6 — every package change, capped at 30 rows for readability."""
    if not changes:
        return "## Package Changes\n\n_No package changes._"

    shown = changes[:_PACKAGE_CHANGES_CAP]
    rows = "\n".join(
        f"| {_md_cell(c.name)} | {_md_cell(c.action)} | "
        f"{_md_cell(c.old_version or '\u2014')} | {_md_cell(c.new_version or '\u2014')} |"
        for c in shown
    )
    table = (
        f"## Package Changes\n\n| Package | Change | Before | After |\n|---|---|---|---|\n{rows}"
    )
    remaining = len(changes) - len(shown)
    if remaining > 0:
        table += f"\n\n_\u2026 and {remaining} more package change(s) not shown._"
    return table


def _validation_table(validation: ValidationResult) -> str:
    """Section 7 — per-check validation status."""
    order = ("lint", "format", "typecheck", "test")
    rows: list[str] = []
    for name in order:
        check = validation.checks.get(name)
        if check is None:
            continue
        rows.append(f"| {name} | {_status_label(check.status)} |")
    # Include any additional checks not in the canonical order.
    for name, check in validation.checks.items():
        if name not in order:
            rows.append(f"| {name} | {_status_label(check.status)} |")

    body = "\n".join(rows) if rows else "| (none) | \u2014 |"
    return "## Validation Results\n\n| Check | Result |\n|---|---|\n" + body


def _ai_warning(fix_attempts: int) -> str:
    """Section 8 — disclosure that an LLM modified source code (req 56)."""
    return (
        "## \U0001f916 AI-Assisted Modifications\n\n"
        f"An AI fix agent modified source code across **{fix_attempts}** "
        "attempt(s) to make the test suite pass after the dependency update. "
        "Package version specifiers were verified unchanged, but the code "
        "changes themselves warrant careful human review before merging."
    )


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def open_pr_if_needed(
    workspace: str,
    token: str,
    base: str,
    body: str,
    now: datetime | None = None,
) -> PullRequestResult:
    """
    Idempotent PR open (req 54).

    1. Check for an existing open ``deps/update-*`` PR. If found, short-circuit
       to a result with ``existed=True`` and the existing URL — no branch, no
       push, no new PR.
    2. Otherwise create the branch, commit, push, and open a new PR.

    Returns a :class:`PullRequestResult`. Callers record the URL as a
    ``pull_request`` artifact (req 57) regardless of which branch was taken.
    """
    prior = existing_pr(workspace, token)
    if prior is not None:
        return PullRequestResult(url=prior, created=False, existed=True)

    br = branch_name(now)
    url = create_pr(workspace, token, base, body, branch=br, now=now)
    return PullRequestResult(url=url or None, created=True, existed=False, branch=br)


def _status_label(status: CheckStatus) -> str:
    """Render a check status as a compact human label with a glyph."""
    if status == CheckStatus.PASSED:
        return "\u2705 passed"
    if status == CheckStatus.FAILED:
        return "\u274c failed"
    return "\u2014 skipped"


def _md_cell(value: str) -> str:
    """Escape a value for safe inclusion in a single markdown table cell."""
    return str(value).replace("|", "\\|").replace("\n", " ").strip()
