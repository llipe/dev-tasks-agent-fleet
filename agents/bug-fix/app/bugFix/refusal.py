"""
Preflight and refusal checks, and the marked refusal reply
(spec §8.2; S-185; D-55, D-58, D-67, D-82, D-91, D-92, D-102, D-104).

**Preflight.**

1. Resolve the installation token. A credential failure ends
   ``failed``/``CREDENTIALS_UNAVAILABLE`` before any GitHub call.
2. The token must carry ``issues: write``; otherwise ``failed``/
   ``GITHUB_PERMISSION_MISSING`` with **zero** GitHub calls, since the App
   couldn't post the reply anyway (D-58).
3. ``params.py`` validates the params. An error is refusal ``invalid_params``.
   With a usable ``issue_number`` the reply names the key; without one there is
   no issue to reply on, so it makes **no** GitHub write (D-82, DF-34).

**Refusal checks** (D-92), in order, the first match wins, and a later check
never runs once one matches:

====================  =====================================================
``pull_request``      the issue payload has ``pull_request`` (D-88)
``closed``            ``state != "open"``
``linked_pr``         an open closing-reference PR, or an open PR whose head
                      starts with ``issue/<N>-`` (D-55)
``active_run``        a trusted claim marker with no trusted ``pr``,
                      ``disposition`` or ``refusal`` marker for its run,
                      whose run is ``queued`` or ``running`` in
                      ``v_runs.effective_status``
====================  =====================================================

``repo_gate`` is decided after the clone (S-189), which calls
:func:`build_reply` and :meth:`IssuesClient.post_comment` the same way. A
``GET /issues/{n}`` 404 (no such number, or a transferred issue) is refusal
``invalid_params`` with no write, as DF-34 recommends.

Labels never enter a check: :class:`issues.IssueFacts` carries none (D-90). The
commenter is never checked (D-91).

**Faults** are never read as "no match" (D-67): GitHub retries exhausted end
``failed``/``GITHUB_UNAVAILABLE``, an unexpected 4xx ``GITHUB_REQUEST_REJECTED``,
and a ``v_runs`` read failure ``SUPABASE_UNAVAILABLE``. None of them writes.

**Reply** (D-104). Exactly one comment: line 1 is the ``refusal`` marker, line 2
one fixed sentence per code, line 3 the run link. Its only variable parts are
the issue number, the linked PR (``#M``, or ``owner/name#M`` for a PR in
another repository, DF-185-07), a ``repo_gate`` item and an ``invalid_params``
key, each from a closed set or a strict grammar, so no issue, commenter or
model text can reach it. A
refusal adds **no** reaction, makes **no** claim and touches **no** board
(D-102). The run ends ``succeeded``/``not_applicable`` with
``result.reason = <code>``. A failure to post the reply is logged as a
``run_event`` and the outcome is unchanged.

A ``v_runs`` row that is missing for a claimed ``run_id`` counts as terminal,
reported as a ``run_event`` warning: a deleted run must not block the issue for
ever (DF-185-03, CT-34). An ``effective_status`` outside the known active and
terminal sets is ``SUPABASE_UNAVAILABLE``, also with a warning (QA 2).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import requests

from credentials import CredentialError, TokenContext, has_issues_write
from github_client import GitHubError
from issues import IssueFacts, IssuesClient, LinkedPr
from markers import build, canonical_run_id, open_claims, trusted_markers
from params import SCHEMA_KEYS, Params, ParamsError, parse_params
from scrubber import SecretsLike, scrub_all, scrub_exception

log = logging.getLogger("bug_fix.refusal")

NON_TERMINAL_STATUSES: frozenset[str] = frozenset({"queued", "running"})
TERMINAL_STATUSES: frozenset[str] = frozenset(
    {"succeeded", "failed", "timed_out", "failed_to_start", "canceled"}
)
SUPABASE_TIMEOUT = 10.0

REPLY_PREFIX = "Bug-fix didn't start: "
REPLY_TEXT: Mapping[str, str] = {
    "pull_request": "#{issue} is a pull request. Comment `/bug-fix` on an issue instead.",
    "closed": "#{issue} is closed. Reopen it, then comment `/bug-fix` again.",
    "linked_pr": (
        "pull request {pr} is already open for #{issue}. "
        "Close it or finish it before asking for another fix."
    ),
    "active_run": (
        "another bug-fix run is already working on #{issue}. "
        "Wait for it to finish, then comment `/bug-fix` again if it's still needed."
    ),
    "repo_gate": (
        "this repository is missing `{detail}`, which bug-fix needs before it can work here."
    ),
    "invalid_params": "the run parameter `{detail}` is missing or invalid.",
}
# The closed sets a reply's variable parts come from (RT-15 oracle (2)).
INVALID_PARAMS_KEYS: tuple[str, ...] = (*SCHEMA_KEYS, "params")
REPO_GATE_ITEMS: tuple[str, ...] = (
    ".claude/agents/developer.md",
    "package.json",
    "Makefile",
    "test",
    "lint",
    "format:check",
    "format-check",
    "typecheck",
)
_DETAIL_SETS: Mapping[str, tuple[str, ...]] = {
    "repo_gate": REPO_GATE_ITEMS,
    "invalid_params": INVALID_PARAMS_KEYS,
}
_RUN_LINK = re.compile(r"https://\S+")
# A GitHub ``owner/name`` (the reply's only other free-form part, DF-185-07).
_PR_REPO = re.compile(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+")


class SupabaseUnavailable(Exception):
    """A ``v_runs`` read failed. Names no key or response body."""

    code = "SUPABASE_UNAVAILABLE"


@dataclass(frozen=True)
class Refusal:
    """A refusal verdict: the code, plus ``#M`` or the item/key it names.

    ``pr_repo`` is ``owner/name`` for a ``linked_pr`` in another repository
    (DF-185-07), so the reply names it ``owner/name#M``, never a bare ``#M``
    that GitHub would link to this repository's PR of that number.
    """

    reason: str
    pr_number: int | None = None
    detail: str | None = None
    pr_repo: str | None = None


# ---------------------------------------------------------------------------
# The decision table
# ---------------------------------------------------------------------------


def decide(
    facts: IssueFacts,
    linked_pr: Callable[[], LinkedPr | None],
    active_run: Callable[[], bool],
) -> Refusal | None:
    """The first matching refusal, or ``None`` to proceed (D-92).

    ``linked_pr`` and ``active_run`` run lazily, in order, only when every
    earlier check passed. A fault inside one propagates; it is never a verdict.
    """
    if facts.is_pull_request:
        return Refusal("pull_request")
    if facts.state != "open":
        return Refusal("closed")
    pr = linked_pr()
    if pr is not None:
        return Refusal("linked_pr", pr_number=pr.number, pr_repo=pr.repo)
    if active_run():
        return Refusal("active_run")
    return None


# ---------------------------------------------------------------------------
# The reply
# ---------------------------------------------------------------------------


def _positive(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def reply_line(refusal: Refusal, issue_number: int | None) -> str:
    """The fixed sentence for ``refusal``. Raises ``ValueError`` on an open input."""
    code = refusal.reason
    if code not in REPLY_TEXT:
        raise ValueError(f"unknown refusal code {code!r}")
    allowed = _DETAIL_SETS.get(code)
    if allowed is None:
        if refusal.detail is not None:
            raise ValueError(f"refusal {code} takes no detail")
    elif refusal.detail not in allowed:
        raise ValueError(f"refusal {code} names a value outside its closed set")
    pr_ref: str | None = None
    if code == "linked_pr":
        if not _positive(refusal.pr_number):
            raise ValueError("refusal linked_pr needs a positive PR number")
        pr_ref = f"#{refusal.pr_number}"
        if refusal.pr_repo is not None:
            repo = refusal.pr_repo
            if (
                not isinstance(repo, str)
                or not _PR_REPO.fullmatch(repo)
                or set(repo.split("/")) & {".", ".."}
            ):
                raise ValueError("refusal linked_pr names a repository outside GitHub's grammar")
            pr_ref = f"{repo}#{refusal.pr_number}"
    elif refusal.pr_number is not None or refusal.pr_repo is not None:
        raise ValueError(f"refusal {code} takes no PR")
    needs_issue = "{issue}" in REPLY_TEXT[code]
    if needs_issue and not _positive(issue_number):
        raise ValueError("the issue number must be a positive integer")
    if issue_number is not None and not _positive(issue_number):
        raise ValueError("the issue number must be a positive integer")
    return REPLY_PREFIX + REPLY_TEXT[code].format(
        issue=issue_number, pr=pr_ref, detail=refusal.detail
    )


def build_reply(
    run_id: str, refusal: Refusal, issue_number: int | None, run_link: str | None = None
) -> str:
    """The refusal comment: marker, fixed sentence, run link (D-104)."""
    rid = canonical_run_id(run_id)
    marker = build("refusal", rid, refusal.reason)
    line = reply_line(refusal, issue_number)
    run_ref = (
        run_link if isinstance(run_link, str) and _RUN_LINK.fullmatch(run_link) else f"`{rid}`"
    )
    return f"{marker}\n{line}\nRun: {run_ref}"


# ---------------------------------------------------------------------------
# active_run: trusted open claims and v_runs
# ---------------------------------------------------------------------------


def open_claim_runs(
    comments: Iterable[Any], app_id: int, own_run_id: str | None = None
) -> list[str]:
    """Run ids of trusted claims with no trusted ``pr``, ``disposition`` or ``refusal``.

    A ``refusal`` marker never opens a claim (D-104); a trusted one for the same
    run closes it, as spec §8.2 states. Forged markers count for nothing
    (D-53). This run's own id is excluded. Unique, in comment order.
    """
    comments = list(comments)
    refused = {m.run_id for _, m in trusted_markers(comments, app_id) if m.kind == "refusal"}
    own = canonical_run_id(own_run_id) if own_run_id is not None else None
    out: list[str] = []
    for _, rid in open_claims(comments, app_id):
        if rid in refused or rid == own or rid in out:
            continue
        out.append(rid)
    return out


class RunStatusReader:
    """Reads ``v_runs.effective_status`` through PostgREST with the service key.

    Mirrors ``credentials._get_installation``: a plain ``GET`` on
    ``/rest/v1/<view>`` with the ``apikey`` and bearer headers, never following
    a redirect. Any failure, a 3xx included, is :class:`SupabaseUnavailable`,
    whose message names no key or body.
    """

    def __init__(
        self,
        supabase_url: str,
        supabase_key: str,
        *,
        session: Any = None,
        timeout: float = SUPABASE_TIMEOUT,
    ) -> None:
        self.url = supabase_url.rstrip("/") + "/rest/v1/v_runs"
        self._key = supabase_key
        # ``requests`` itself, or any object with the same ``get()``.
        self.session: Any = session if session is not None else requests
        self.timeout = timeout

    def __call__(self, run_ids: Sequence[str]) -> dict[str, str]:
        return self.effective_statuses(run_ids)

    def effective_statuses(self, run_ids: Sequence[str]) -> dict[str, str]:
        """``{run_id: effective_status}`` for the ids that have a row."""
        ids = [canonical_run_id(r) for r in run_ids]
        if not ids:
            return {}
        try:
            resp = self.session.get(
                self.url,
                headers={
                    "apikey": self._key,
                    "Authorization": f"Bearer {self._key}",
                    "Accept": "application/json",
                },
                params={"select": "id,effective_status", "id": f"in.({','.join(ids)})"},
                timeout=self.timeout,
                # Never followed (QA 3): a redirect would carry the ``apikey``
                # header, which ``requests`` doesn't strip, to another host.
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise SupabaseUnavailable(
                f"v_runs read could not reach Supabase ({type(exc).__name__})"
            ) from None
        status = resp.status_code
        if not 200 <= status < 300:
            raise SupabaseUnavailable(f"v_runs read returned {status}")
        try:
            rows = resp.json()
        except ValueError:
            raise SupabaseUnavailable("v_runs read returned no JSON") from None
        if not isinstance(rows, list):
            raise SupabaseUnavailable("v_runs read returned no list")
        out: dict[str, str] = {}
        for row in rows:
            if not (
                isinstance(row, Mapping)
                and isinstance(row.get("id"), str)
                and isinstance(row.get("effective_status"), str)
            ):
                raise SupabaseUnavailable("v_runs read returned a malformed row")
            out[str(row["id"]).lower()] = str(row["effective_status"])
        return {rid: out[rid] for rid in ids if rid in out}


def has_active_run(
    comments: Iterable[Any],
    app_id: int,
    own_run_id: str,
    read_statuses: Callable[[Sequence[str]], Mapping[str, str]],
    *,
    warn: Callable[[str], None] | None = None,
) -> bool:
    """Refusal (d): an open trusted claim whose run is ``queued`` or ``running``.

    Each claimed run resolves by its ``v_runs.effective_status`` (CT-34):

    - :data:`NON_TERMINAL_STATUSES` → active;
    - :data:`TERMINAL_STATUSES` → finished;
    - no row → finished, with a warning (DF-185-03: a deleted run must not
      block the issue for ever);
    - any other value → :class:`SupabaseUnavailable`, with a warning (QA 2):
      an unknown status is a fault, never read as "finished" (D-67). It fails
      closed even next to an active claim, so the outcome doesn't depend on
      claim order.

    ``warn`` reports a warning as a ``run_event`` (the step passes one);
    without it the warning goes to the log only.
    """
    candidates = open_claim_runs(comments, app_id, own_run_id)
    if not candidates:
        return False
    report = warn if warn is not None else (lambda m: log.warning("%s", m))
    statuses = read_statuses(candidates)
    active = False
    for rid in candidates:
        status = statuses.get(rid)
        if status is None:
            report(f"claim for run {rid} has no v_runs row; treated as terminal")
        elif status in NON_TERMINAL_STATUSES:
            active = True
        elif status not in TERMINAL_STATUSES:
            report(f"claim for run {rid} has an unknown effective_status; failing closed")
            raise SupabaseUnavailable(f"v_runs returned an unknown effective_status for run {rid}")
    return active


# ---------------------------------------------------------------------------
# The step
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CheckOutcome:
    """The result of the preflight and refusal step.

    ``status`` is ``proceed``, ``succeeded`` (a refusal: ``outcome`` is
    ``not_applicable`` and ``reason`` the code) or ``failed`` (``error_code``).
    ``reply`` is ``posted``, ``failed`` or ``none``. On ``proceed``, ``params``,
    ``facts`` and ``token`` are set for the next steps.
    """

    status: str
    summary: str
    outcome: str | None = None
    reason: str | None = None
    error_code: str | None = None
    reply: str = "none"
    params: Params | None = None
    facts: IssueFacts | None = None
    token: TokenContext | None = None

    @property
    def proceed(self) -> bool:
        return self.status == "proceed"

    def result(self) -> dict[str, Any]:
        """``runs.result`` for a refusal: ``{reason, summary}``; empty otherwise.

        Never carries a ``board`` key: a refusal touches no board (TC-185-23).
        """
        if self.status == "succeeded":
            return {"reason": self.reason, "summary": self.summary}
        return {}

    def report(self, run: Any) -> None:
        """End the run for a refusal or a fault; a ``proceed`` reports nothing."""
        if self.status == "succeeded":
            run.succeed("not_applicable", result=self.result())
        elif self.status == "failed":
            run.fail(self.error_code or "UNHANDLED_ERROR", self.summary)


def _event(run: Any, level: str, message: str, secrets: SecretsLike) -> None:
    message = scrub_all(message, secrets)
    getattr(log, "warning" if level == "warn" else level)("%s", message)
    if run is None:
        return
    try:
        getattr(run, level)(message)
    except Exception:  # noqa: BLE001 — a reporting failure never changes the outcome
        return


def _failed(code: str, exc: BaseException, secrets: SecretsLike, run: Any) -> CheckOutcome:
    summary = scrub_all(f"{code}: {scrub_exception(exc, secrets)}", secrets)
    _event(run, "error", summary, secrets)
    return CheckOutcome(status="failed", summary=summary, error_code=code)


def _usable_issue(raw: object) -> int | None:
    """``issue_number`` when it alone passes the schema, else ``None``."""
    if not isinstance(raw, Mapping) or "issue_number" not in raw:
        return None
    try:
        return parse_params({"issue_number": raw["issue_number"]}).issue_number
    except ParamsError:
        return None


def run_refusal_checks(
    *,
    run_id: str,
    owner: str,
    repo: str,
    raw_params: object,
    resolve_token: Callable[[], TokenContext],
    run_status: Callable[[Sequence[str]], Mapping[str, str]],
    session: Any = None,
    run: Any = None,
    run_link: str | None = None,
    secrets: SecretsLike | None = None,
    sleep: Callable[[float], None] | None = None,
) -> CheckOutcome:
    """Run the preflight and the refusal checks; post the reply on a refusal.

    ``session`` is the GitHub transport (tests pass the in-repo double),
    ``run_status`` reads ``v_runs`` (a :class:`RunStatusReader`), and ``run`` is
    the run reporter for ``run_events``. Makes no claim and no board call.
    """
    secrets = [] if secrets is None else secrets
    rid = canonical_run_id(run_id)

    # Preflight 1–2: credentials and issues: write (D-58).
    try:
        token = resolve_token()
    except CredentialError as exc:
        # CREDENTIALS_UNAVAILABLE, or GITHUB_PERMISSION_MISSING for a token
        # that lost issues: write on a refresh (QA 6).
        return _failed(exc.error_code, exc, secrets, run)
    if token.app_id is None:
        return _failed(
            "CREDENTIALS_UNAVAILABLE",
            CredentialError("INVALID_APP_ID", "the installation has no App id"),
            secrets,
            run,
        )
    if not has_issues_write(token.permissions):
        summary = "GITHUB_PERMISSION_MISSING: the installation token lacks issues: write"
        _event(run, "error", summary, secrets)
        return CheckOutcome(
            status="failed", summary=summary, error_code="GITHUB_PERMISSION_MISSING"
        )

    client = IssuesClient(owner, repo, token.token, session=session, sleep=sleep)

    def refuse(refusal: Refusal, issue: int | None, *, reply: bool) -> CheckOutcome:
        summary = reply_line(refusal, issue)
        state = "none"
        if reply and issue is not None:
            try:
                client.post_comment(issue, build_reply(rid, refusal, issue, run_link))
                state = "posted"
            except Exception as exc:  # noqa: BLE001 — the reply is best effort (spec §8.2)
                state = "failed"
                _event(
                    run,
                    "warn",
                    f"refusal reply for {refusal.reason} failed: {scrub_exception(exc, secrets)}",
                    secrets,
                )
        _event(run, "info", f"refused: {refusal.reason} (reply {state})", secrets)
        return CheckOutcome(
            status="succeeded",
            summary=summary,
            outcome="not_applicable",
            reason=refusal.reason,
            reply=state,
            token=token,
        )

    # Preflight 3: params (D-82).
    try:
        params = parse_params(raw_params)
    except ParamsError as exc:
        key = exc.key if exc.key in INVALID_PARAMS_KEYS else "params"
        issue = _usable_issue(raw_params)
        return refuse(Refusal("invalid_params", detail=key), issue, reply=issue is not None)

    issue = params.issue_number
    try:
        facts = client.get_issue(issue)
        if facts is None:  # 404: no such issue here (DF-34)
            return refuse(Refusal("invalid_params", detail="issue_number"), None, reply=False)
        verdict = decide(
            facts,
            lambda: client.linked_pr(issue),
            lambda: has_active_run(
                client.list_comments(issue),
                token.app_id or 0,
                rid,
                run_status,
                warn=lambda message: _event(run, "warn", message, secrets),
            ),
        )
    except GitHubError as exc:
        return _failed(exc.code, exc, secrets, run)
    except SupabaseUnavailable as exc:
        return _failed(exc.code, exc, secrets, run)

    if verdict is not None:
        return refuse(verdict, issue, reply=True)
    _event(run, "info", f"refusal checks passed for #{issue}", secrets)
    return CheckOutcome(
        status="proceed",
        summary=f"refusal checks passed for #{issue}",
        params=params,
        facts=facts,
        token=token,
    )
