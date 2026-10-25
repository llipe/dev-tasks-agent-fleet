"""
The ``checkout`` step: clone, repo gate, install, base gates, base restore
(spec §8.7; S-189; FR-5, FR-6; D-06, D-14, D-19, D-62, D-63, D-83, D-92,
D-110, D-112).

The link-protection sysctls (QA-189-01) are recorded first, at the start of
this step and before the clone (spec v2.6 §8.7), by
:func:`record_link_protection`.

Runs after the refusal checks pass and **before** the claim, so a repository
the agent can't work in gets only a refusal reply (FR-5(e), AC-4). No issue is
changed before the repo gate passes; the refusal reply is the only GitHub
write this step can make.

1. **Clone** (D-62). ``safe_git.clone`` shallow-clones ``base_branch`` of
   ``https://github.com/<owner>/<repo>.git`` into the wrapper clone
   ``/work/wrapper/repo`` (root-owned ``/work/wrapper``, mode 0700, D-110),
   records the base SHA and writes the narrow ``info/exclude`` (D-83).
2. **Materialize.** The base tree goes into the empty ``/work/repo`` as plain
   files, through ``tar -x`` spawned as ``fixer``. ``/work/repo`` has no
   ``.git``; ``fixer`` may create one, and the wrapper never reads it.
3. **Repo gate** (FR-6, D-06, D-19, D-112). ``toolchain.check_repo_gate``
   reads the base commit in the wrapper clone (trusted data, not the work
   tree): ``.claude/agents/developer.md`` plus the four gates, and for Python
   a ``make install`` target. A miss ends with refusal ``repo_gate``: the
   marked reply names the first item, ``result.summary`` names every one,
   ``succeeded``/``not_applicable``, no claim, no reaction, no board.
4. **Install** in the script sandbox as ``fixer``: ``pnpm install
   --frozen-lockfile``, ``npm ci`` or ``make install``. A lockfile mismatch
   fails and never rewrites the lockfile (D-63).
5. **Base gates** (D-14): the four gates and ``audit`` on the base tree,
   recorded as ``run_events`` and kept for the PR body. They never block.
6. **Restore the base** (D-63). Install and the base runs may edit the tree
   (an autofix ``lint``, codegen). The wrapper captures ``/work/repo``, and
   every path that differs from base is put back as ``fixer``: ``rm -rf``,
   then the base version (if any) through ``tar -x``. Ignored paths
   (``node_modules/`` and the rest of ``info/exclude``, and the repo's own
   ``.gitignore``) are left as they are. The capture repeats until the tree
   equals the base tree (a ``.gitignore`` the runs edited can hide a file
   until it is restored), up to :data:`RESTORE_ROUNDS`. A ``run_event``
   records "base runs modified N tracked files; restored", so the CLI starts
   from an exact base tree and the captured change holds only its edits.

Outcomes (:class:`CheckoutResult`):

============  ============================================================
``proceed``   the run continues to the claim
``refused``   refusal ``repo_gate``: ``succeeded``/``not_applicable``
``failed``    ``CLONE_FAILED`` (clone, materialize, capture or restore;
              wrapper-side, including an unsafe work tree, QA-189-01/-02,
              and a tree over the tar caps, gap 5) or ``INSTALL_FAILED`` (the install command,
              including an unavailable sandbox); both count toward the
              breaker (spec §8.9)
============  ============================================================

Every message is scrubbed of the installation token and every other known
secret before it is logged, reported or returned.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field, replace
from typing import Any

from gates import GATE_TIMEOUT_SECONDS, GateReport, SandboxLike, run_gates
from issues import IssuesClient
from refusal import CheckOutcome, Refusal, post_refusal
from safe_git import EXCLUDE_LINES, GitError, GitTools, SafeGit, clone, link_protection
from sandbox import Mode, SandboxError
from scrubber import SecretsLike, scrub_all, tail
from toolchain import RepoGate, Toolchain, check_repo_gate

log = logging.getLogger("bug_fix.checkout")

CLONE_FAILED = "CLONE_FAILED"
INSTALL_FAILED = "INSTALL_FAILED"
INSTALL_TIMEOUT_SECONDS = 900.0
RESTORE_ROUNDS = 3

__all__ = [
    "CLONE_FAILED",
    "EXCLUDE_LINES",
    "INSTALL_FAILED",
    "CheckoutResult",
    "WorkPaths",
    "github_url",
    "record_link_protection",
    "run_checkout",
]

# GitHub owner and repository names (the reply grammar in refusal.py, plus
# the leading-character rules GitHub applies).
_OWNER = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})")
_REPO = re.compile(r"[A-Za-z0-9._-]{1,100}")


@dataclass(frozen=True)
class WorkPaths:
    """The image's work directories (spec §7)."""

    wrapper_dir: str = "/work/wrapper"
    repo_dir: str = "/work/repo"

    @property
    def clone_dir(self) -> str:
        return os.path.join(self.wrapper_dir, "repo")


