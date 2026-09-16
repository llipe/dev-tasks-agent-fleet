"""
Pull request creation — branch management, commit, push with an ephemeral
credential helper, PR body builder, and idempotency check (spec §8.9, PRD
requirements 38-43, story S-139).

Branch/idempotency/push/`--body-file` mechanics are ported near-verbatim
from the sibling (`dependency-update`) agent's `pull_request.py` (research
item 6, S1) — same credential-helper push, same `gh pr list` idempotency
pattern, same "body always via `--body-file`, never inline `--body`" rule.
Only the fixed contract values differ (branch prefix, commit message, PR
title) and the PR body's *content* is entirely new (requirement 42).

Requirements:
    - req 38: branch `security/fix-<UTC timestamp YYYYMMDD-HHMMSS>`.
    - req 39: commit `fix(security): automated mechanical security fixes`
      (Conventional Commits).
    - req 40: never push to or merge into the target repo's default branch.
    - req 41: idempotency — an already-open `security/fix-*` PR short-
      circuits the run to `succeeded` / `not_applicable`, no second branch
      or PR; the existing PR's URL is recorded as the run artifact.
    - req 42: PR body assembled from sections and passed via `--body-file`
      (never inline `--body`) — summary table, fixed-findings table,
      always-present remaining-manual table (even when empty — "no false
      all-clear"), conditional D24-boundary section, conditional major-
      version-guard section, conditional AI-modification warning, and an
      always-present re-scan confirmation line.
    - req 43: the PR is recorded as a `run_artifacts` row of type
      `pull_request` with its URL and title (caller's responsibility, not
      this module's — mirrors the sibling agent's split).

S-139 built `pull_request.py` standalone, without wiring it into `main.py`'s
orchestrator loop — `build_pr_body()`'s `PipelineState` slice, defined *in
this module* rather than imported from an orchestrator-level type (since no
such type existed yet), was that story's own explicit forward-reference gap
for S-140 to resolve. **Resolved by S-140:** `main.py`'s `open_pr` step
constructs this exact `PipelineState` shape directly at its
`open_pr_if_needed()`/`build_pr_body()` call site — no superset was needed.
`fixed` is populated from the full `mechanical` findings list (a clean
re-scan gate, D23, is the orchestrator's proof that every targeted
fingerprint is gone, so all of `mechanical` counts as fixed by
construction); `manual_remaining`/`unscannable_remaining` come straight from
`classifier.py`'s own bucket split; `dependency_update_boundary`/
`major_version_guard` are derived at the call site as the two disjoint
`Bucket.MANUAL` subsets whose `remediation.kind == "version_bump"`
(`lockfile_managed` True vs. False respectively — `classifier.py`'s own
branch order already guarantees mutual exclusivity, see that module's
docstring); `llm_used`/`llm_fixed` come from the `fix` step's own
per-finding LLM invocation bookkeeping; `rescan_before_count`/
`rescan_after_count` are the orchestrator's pre-fix and post-fix merged
finding-set sizes. This class remains defined here (not moved to `main.py`)
since it is `build_pr_body()`'s own input contract, not a general
pipeline-wide state type — `main.py` has no need for a shared
`PipelineState` type beyond this one call site. This mirrors `main.py`'s
own precedent for the same class of forward-reference gap (see `main.py`'s
`determine_outcome()` docstring on the 3-tuple return shape, also resolved
by S-140).
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime

from dedupe import MergedFinding
from scrubber import scrub_process_error

# Commit message, branch prefix, and PR title are fixed contract values
# (req 38-39).
_COMMIT_MESSAGE = "fix(security): automated mechanical security fixes"
_BRANCH_PREFIX = "security/fix-"
_PR_TITLE = "fix(security): automated mechanical security fixes"


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
# Branch naming (req 38)
# ---------------------------------------------------------------------------


def branch_name(now: datetime | None = None) -> str:
    """Return a ``security/fix-YYYYMMDD-HHMMSS`` branch name (UTC)."""
    ts = (now or datetime.now(UTC)).strftime("%Y%m%d-%H%M%S")
    return f"{_BRANCH_PREFIX}{ts}"


# ---------------------------------------------------------------------------
# Idempotency check (req 41)
# ---------------------------------------------------------------------------


def existing_pr(workspace: str, token: str) -> str | None:
    """
    Return the URL of an existing open ``security/fix-*`` PR, or None.

    Uses ``gh pr list`` filtered to open PRs whose head branch begins with
    the ``security/fix-`` prefix. ``gh`` is authenticated via the per-call
    ``GH_TOKEN`` environment variable so the token never lands on the
    command line — identical pattern to the sibling agent's
    `pull_request.existing_pr`.
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
# Push with ephemeral credential helper (ported verbatim from the sibling)
# ---------------------------------------------------------------------------


