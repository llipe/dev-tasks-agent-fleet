"""
The claim and the post-claim race check
(spec §8.6; S-188; D-54, D-81, D-93, D-94, D-103; DF-33).

The step runs after the refusal checks pass:

1. **Claim.** Post the claim comment: line 1 is this run's ``claim`` marker,
   line 2 the fixed :data:`CLAIM_LINE` with the run link. Then add 👀 to the
   ``/bug-fix`` comment when ``trigger_comment_id`` is present (a manual
   invoke has none, so no reaction is made, AC-19). A reaction fault is
   logged as a ``run_event`` and is never fatal (DF-38). No label or assignee
   is touched (D-93, FR-8): this module has no call for either.
2. **Post-check** (D-54). List the issue's comments and look for an open
   claim, by the single rule of :func:`markers.open_claims` (DF-33: a trusted
   claim with no trusted ``pr``, ``disposition`` or ``refusal`` marker for its
   run), with a **lower comment id** than this run's claim, whose run is not
   terminal in ``v_runs.effective_status``. The integer comment id decides,
   so two claims in the same second still have one winner. A missing
   ``v_runs`` row counts as finished and is reported as a ``run_event``
   (CT-34); an unknown status fails closed.
3. **Lost race.** Delete **only** this run's own claim comment and end
   ``succeeded``/``not_applicable`` with ``result.reason = "active_run"``,
   naming the winner. No board call, no disposition. The 👀 stays, as spec
   §8.6 is written (pinned, DF-32). A 404 on the ``DELETE`` means the comment
   is already gone and is logged; any other ``DELETE`` fault ends ``failed``
   with its D-67 code, still with no disposition (DF-38 leaves this open).
4. **Ownership gate** (D-81). Only a won race calls
   :meth:`disposition.Disposer.confirm_ownership`, then the board's
   ``In progress`` update (``board_in_progress``, best effort, D-103). A
   post-check fault (``SUPABASE_UNAVAILABLE``, or a GitHub fault on the
   listing) keeps the claim comment, confirms nothing and ends ``failed``, so
   neither the ``finally`` path nor the SIGTERM backstop can dispose.

Outcomes (:class:`ClaimOutcome`):

=========  ==============================================================
``owned``  the race is won; ownership confirmed; the run continues
``lost``   another active run claimed first; own comment withdrawn;
           ``succeeded``/``not_applicable``, reason ``active_run``
``failed`` a fault on the claim post or the post-check; ``error_code`` is
           ``GITHUB_UNAVAILABLE``, ``GITHUB_REQUEST_REJECTED`` or
           ``SUPABASE_UNAVAILABLE`` (D-67)
=========  ==============================================================

Every message is scrubbed of secrets before it is logged or reported.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from github_client import GitHubError
from issues import IssuesClient
from markers import build, canonical_run_id, comment_id
from refusal import SupabaseUnavailable, active_claim_runs
from run_link import run_ref
from scrubber import SecretsLike, scrub_all, scrub_exception

log = logging.getLogger("bug_fix.claim")

CLAIM_LINE = "🔧 Bug-fix run {run} is working on this issue."


def build_claim_body(
    run_id: str, run_link: object = None, *, panel_origin: str | None = None
) -> str:
    """The claim comment: the ``claim`` marker, then one fixed line (spec §8.3).

    ``run_link`` must pass the shared strict validator
    (:func:`run_link.is_valid_run_link`: a ``RunLink`` from the configured panel
    origin, for this run, on the host of ``panel_origin``, the configured
    ``PANEL_BASE_URL``); anything else falls back to the run id in backticks,
    as the refusal reply and the diagnosis do.
    """
    rid = canonical_run_id(run_id)
    ref = run_ref(run_link, rid, panel_origin)
    return f"{build('claim', rid)}\n{CLAIM_LINE.format(run=ref)}"


def race_winner(
    comments: Iterable[Any],
    app_id: int,
    own_run_id: str,
    own_comment_id: int,
    read_statuses: Callable[[Sequence[str]], Mapping[str, str]],
    *,
    warn: Callable[[str], None] | None = None,
) -> str | None:
    """The run that beat this one, or ``None`` when this run won (D-54).

    The winner is the earliest open claim (DF-33) with a comment id lower than
    ``own_comment_id`` whose run is ``queued`` or ``running``. Raises
    :class:`refusal.SupabaseUnavailable` on a read failure or an unknown
    status, and ``ValueError`` on an invalid ``own_comment_id``.
    """
    if (
        not isinstance(own_comment_id, int)
        or isinstance(own_comment_id, bool)
        or own_comment_id < 1
    ):
        raise ValueError("own_comment_id must be a positive integer")
    active = active_claim_runs(
        comments, app_id, own_run_id, read_statuses, before=own_comment_id, warn=warn
    )
    return active[0] if active else None


@dataclass(frozen=True)
class ClaimOutcome:
    """The result of a claim step.

    ``status`` is ``posted`` (after :meth:`Claimer.post` only), ``owned``,
    ``lost`` or ``failed``. ``reaction`` is ``added``, ``skipped`` or
    ``failed``; ``withdrawal`` is ``none``, ``deleted`` or ``already_gone``;
    ``board`` is ``ok``, ``skipped`` or ``failed``.
    """

    status: str
    summary: str
    comment_id: int | None = None
    reaction: str = "skipped"
    winner: str | None = None
    withdrawal: str = "none"
    board: str = "skipped"
    error_code: str | None = None

    @property
    def owned(self) -> bool:
        return self.status == "owned"

    def result(self) -> dict[str, Any]:
        """``runs.result`` for a lost race: ``{reason, summary}``; empty otherwise.

        Never carries a ``board`` key: a lost race touches no board.
        """
        if self.status == "lost":
            return {"reason": "active_run", "summary": self.summary}
        return {}

    def report(self, run: Any) -> None:
        """End the run for a lost race or a fault; ``owned`` reports nothing."""
        if self.status == "lost":
            run.succeed("not_applicable", result=self.result())
        elif self.status == "failed":
            run.fail(self.error_code or "UNHANDLED_ERROR", self.summary)


class Claimer:
    """Claims one issue for one run, then runs the post-claim race check.

    :meth:`claim` does both. :meth:`post` and :meth:`post_check` are the two
    halves, kept separate so a test can interleave two runs (AC-20).
    """

    def __init__(
        self,
        *,
        client: IssuesClient,
        issue_number: int,
        run_id: str,
        app_id: int,
        trigger_comment_id: int | None,
        run_status: Callable[[Sequence[str]], Mapping[str, str]],
        run: Any = None,
        run_link: str | None = None,
        panel_origin: str | None = None,
        secrets: SecretsLike | None = None,
        disposer: Any = None,
        board_in_progress: Callable[[], object] | None = None,
    ) -> None:
        self.client = client
        self.issue_number = issue_number
        self.run_id = canonical_run_id(run_id)
        self.app_id = app_id
        self.trigger_comment_id = trigger_comment_id
        self.run_status = run_status
        self.run = run
        self.run_link = run_link
        self.panel_origin = panel_origin
        self.secrets: SecretsLike = [] if secrets is None else secrets
        self.disposer = disposer
        self.board_in_progress = board_in_progress
        self._posted: ClaimOutcome | None = None

    # -- reporting ---------------------------------------------------------------

    def _event(self, level: str, message: str) -> None:
        message = scrub_all(message, self.secrets)
        getattr(log, "warning" if level == "warn" else level)("%s", message)
        if self.run is None:
            return
        try:
            getattr(self.run, level)(message)
        except Exception:  # noqa: BLE001 — a reporting failure never changes the outcome
            return

    def _failed(
        self, code: str, what: str, exc: BaseException | None, base: ClaimOutcome | None = None
    ) -> ClaimOutcome:
        detail = f": {scrub_exception(exc, self.secrets)}" if exc is not None else ""
        summary = scrub_all(f"{code}: {what}{detail}", self.secrets)
        self._event("error", summary)
        if base is None:
            return ClaimOutcome(status="failed", summary=summary, error_code=code)
        return replace(base, status="failed", summary=summary, error_code=code)

    # -- 1. the claim ------------------------------------------------------------

    def post(self) -> ClaimOutcome:
        """Post the claim comment, then 👀. ``posted``, or ``failed`` on a fault."""
        if self._posted is not None:
            raise RuntimeError("the claim was already posted")
        body = build_claim_body(self.run_id, self.run_link, panel_origin=self.panel_origin)
        try:
            created = self.client.post_comment(self.issue_number, body)
        except GitHubError as exc:
            self._posted = self._failed(exc.code, "the claim comment was not posted", exc)
            return self._posted
        cid = comment_id(created)
        if cid is None:
            # Without its id the run can't order its claim or withdraw it.
            self._posted = self._failed(
                "GITHUB_REQUEST_REJECTED", "the claim comment came back with no id", None
            )
            return self._posted
        reaction = self._react()
        self._event("info", f"claim comment {cid} posted on #{self.issue_number}")
        self._posted = ClaimOutcome(
            status="posted",
            summary=f"claim posted on #{self.issue_number}",
            comment_id=cid,
            reaction=reaction,
        )
        return self._posted

    def _react(self) -> str:
        try:
            result = self.client.add_reaction(self.trigger_comment_id, "eyes")
        except Exception as exc:  # noqa: BLE001 — a reaction is cosmetic (DF-38)
            self._event("warn", f"eyes reaction failed: {scrub_exception(exc, self.secrets)}")
            return "failed"
        if result.status == "failed":
            self._event("warn", f"eyes reaction failed with HTTP {result.http_status}")
        return result.status

    # -- 2. the post-check -------------------------------------------------------

    def post_check(self) -> ClaimOutcome:
        """Run the race check (D-54) and the ownership gate (D-81)."""
        posted = self._posted
        if posted is None or posted.status != "posted":
            raise RuntimeError("post_check needs a posted claim")
        assert posted.comment_id is not None  # set on every "posted" outcome
        own_cid = posted.comment_id
        try:
            comments = self.client.list_comments(self.issue_number)
            winner = race_winner(
                comments,
                self.app_id,
                self.run_id,
                own_cid,
                self.run_status,
                warn=lambda message: self._event("warn", message),
            )
        except GitHubError as exc:
            return self._failed(
                exc.code, "the post-claim check could not list comments", exc, posted
            )
        except SupabaseUnavailable as exc:
            return self._failed(exc.code, "the post-claim check could not read v_runs", exc, posted)
        if winner is not None:
            return self._withdraw(posted, winner)
        return self._own(posted)

    def _withdraw(self, posted: ClaimOutcome, winner: str) -> ClaimOutcome:
        """Lost race: delete only this run's own comment (D-54)."""
        own_cid = posted.comment_id
        assert own_cid is not None
        lost = replace(posted, winner=winner)
        try:
            gone = self.client.delete_comment(own_cid)
        except GitHubError as exc:
            return self._failed(
                exc.code, f"run {winner} claimed first, and withdrawing the claim failed", exc, lost
            )
        withdrawal = "deleted" if gone else "already_gone"
        if not gone:
            self._event("warn", f"claim comment {own_cid} was already gone when this run withdrew")
        summary = (
            f"bug-fix run {winner} claimed #{self.issue_number} first; "
            "this run withdrew its claim (active_run)"
        )
        self._event("info", summary)
        return replace(lost, status="lost", summary=summary, withdrawal=withdrawal)

    def _own(self, posted: ClaimOutcome) -> ClaimOutcome:
        """Won race: confirm ownership, then the board's In progress (D-81, D-103)."""
        if self.disposer is not None:
            self.disposer.confirm_ownership()
        board = self._board()
        summary = f"claim confirmed on #{self.issue_number}"
        self._event("info", f"{summary} (board {board})")
        return replace(posted, status="owned", summary=summary, board=board)

    def _board(self) -> str:
        if self.board_in_progress is None:
            return "skipped"
        try:
            self.board_in_progress()
        except Exception as exc:  # noqa: BLE001 — the board is best effort (D-99)
            self._event(
                "warn", f"board update (In progress) failed: {scrub_exception(exc, self.secrets)}"
            )
            return "failed"
        return "ok"

    # -- both --------------------------------------------------------------------

    def claim(self) -> ClaimOutcome:
        """Claim, then run the post-check: ``owned``, ``lost`` or ``failed``."""
        posted = self.post()
        if posted.status != "posted":
            return posted
        return self.post_check()


def claim_issue(**kwargs: Any) -> ClaimOutcome:
    """One-call form of :class:`Claimer` (same keyword arguments)."""
    return Claimer(**kwargs).claim()