def github_url(owner: str, repo: str) -> str:
    """The token-free clone URL, ``https://github.com/<owner>/<repo>.git``."""
    if not isinstance(owner, str) or not _OWNER.fullmatch(owner):
        raise ValueError("invalid repository owner")
    if not isinstance(repo, str) or not _REPO.fullmatch(repo) or repo in (".", ".."):
        raise ValueError("invalid repository name")
    return f"https://github.com/{owner}/{repo}.git"


@dataclass(frozen=True)
class CheckoutResult:
    status: str  # proceed, refused or failed
    summary: str
    error_code: str | None = None
    refusal: CheckOutcome | None = None
    base_sha: str | None = None
    toolchain: Toolchain | None = None
    repo_gate: RepoGate | None = None
    base_gates: GateReport | None = None
    restored: int = 0
    git: SafeGit | None = field(default=None, repr=False)

    @property
    def proceed(self) -> bool:
        return self.status == "proceed"

    def report(self, run: Any) -> None:
        """End the run for a refusal or a failure; ``proceed`` reports nothing."""
        if self.status == "refused" and self.refusal is not None:
            self.refusal.report(run)
        elif self.status == "failed":
            run.fail(self.error_code or CLONE_FAILED, self.summary)


def _event(run: Any, level: str, message: str, secrets: SecretsLike, **data: Any) -> None:
    message = scrub_all(message, secrets)
    getattr(log, "warning" if level == "warn" else level)("%s", message)
    if run is None:
        return
    try:
        getattr(run, level)(message, **data)
    except Exception:  # noqa: BLE001 — a reporting fault never changes the outcome
        return


def _failed(
    code: str,
    message: str,
    secrets: SecretsLike,
    run: Any,
    known: CheckoutResult | None = None,
) -> CheckoutResult:
    """A ``failed`` result carrying whatever ``known`` already holds."""
    summary = scrub_all(f"{code}: {message}", secrets)
    _event(run, "error", summary, secrets)
    known = known or CheckoutResult(status="failed", summary=summary)
    return replace(known, status="failed", summary=summary, error_code=code)


def _restore_paths(git: SafeGit, work_tree: str, changed: list[Any]) -> None:
    """Put every changed path back to base, as ``fixer``: remove what is
    there, then write the base version of the paths base has."""
    git.remove([c.path for c in changed], work_tree)
    in_base = [c.path for c in changed if c.in_base]
    if in_base:
        git.materialize(git.base_sha, work_tree, paths=in_base, fresh=False)


def record_link_protection(
    run: Any, secrets: SecretsLike, base: str | None = None
) -> dict[str, str]:
    """Record ``fs.protected_hardlinks`` and ``fs.protected_symlinks`` (QA-189-01).

    :func:`run_checkout` calls it first, before the clone (spec v2.6 §8.7,
    "at the start of ``checkout``"). Evidence only: ``check_work_tree``
    refuses hardlinks whatever the sysctls say, and local Docker may differ
    from AgentCore (the live value is probe #446's). A value other than ``1``
    is a ``warn`` event, never a failure.
    """
    lp = link_protection(base)
    _event(
        run,
        "info" if all(v == "1" for v in lp.values()) else "warn",
        "link protection: fs.protected_hardlinks={protected_hardlinks} "
        "fs.protected_symlinks={protected_symlinks}".format(**lp),
        secrets,
        **lp,
    )
    return lp


def restore_base(git: SafeGit, work_tree: str, *, rounds: int = RESTORE_ROUNDS) -> int:
    """Undo every edit install and the base runs made to the tree (D-63).

    Returns the number of paths that differed from base on the first capture.
    Raises :class:`GitError` when the tree is still not the base tree after
    ``rounds`` restores.
    """
    base_tree = git.tree_of(git.base_sha)
    first: int | None = None
    for _ in range(rounds):
        changed = git.changes(base_tree, git.capture(work_tree))
        if first is None:
            first = len(changed)
        if not changed:
            return first
        _restore_paths(git, work_tree, changed)
    if git.changes(base_tree, git.capture(work_tree)):
        raise GitError(f"base restore did not converge after {rounds} rounds")
    return first or 0