def _gh_env(token: str) -> dict[str, str]:
    """Return an environment dict with GH_TOKEN set for gh CLI calls."""
    env = os.environ.copy()
    env["GH_TOKEN"] = token
    return env


def _push_with_credential_helper(workspace: str, token: str, branch: str) -> None:
    """
    Push ``branch`` to origin using an ephemeral credential helper.

    The token is passed to git via ``-c credential.helper=`` set to an
    inline shell snippet that echoes the token as the password for any
    HTTPS host. This keeps the token out of the remote URL and out of
    ``.git/config`` — the helper lives only for the duration of the single
    push invocation. Identical mechanism to the sibling agent's
    `_push_with_credential_helper` (req 40's "never push to default
    branch" is enforced by the caller always passing the fix branch, never
    the base).
    """
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
# PR creation (req 38-40, 42)
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
      1. Create the ``security/fix-*`` branch (never the default branch —
         req 40).
      2. Stage all changes and commit with the fixed message (req 39).
      3. Push via the ephemeral credential helper.
      4. ``gh pr create --body-file`` (never inline ``--body`` — req 42).

    Returns the created PR URL. The token is scrubbed from any error output.
    """
    br = branch or branch_name(now)

    # 1. Create and switch to the fix branch.
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
    """Write the PR body to a temp file and return its path (req 42)."""
    fd, path = tempfile.mkstemp(prefix="pr-body-", suffix=".md", dir=workspace)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(body)
    return path


def open_pr_if_needed(
    workspace: str,
    token: str,
    base: str,
    body: str,
    now: datetime | None = None,
) -> PullRequestResult:
    """
    Idempotent PR open (req 41).

    1. Check for an existing open ``security/fix-*`` PR. If found,
       short-circuit to a result with ``existed=True`` and the existing
       URL — no branch, no push, no new PR (PRD AC-22).
    2. Otherwise create the branch, commit, push, and open a new PR.

    Returns a :class:`PullRequestResult`. Callers record the URL as a
    ``pull_request`` artifact (req 43) regardless of which branch was
    taken.
    """
    prior = existing_pr(workspace, token)
    if prior is not None:
        return PullRequestResult(url=prior, created=False, existed=True)

    br = branch_name(now)
    url = create_pr(workspace, token, base, body, branch=br, now=now)
    return PullRequestResult(url=url or None, created=True, existed=False, branch=br)


# ---------------------------------------------------------------------------
# PipelineState — the minimal slice build_pr_body() needs (see module
# docstring for why this is defined here rather than imported from main.py).
# ---------------------------------------------------------------------------


@dataclass
class PipelineState:
    """The slice of a `fix`-mode run's state that `build_pr_body()` renders
    (spec §8.9, req 42).

    ``findings_before`` is the total finding count across all five tools
    before the fix (the pre-fix scan, not gated by ``min_severity`` — req
    63 never narrows what is reported). ``fixed`` is every `MergedFinding`
    the run successfully fixed and the re-scan gate confirmed cleared.
    ``manual_remaining``/``unscannable_remaining`` are the post-fix
    remainder in each bucket (D22).

    ``dependency_update_boundary`` and ``major_version_guard`` are
    *subsets* of ``manual_remaining`` — the findings reclassified `manual`
    specifically under requirement 24 (the D24 lockfile boundary with the
    sibling agent) or requirement 27 (the major-version guard),
    respectively. A finding can appear in at most one of the two per
    `classifier.py`'s branch-order precedence (D24 checked first — see
    `classifier.py`'s module docstring), so the two lists are disjoint by
    construction, but this module does not re-derive or enforce that; it
    only renders whatever the caller supplies.

    ``llm_used``/``llm_fixed`` name which findings (a subset of ``fixed``)
    the LLM escape hatch touched, for the AI-modification warning's
    "naming exactly which findings it touched" requirement (req 42).

    ``rescan_before_count``/``rescan_after_count`` are the re-scan gate's
    own before/after finding counts (`rescan.py`'s `GateResult` does not
    carry raw counts, only fingerprint sets, so the caller supplies them
    separately). `build_pr_body()` is only ever invoked once the re-scan
    gate has already passed (D23 — a `fix`-mode run either produces a
    re-scan-verified PR or no PR at all, spec §8.10), so the confirmation
    line always reports success; there is no "gate failed" rendering path
    in this module because that case never reaches PR creation.
    """

    findings_before: int
    fixed: list[MergedFinding] = field(default_factory=list)
    manual_remaining: list[MergedFinding] = field(default_factory=list)
    unscannable_remaining: list[MergedFinding] = field(default_factory=list)
    dependency_update_boundary: list[MergedFinding] = field(default_factory=list)
    major_version_guard: list[MergedFinding] = field(default_factory=list)
    llm_used: bool = False
    llm_fixed: list[MergedFinding] = field(default_factory=list)
    rescan_before_count: int = 0
    rescan_after_count: int = 0


# ---------------------------------------------------------------------------
# PR body builder (req 42; spec §8.9)
# ---------------------------------------------------------------------------


def build_pr_body(state: PipelineState) -> str:
    """
    Assemble the PR body markdown from `state` (spec §8.9, req 42).

    Sections 1-3 (summary, fixed findings, remaining-manual) are always
    present — the remaining-manual table specifically **always** renders
    its header and table structure even when both remainder lists are
    empty, so a fully-green PR cannot be misread as "no more findings
    exist at all" (req 42's own "no false all-clear" framing, mirroring
    the sibling agent's `major_required` section). The D24-boundary and
    major-version-guard sections are conditional on their respective lists
    being non-empty. The AI-modification warning is conditional on
    ``state.llm_used``. The re-scan confirmation line is always last and
    always present.
    """
    sections: list[str] = [
        _security_summary_table(state),
        _fixed_findings_table(state.fixed),
        _remaining_manual_table(state),
    ]

    if state.dependency_update_boundary:
        sections.append(_dependency_update_boundary_section(state.dependency_update_boundary))

    if state.major_version_guard:
        sections.append(_major_version_guard_section(state.major_version_guard))

    if state.llm_used:
        sections.append(_ai_modification_warning(state.llm_fixed))

    sections.append(_rescan_confirmation_line(state))

    return "\n\n".join(sections)


def _severity_counts(findings: list[MergedFinding]) -> dict[str, int]:
    """Count `findings` by their representative finding's severity value."""
    counts: dict[str, int] = {}
    for m in findings:
        key = m.finding.severity.value
        counts[key] = counts.get(key, 0) + 1
    return counts


