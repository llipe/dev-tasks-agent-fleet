"""
The disposition: what a claimed run leaves on the issue when it ends without
a PR (spec §8.8; FR-22, FR-23; D-08, D-81, D-85, D-93).

The disposition is:

1. one **diagnosis comment** whose first line is this run's ``disposition``
   marker, followed by a fixed line, why the run stopped, what was tried, and
   the diffstat when a change cap was hit;
2. a 😕 (``confused``) reaction on the ``/bug-fix`` comment, when
   ``trigger_comment_id`` is known (a reaction 4xx is logged, not fatal);
3. the board's ``Ready`` status through ``board_ready``, best effort (D-103).

It changes **no labels and no assignee**, and never edits the issue, which
stays open for a later ``/bug-fix`` (D-93).

Safety rules:

- **Ownership gate (D-81).** Nothing is applied until the claim's post-check
  has called :meth:`Disposer.confirm_ownership`. Before that, ``dispose()`` and
  the backstop make no call at all.
- **Idempotent per run.** A trusted ``disposition`` marker for this ``run_id``
  on the issue (D-53) means it was already applied, so nothing is written. A
  forged marker (a human, another App) never suppresses it. In-process, a
  disposition that has finished or is in flight is never started again, so the
  ``finally`` path and the SIGTERM backstop can't both post.
- **Text.** Every variable part is CRLF-normalized, scrubbed of secrets,
  neutralized (D-65, D-85), and has ``<!--`` defused, so model text can't add a
  marker or hide content. A fixed line always follows the marker, so model
  text can never join the leading marker block.
- **Size.** The body fits GitHub's 65,536-character limit. The longest parts
  are shortened first (what was tried, then the diffstat, then the reason), so
  the marker and every section survive.
"""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from issues import MAX_COMMENT_CHARS, IssuesClient, cut_utf16, truncate_comment, utf16_len
from markers import build, canonical_run_id, has_trusted
from neutralize import ZWSP, neutralize
from scrubber import SecretsLike, scrub_all, scrub_exception

log = logging.getLogger("bug_fix.disposition")

CUT_NOTE = " … (truncated)"
RETRY_LINE = (
    "No labels or assignees were changed, and the issue stays open. "
    "Comment `/bug-fix` to try again."
)
_RUN_LINK = re.compile(r"https://\S+")
_LOCK_TIMEOUT = 1.0


@dataclass(frozen=True)
class Diagnosis:
    """Why the run stopped, what it tried, and the diffstat when a cap was hit."""

    why: str
    tried: str
    diffstat: str | None = None


BACKSTOP_DIAGNOSIS = Diagnosis(
    why="the run was stopped by a termination signal (SIGTERM) before it finished",
    tried="The run had claimed this issue and was still working on it.",
)


@dataclass(frozen=True)
class DispositionResult:
    # "applied" | "already_disposed" | "in_progress" | "not_owned"
    status: str
    comment_id: int | None = None
    reaction: str | None = None  # "added" | "skipped" | "failed"
    board: str | None = None  # "ok" | "skipped" | "failed"


def _clean(text: str | None, secrets: SecretsLike) -> str:
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = neutralize(scrub_all(text, secrets))
    return text.replace("<!--", "<!" + ZWSP + "--").strip("\n")


def _fence(text: str) -> str:
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)


def _render(run_ref: str, rid: str, why: str, tried: str, diffstat: str) -> str:
    lines = [
        build("disposition", rid),
        f"😕 Bug-fix run {run_ref} stopped without opening a pull request.",
        "",
        f"**Why it stopped:** {why or 'unknown'}",
        "",
        "**What was tried:**",
        "",
        tried or "(no summary)",
    ]
    if diffstat:
        fence = _fence(diffstat)
        lines += ["", "**Diffstat** (a change cap was exceeded):", "", fence, diffstat, fence]
    lines += ["", RETRY_LINE]
    return "\n".join(lines)


def _shorten(value: str, excess: int) -> str:
    keep = max(0, utf16_len(value) - excess - utf16_len(CUT_NOTE))
    # Never leave a bare "@" whose U+200B was cut off.
    return cut_utf16(value, keep).rstrip("@") + CUT_NOTE