def run_checkout(
    *,
    run_id: str,
    owner: str,
    repo: str,
    base_branch: str,
    issue_number: int,
    sandbox: SandboxLike,
    issues: IssuesClient,
    secrets: SecretsLike,
    token: str | None = None,
    run: Any = None,
    run_link: str | None = None,
    panel_origin: str | None = None,
    paths: WorkPaths | None = None,
    tools: GitTools | None = None,
    remote_url: str | None = None,
    app_id: int | None = None,
    install_timeout: float = INSTALL_TIMEOUT_SECONDS,
    gate_timeout: float = GATE_TIMEOUT_SECONDS,
    sysctl_base: str | None = None,
) -> CheckoutResult:
    """Run the ``checkout`` step. ``remote_url`` overrides the GitHub URL
    (tests clone a local bare remote). ``app_id`` is unused here and kept for
    the S-190 call site's symmetry with the claim step. ``sysctl_base``
    overrides ``/proc/sys/fs`` for the link-protection event (tests)."""
    del app_id
    paths = paths or WorkPaths()
    scrub = [*(secrets.values() if hasattr(secrets, "values") else secrets)]
    if token:
        scrub.append(token)

    # 0. The link-protection sysctls, as evidence (spec v2.6 §8.7, QA-189-01).
    record_link_protection(run, scrub, sysctl_base)

    # 1. Clone into the wrapper clone (D-62).
    try:
        url = remote_url if remote_url is not None else github_url(owner, repo)
        git = clone(url, base_branch, paths.clone_dir, tools=tools, token=token, secrets=scrub)
    except (GitError, ValueError) as exc:
        return _failed(CLONE_FAILED, str(exc), scrub, run)
    _event(run, "info", f"cloned {base_branch} at {git.base_sha}", scrub, base_sha=git.base_sha)
    cloned = CheckoutResult(status="proceed", summary="", base_sha=git.base_sha, git=git)

    # 2. Materialize the base tree into the empty /work/repo, as fixer.
    try:
        written = git.materialize(git.base_sha, paths.repo_dir, fresh=True)
    except GitError as exc:
        return _failed(CLONE_FAILED, str(exc), scrub, run, cloned)
    _event(run, "info", f"materialized {written} entries into the work tree as fixer", scrub)

    # 3. The repo gate, on the base commit (FR-6). A miss is a refusal (D-92).
    try:
        gate = check_repo_gate(git.reader(git.base_sha))
    except GitError as exc:
        return _failed(CLONE_FAILED, str(exc), scrub, run, cloned)
    if not gate.ok:
        first = gate.first
        assert first is not None
        _event(run, "info", gate.summary, scrub, missing=[m.describe() for m in gate.missing])
        outcome = post_refusal(
            issues,
            run_id,
            Refusal("repo_gate", detail=first.item),
            issue_number,
            run=run,
            run_link=run_link,
            panel_origin=panel_origin,
            secrets=scrub,
            summary=gate.summary,
        )
        return CheckoutResult(
            status="refused",
            summary=outcome.summary,
            refusal=outcome,
            base_sha=git.base_sha,
            repo_gate=gate,
            git=git,
        )
    toolchain = gate.toolchain
    assert toolchain is not None
    _event(run, "info", gate.summary, scrub, stack=str(toolchain.stack), manager=toolchain.manager)
    known = replace(cloned, toolchain=toolchain, repo_gate=gate)

    # 4. Install, frozen, in the script sandbox as fixer (D-63, D-112).
    argv = toolchain.install_argv
    command = " ".join(argv)
    try:
        res = sandbox.run(argv, cwd=paths.repo_dir, timeout=install_timeout, mode=Mode.SCRIPT)
    except SandboxError as exc:
        return _failed(INSTALL_FAILED, f"{command}: {exc}", scrub, run, known)
    if not res.ok:
        output = "\n".join(x for x in (res.stdout, res.stderr) if x)
        detail = tail(output, scrub, 1000).strip()
        reason = "timeout" if res.timed_out else f"{res.outcome}, exit {res.exit_code}"
        message = f"{command} ({reason})" + (f": {detail}" if detail else "")
        return _failed(INSTALL_FAILED, message, scrub, run, known)
    _event(run, "info", f"installed with {command}", scrub)

    # 5. Base gates: evidence only, never blocking (D-14).
    report = run_gates(
        sandbox,
        toolchain,
        paths.repo_dir,
        secrets=scrub,
        phase="base",
        run=run,
        timeout=gate_timeout,
    )

    # 6. Restore the base tree (D-63).
    try:
        restored = restore_base(git, paths.repo_dir)
    except GitError as exc:
        return _failed(
            CLONE_FAILED, f"restore: {exc}", scrub, run, replace(known, base_gates=report)
        )
    if restored:
        _event(
            run,
            "warn",
            f"base runs modified {restored} tracked files; restored",
            scrub,
            restored=restored,
        )
    return replace(
        known,
        status="proceed",
        summary=f"checkout ready at {git.base_sha}",
        base_gates=report,
        restored=restored,
    )