def _security_summary_table(state: PipelineState) -> str:
    """Section 1 — total before/fixed/remaining counts, remaining by severity."""
    remaining = state.manual_remaining + state.unscannable_remaining
    severity_counts = _severity_counts(remaining)
    order = ("critical", "high", "medium", "low")
    severity_rows = "\n".join(f"| {s} | {severity_counts.get(s, 0)} |" for s in order)
    return (
        "## Summary\n\n"
        "| Metric | Count |\n"
        "|---|---|\n"
        f"| Findings before | {state.findings_before} |\n"
        f"| Findings fixed | {len(state.fixed)} |\n"
        f"| Remaining — manual | {len(state.manual_remaining)} |\n"
        f"| Remaining — unscannable | {len(state.unscannable_remaining)} |\n\n"
        "| Severity (remaining) | Count |\n"
        "|---|---|\n"
        f"{severity_rows}"
    )


def _fixed_findings_table(fixed: list[MergedFinding]) -> str:
    """Section 2 — findings this PR fixed (tool, rule, file, severity, description)."""
    header = (
        "## Fixed Findings\n\n"
        "| Tool | Rule | File | Severity | Description |\n"
        "|---|---|---|---|---|"
    )
    if not fixed:
        return f"{header}\n| (none) | — | — | — | — |"
    rows = "\n".join(_finding_row(m) for m in fixed)
    return f"{header}\n{rows}"


def _remaining_manual_table(state: PipelineState) -> str:
    """Section 3 — the always-present remainder table (req 42's "no false
    all-clear" requirement). Combines `manual_remaining` and
    `unscannable_remaining` under one table with a `Bucket` column so a
    reviewer sees both groups side by side; renders its header and column
    structure unconditionally, even when both lists are empty."""
    header = (
        "## Remaining Findings (Manual Review Required)\n\n"
        "These findings were **not** fixed by this PR and still require "
        "human review:\n\n"
        "| Bucket | Tool | Rule | File | Severity | Description |\n"
        "|---|---|---|---|---|---|"
    )
    rows: list[str] = [_finding_row_with_bucket(m, "manual") for m in state.manual_remaining]
    rows += [_finding_row_with_bucket(m, "unscannable") for m in state.unscannable_remaining]
    if not rows:
        return f"{header}\n| (none) | — | — | — | — | — |"
    return f"{header}\n" + "\n".join(rows)