def build_body(
    run_id: str, diagnosis: Diagnosis, secrets: SecretsLike, run_link: str | None = None
) -> str:
    """The diagnosis comment for ``run_id``, ready to post."""
    rid = canonical_run_id(run_id)
    run_ref = run_link if run_link and _RUN_LINK.fullmatch(run_link) else f"`{rid}`"
    parts = {
        "why": _clean(diagnosis.why, secrets),
        "tried": _clean(diagnosis.tried, secrets),
        "diffstat": _clean(diagnosis.diffstat, secrets),
    }
    body = _render(run_ref, rid, **parts)
    for key in ("tried", "diffstat", "why"):
        excess = utf16_len(body) - MAX_COMMENT_CHARS
        if excess <= 0:
            break
        if parts[key]:
            parts[key] = _shorten(parts[key], excess)
            body = _render(run_ref, rid, **parts)
    return truncate_comment(body)


class Disposer:
    """Applies this run's disposition at most once, after confirmed ownership."""

    def __init__(
        self,
        *,
        client: IssuesClient,
        issue_number: int,
        run_id: str,
        app_id: int,
        trigger_comment_id: int | None,
        secrets: SecretsLike,
        run: Any | None = None,
        run_link: str | None = None,
        board_ready: Callable[[], object] | None = None,
    ) -> None:
        self.client = client
        self.issue_number = issue_number
        self.run_id = canonical_run_id(run_id)
        self.app_id = app_id
        self.trigger_comment_id = trigger_comment_id
        self.secrets = secrets
        self.run = run
        self.run_link = run_link
        self.board_ready = board_ready
        self._owned = threading.Event()
        self._lock = threading.Lock()
        self._busy = False
        self._done = False

    # -- ownership ---------------------------------------------------------------

    @property
    def ownership_confirmed(self) -> bool:
        return self._owned.is_set()

    def confirm_ownership(self) -> None:
        """Called by the claim once the race post-check confirms this run owns it."""
        self._owned.set()

    def backstop_action(self) -> Callable[[], DispositionResult] | None:
        """The SIGTERM backstop's disposition, or ``None`` before confirmed ownership."""
        if not self.ownership_confirmed:
            return None
        return lambda: self.dispose(BACKSTOP_DIAGNOSIS)

    # -- in-process single flight -----------------------------------------------

    def _begin(self) -> bool:
        if not self._lock.acquire(timeout=_LOCK_TIMEOUT):
            return False
        try:
            if self._busy:
                return False
            self._busy = True
            return True
        finally:
            self._lock.release()

    def _end(self) -> None:
        with self._lock:
            self._busy = False

    # -- reporting ---------------------------------------------------------------

    def _event(self, level: str, message: str) -> None:
        message = scrub_all(message, self.secrets)
        getattr(log, "warning" if level == "warn" else level)("%s", message)
        if self.run is None:
            return
        try:
            getattr(self.run, level)(message)
        except Exception:  # noqa: BLE001 — a reporting failure never breaks the disposition
            return

    # -- the disposition ---------------------------------------------------------

    def dispose(self, diagnosis: Diagnosis) -> DispositionResult:
        """Apply the disposition once. GitHub errors on the read or the comment raise."""
        if not self.ownership_confirmed:
            return DispositionResult("not_owned")
        if self._done:
            return DispositionResult("already_disposed")
        if not self._begin():
            return DispositionResult("in_progress")
        try:
            comments = self.client.list_comments(self.issue_number)
            if has_trusted(comments, self.app_id, "disposition", self.run_id):
                self._done = True
                self._event("info", "disposition already applied for this run; nothing written")
                return DispositionResult("already_disposed")
            body = build_body(self.run_id, diagnosis, self.secrets, self.run_link)
            created = self.client.post_comment(self.issue_number, body)
            self._done = True
            reaction = self._react()
            board = self._board()
            self._event("info", f"disposition applied (reaction {reaction}, board {board})")
            cid = created.get("id")
            return DispositionResult(
                "applied",
                comment_id=cid if isinstance(cid, int) else None,
                reaction=reaction,
                board=board,
            )
        finally:
            self._end()

    def _react(self) -> str:
        try:
            result = self.client.add_reaction(self.trigger_comment_id, "confused")
        except Exception as exc:  # noqa: BLE001 — a reaction is cosmetic (DF-38)
            self._event("warn", f"confused reaction failed: {scrub_exception(exc, self.secrets)}")
            return "failed"
        if result.status == "failed":
            self._event("warn", f"confused reaction failed with HTTP {result.http_status}")
        return result.status

    def _board(self) -> str:
        if self.board_ready is None:
            return "skipped"
        try:
            self.board_ready()
        except Exception as exc:  # noqa: BLE001 — the board is best effort (D-99)
            self._event("warn", f"board update failed: {scrub_exception(exc, self.secrets)}")
            return "failed"
        return "ok"