def _dependency_update_boundary_section(findings: list[MergedFinding]) -> str:
    """Requirement 24 (D24) callout — findings owned by the sibling agent."""
    rows = "\n".join(_finding_row(m) for m in findings)
    return (
        "## Owned by `dependency-update` (D24 boundary)\n\n"
        "These findings were reclassified `manual` because they are "
        "lockfile-managed version bumps — the sibling `dependency-update` "
        "agent owns fixing them, not this agent (PRD requirement 24):\n\n"
        "| Tool | Rule | File | Severity | Description |\n"
        "|---|---|---|---|---|\n"
        f"{rows}"
    )


def _major_version_guard_section(findings: list[MergedFinding]) -> str:
    """Requirement 27 callout — findings that need a manual major-version bump."""
    rows = "\n".join(_major_bump_row(m) for m in findings)
    return (
        "## \u26a0\ufe0f Major Version Required\n\n"
        "These findings require a major-version bump and are left for "
        "manual migration rather than fixed automatically (PRD requirement "
        "27):\n\n"
        "| Tool | Rule | File | Severity | Current | Target |\n"
        "|---|---|---|---|---|---|\n"
        f"{rows}"
    )


def _ai_modification_warning(llm_fixed: list[MergedFinding]) -> str:
    """Requirement 42's AI-modification warning — mirrors the sibling
    agent's requirement 57 in spirit, naming exactly which findings the
    LLM escape hatch touched."""
    names = "\n".join(
        f"- `{_md_cell(m.finding.rule_id)}` in `{_md_cell(m.finding.file_path)}`" for m in llm_fixed
    )
    if not names:
        names = "_(no findings recorded)_"
    return (
        "## \U0001f916 AI-Assisted Modifications\n\n"
        "An AI fix agent modified source code to resolve the following "
        "finding(s) after the deterministic fix path did not fully "
        "resolve them. Review these changes carefully before merging:\n\n"
        f"{names}"
    )


def _rescan_confirmation_line(state: PipelineState) -> str:
    """Requirement 42's re-scan confirmation line — always present, always
    last. `build_pr_body()` is only ever called after the re-scan gate has
    already passed (D23 — see this module's `PipelineState` docstring), so
    this line always reports a clean gate."""
    return (
        f"**Re-scan confirmation:** {state.rescan_before_count} finding(s) "
        f"before the fix, {state.rescan_after_count} finding(s) after — "
        "every targeted finding was cleared and no unexplained new finding "
        "appeared (PRD requirement 34's gate passed)."
    )


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _finding_row(m: MergedFinding) -> str:
    """One row: Tool | Rule | File | Severity | Description."""
    f = m.finding
    location = f"{f.file_path}:{f.line_start}"
    return (
        f"| {_md_cell(f.tool)} | {_md_cell(f.rule_id)} | {_md_cell(location)} | "
        f"{_md_cell(f.severity.value)} | {_md_cell(f.message)} |"
    )


def _finding_row_with_bucket(m: MergedFinding, bucket: str) -> str:
    """One row: Bucket | Tool | Rule | File | Severity | Description."""
    f = m.finding
    location = f"{f.file_path}:{f.line_start}"
    return (
        f"| {_md_cell(bucket)} | {_md_cell(f.tool)} | {_md_cell(f.rule_id)} | "
        f"{_md_cell(location)} | {_md_cell(f.severity.value)} | {_md_cell(f.message)} |"
    )


def _major_bump_row(m: MergedFinding) -> str:
    """One row: Tool | Rule | File | Severity | Current | Target."""
    f = m.finding
    remediation = f.remediation
    current = (remediation.current_version if remediation else None) or "(unknown)"
    target = (remediation.target_version if remediation else None) or "(unknown)"
    location = f"{f.file_path}:{f.line_start}"
    return (
        f"| {_md_cell(f.tool)} | {_md_cell(f.rule_id)} | {_md_cell(location)} | "
        f"{_md_cell(f.severity.value)} | {_md_cell(current)} | {_md_cell(target)} |"
    )


def _md_cell(value: str) -> str:
    """Escape a value for safe inclusion in a single markdown table cell."""
    return str(value).replace("|", "\\|").replace("\n", " ").strip()
