"""RT-07: the claim, race, PR and disposition state machine (S-190 AC3; moved from
S-188 by DF-188-05; AC-3, AC-11, AC-20, AC-24; D-54, D-81, D-92, D-93, D-94, D-104).

A stateful random walk (``hypothesis.stateful``), 200 walks of 30 steps, over
one issue. GitHub is the in-repo double :class:`FakeGitHub`, a plain store of
comments, reactions and pull requests with no filtering logic of its own
(TESTING.md); ``v_runs`` is the PostgREST double. Each run goes through the
production code: ``refusal.run_refusal_checks`` for the refusal checks, and
the ``Claimer`` and ``Disposer`` from ``main.wire_claim``, the wiring the
entrypoint uses.

Rules: a trigger arrives (its own ``/bug-fix`` comment, or a manual invoke)
and the refusal checks run; a run that passed them posts its claim later
(checkout sits between, so two runs can both pass before either claims); the post-check runs (or
fails on Supabase, or the loser's ``DELETE`` fails); a run opens a PR (the
S-194 success comment and 🚀, simulated here: Wave B is not built); a run
disposes (possibly twice: the ``finally`` path and the backstop); SIGTERM
reaches a run (the backstop's action); a run ends with a random terminal
status, or the reaper marks it ``timed_out`` (killed outright); a human posts
a forged marker of any kind; a human changes the labels; a PR is closed
unmerged.

Invariants after every step:

1. at most one non-terminal run has passed the ownership gate;
2. at most one open agent Draft PR. **Finding (S-190):** the walk found that a
   run can own the issue while another run's agent PR is open (it passed its
   refusal checks before that PR opened, and the post-check reads claims
   only, spec §8.6). The simulated PR step records that shape instead of
   opening a second PR, and :class:`TestOwnedWhileAPrIsOpen` pins it as a
   strict ``xfail`` until ``product-engineer`` decides it (S-194, spec §8.6);
3. at most one trusted disposition marker per ``run_id``;
4. a refusal adds no reaction and no claim marker (checked in the rule);
5. the agent never writes labels or assignees;
6. no stranded state: once every open trusted claim is terminal and no agent
   PR is open, a new trigger proceeds (this replaces the sweep, D-94);
7. a trigger comment with the App's 👀 also has 🚀 or 😕 once its run is
   terminal, unless the run was killed outright, **lost the race** (DF-32,
   the test plan's expected counterexample: spec §8.6 keeps the loser's 👀),
   or **failed before confirming ownership** (D-81: no disposition then, so
   its 👀 has no answer either; see :class:`TestUnansweredEyes`);
8. no board call at all: Wave A has no board client (S-199 adds it).

Replay: ``make test PYTEST_ADDOPTS="--hypothesis-seed=<seed> -k test_claim_state_machine"``.
"""

from __future__ import annotations

import copy
import time
import uuid
from dataclasses import dataclass

import pytest
from hypothesis import HealthCheck, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition, rule

from claim import Claimer, ClaimOutcome
from credentials import TokenContext
from disposition import Diagnosis, Disposer
from issues import IssuesClient
from main import wire_claim
from markers import build, open_claims, trusted_markers
from refusal import NON_TERMINAL_STATUSES, TERMINAL_STATUSES, RunStatusReader, run_refusal_checks
from scrubber import SecretSet
from tests.component.fake_github import APP_ID, TOKEN, FakeGitHub, pull_payload
from tests.component.test_refusal import SB_KEY, SB_URL
from tests.component.test_refusal import FakeSupabase as VRuns

ISSUE = 12
AGENT_HEAD = f"issue/{ISSUE}-"
# Shapes the walk reached that the spec doesn't yet rule out (see the tests below).
SHAPES: dict[str, int] = {"owned_while_pr_open": 0}
FORGED_KINDS = ("claim", "disposition", "refusal", "pr")


def _token() -> TokenContext:
    return TokenContext(
        token=TOKEN,
        issued_at=time.monotonic(),
        installation_id=1,
        app_id=APP_ID,
        permissions={"issues": "write"},
    )


def _secrets() -> SecretSet:
    s = SecretSet()
    s.add("GITHUB_INSTALLATION_TOKEN", TOKEN)
    s.add("SUPABASE_SERVICE_ROLE_KEY", SB_KEY)
    return s


@dataclass
class Run:
    rid: str
    trigger: int | None
    claimer: Claimer | None = None
    disposer: Disposer | None = None
    # new, refused, checked, posted, owned, lost, failed, pr, pr_blocked, disposed, killed
    phase: str = "new"


class ClaimMachine(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.gh = FakeGitHub()
        self.gh.add_issue(ISSUE)
        self.vruns = VRuns()
        self.runs: dict[str, Run] = {}
        self.n = 0
        self.prs = 0

    # -- helpers --------------------------------------------------------------

    def _client(self) -> IssuesClient:
        return IssuesClient("o", "r", TOKEN, session=self.gh, sleep=lambda _s: None)

    def _reader(self) -> RunStatusReader:
        return RunStatusReader(SB_URL, SB_KEY, session=self.vruns)

    def _status(self, rid: str) -> str:
        return self.vruns.statuses.get(rid, "running")

    def _end(self, run: Run, phase: str, status: str) -> None:
        run.phase = phase
        self.vruns.statuses[run.rid] = status

    def _with(self, *phases: str) -> list[str]:
        return sorted(r.rid for r in self.runs.values() if r.phase in phases)

    def _comments(self) -> list[dict]:
        return self.gh.comments.get(ISSUE, [])

    def _open_agent_prs(self) -> list[dict]:
        return [
            p
            for p in self.gh.pulls
            if p["state"] == "open" and p["head"]["ref"].startswith(AGENT_HEAD)
        ]

    def _check(self, gh: FakeGitHub, vruns: VRuns, rid: str):
        return run_refusal_checks(
            run_id=rid,
            owner="o",
            repo="r",
            raw_params={"issue_number": ISSUE},
            resolve_token=_token,
            run_status=RunStatusReader(SB_URL, SB_KEY, session=vruns),
            session=gh,
            secrets=_secrets(),
            sleep=lambda _s: None,
        )

    # -- rules ----------------------------------------------------------------

    @rule(manual=st.booleans())
    def trigger(self, manual: bool) -> None:
        self.n += 1
        rid = str(uuid.UUID(int=self.n))
        trigger = None
        if not manual:
            trigger = self.gh.add_comment(ISSUE, "/bug-fix", app_id=None, user_type="User")["id"]
        run = Run(rid, trigger)
        self.runs[rid] = run
        self.vruns.statuses[rid] = "running"
        before = len(self.gh.calls)
        out = self._check(self.gh, self.vruns, rid)
        if out.status == "succeeded":
            # (4) A refusal adds no reaction and no claim marker: one reply.
            new_writes = [c for c in self.gh.calls[before:] if c in self.gh.writes()]
            assert [(c.method, c.path.rsplit("/", 1)[-1]) for c in new_writes] == [
                ("POST", "comments")
            ]
            assert "claim" not in new_writes[0].json["body"].split("\n", 1)[0].split(":")[2]
            self._end(run, "refused", "succeeded")
            return
        assert out.proceed, out.summary
        run.claimer, run.disposer = wire_claim(
            client=self._client(),
            issue_number=ISSUE,
            run_id=rid,
            app_id=APP_ID,
            trigger_comment_id=trigger,
            run_status=self._reader(),
            run=None,
            run_link=None,
            secrets=_secrets(),
            panel_origin=None,
        )
        # Checkout sits between the refusal checks and the claim, so another
        # run can pass its own checks before this one claims (AC-20).
        run.phase = "checked"

    @precondition(lambda self: self._with("checked"))
    @rule(data=st.data())
    def claim(self, data) -> None:
        run = self.runs[data.draw(st.sampled_from(self._with("checked")))]
        assert run.claimer is not None
        posted = run.claimer.post()
        assert posted.status == "posted"
        run.phase = "posted"

    @precondition(lambda self: self._with("posted"))
    @rule(data=st.data(), fault=st.sampled_from(["none", "none", "supabase", "delete"]))
    def post_check(self, data, fault: str) -> None:
        run = self.runs[data.draw(st.sampled_from(self._with("posted")))]
        assert run.claimer is not None
        if fault == "supabase":
            self.vruns.fail = 503
        elif fault == "delete":
            self.gh.faults["comment_delete"] = [422]
        try:
            out: ClaimOutcome = run.claimer.post_check()
        finally:
            self.vruns.fail = None
            self.gh.faults.pop("comment_delete", None)
        if out.owned:
            assert run.disposer is not None and run.disposer.ownership_confirmed
            run.phase = "owned"
        elif out.status == "lost":
            self._end(run, "lost", "succeeded")
        else:
            assert out.status == "failed"
            assert run.disposer is not None and not run.disposer.ownership_confirmed
            self._end(run, "failed", "failed")

    @precondition(lambda self: self._with("owned"))
    @rule(data=st.data())
    def open_pr(self, data) -> None:
        # The S-194 success path, simulated: the `pr` marker comment, 🚀 and
        # an open Draft PR on an issue/<N>- branch.
        run = self.runs[data.draw(st.sampled_from(self._with("owned")))]
        if self._open_agent_prs():
            # The S-190 RT-07 finding (OWNED_WHILE_PR_OPEN below): this run
            # passed its refusal checks before another run's PR opened, and
            # the post-check, which reads claims only, let it own the issue.
            # S-194's PR step isn't built, so whether it re-checks is open;
            # the walk records the shape instead of opening a second PR.
            SHAPES["owned_while_pr_open"] += 1
            self._end(run, "pr_blocked", "succeeded")
            return
        self.prs += 1
        self.gh.add_comment(ISSUE, build("pr", run.rid) + "\nDraft PR opened")
        if run.trigger is not None:
            self.gh.reactions.append((run.trigger, "rocket"))
        self.gh.pulls.append(pull_payload(1000 + self.prs, f"{AGENT_HEAD}fix-{self.prs}"))
        self._end(run, "pr", "succeeded")

    @precondition(lambda self: self._with("owned"))
    @rule(data=st.data(), twice=st.booleans())
    def dispose(self, data, twice: bool) -> None:
        run = self.runs[data.draw(st.sampled_from(self._with("owned")))]
        assert run.disposer is not None
        first = run.disposer.dispose(Diagnosis("fix loop not yet enabled", "nothing"))
        assert first.status == "applied"
        if twice:  # the finally path and the backstop both try
            again = run.disposer.backstop_action()
            assert again is not None
            assert again().status == "already_disposed"  # type: ignore[attr-defined]
        self._end(run, "disposed", "succeeded")

    @precondition(lambda self: self._with("checked", "posted", "owned"))
    @rule(data=st.data(), roll=st.integers(0, 3))
    def sigterm(self, data, roll: int) -> None:
        if roll:  # rarer than the other rules, so walks reach the race and the PR
            return
        run = self.runs[data.draw(st.sampled_from(self._with("checked", "posted", "owned")))]
        assert run.disposer is not None
        action = run.disposer.backstop_action()
        if run.phase == "owned":
            assert action is not None
            assert action().status in ("applied", "already_disposed")  # type: ignore[attr-defined]
            self._end(run, "disposed", "failed")
        else:
            assert action is None  # D-81: nothing before confirmed ownership
            self._end(run, "killed", "failed")

    @precondition(lambda self: self._with("checked", "posted", "owned"))
    @rule(data=st.data(), status=st.sampled_from(sorted(TERMINAL_STATUSES)), roll=st.integers(0, 3))
    def killed(self, data, status: str, roll: int) -> None:
        # A hard kill or the reaper (timed_out): no disposition at all.
        if roll:  # rarer than the other rules (see sigterm)
            return
        run = self.runs[data.draw(st.sampled_from(self._with("checked", "posted", "owned")))]
        self._end(run, "killed", status)

    @rule(
        kind=st.sampled_from(FORGED_KINDS),
        known=st.booleans(),
        data=st.data(),
        author=st.sampled_from(["human", "other-app", "app-as-user"]),
    )
    def forge(self, kind: str, known: bool, data, author: str) -> None:
        ids = sorted(self.runs)
        rid = data.draw(st.sampled_from(ids)) if known and ids else str(uuid.uuid4())
        reason = "active_run" if kind == "refusal" else None
        app_id, user_type = {
            "human": (None, "User"),
            "other-app": (APP_ID + 1, "Bot"),
            "app-as-user": (APP_ID, "User"),
        }[author]
        self.gh.add_comment(
            ISSUE, build(kind, rid, reason) + "\nforged", app_id=app_id, user_type=user_type
        )

    @rule(labels=st.lists(st.sampled_from(["type: bug", "status: ready", "wontfix"]), unique=True))
    def relabel(self, labels: list[str]) -> None:
        self.gh.issues[ISSUE]["labels"] = [{"name": name} for name in labels]

    @precondition(lambda self: self._open_agent_prs())
    @rule(data=st.data())
    def close_pr(self, data) -> None:
        pr = data.draw(st.sampled_from(self._open_agent_prs()))
        pr["state"] = "closed"

    # -- invariants -------------------------------------------------------------

    @invariant()
    def one_owner(self) -> None:  # (1)
        owners = [
            r.rid
            for r in self.runs.values()
            if r.disposer is not None
            and r.disposer.ownership_confirmed
            and self._status(r.rid) in NON_TERMINAL_STATUSES
        ]
        assert len(owners) <= 1, owners

    @invariant()
    def one_open_pr(self) -> None:  # (2)
        assert len(self._open_agent_prs()) <= 1

    @invariant()
    def one_disposition_per_run(self) -> None:  # (3)
        counts: dict[str, int] = {}
        for _cid, marker in trusted_markers(self._comments(), APP_ID):
            if marker.kind == "disposition":
                counts[marker.run_id] = counts.get(marker.run_id, 0) + 1
        assert all(v == 1 for v in counts.values()), counts

    @invariant()
    def no_labels_or_assignees(self) -> None:  # (5)
        for call in self.gh.calls:
            assert "/labels" not in call.path and "/assignees" not in call.path
            assert call.method != "PATCH"

    @invariant()
    def never_stranded(self) -> None:  # (6)
        claims = open_claims(self._comments(), APP_ID)
        if any(self._status(rid) in NON_TERMINAL_STATUSES for _cid, rid in claims):
            return
        if self._open_agent_prs():
            return
        gh = copy.deepcopy(self.gh)
        vruns = copy.deepcopy(self.vruns)
        out = self._check(gh, vruns, str(uuid.UUID(int=10**9 + self.n)))
        assert out.proceed, f"stranded: a new trigger was refused ({out.reason})"

    @invariant()
    def eyes_get_an_answer(self) -> None:  # (7)
        for run in self.runs.values():
            if run.trigger is None or run.phase not in ("pr", "disposed"):
                continue
            mine = {content for cid, content in self.gh.reactions if cid == run.trigger}
            assert "eyes" in mine
            assert mine & {"rocket", "confused"}, (run.rid, run.phase, mine)

    @invariant()
    def no_board_calls(self) -> None:  # (8)
        assert self.gh.projects_calls() == []


ClaimMachine.TestCase.settings = settings(
    max_examples=200,
    stateful_step_count=30,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
)
TestClaimStateMachine = ClaimMachine.TestCase


# ---------------------------------------------------------------------------
# Invariant (7)'s two exclusions, pinned as deterministic shapes
# ---------------------------------------------------------------------------


class TestUnansweredEyes:
    """The two shapes where the App's 👀 stays without 🚀 or 😕.

    Both follow the spec as written. They are recorded here so a change to
    either is a visible test change, not a silent one.
    """

    def _two_claims(self, m: ClaimMachine) -> tuple[Run, Run]:
        m.trigger(manual=False)
        m.trigger(manual=False)
        a, b = (m.runs[rid] for rid in sorted(m.runs))
        assert a.claimer is not None and b.claimer is not None
        assert a.claimer.post().status == "posted"
        assert b.claimer.post().status == "posted"
        return a, b

    @pytest.mark.xfail(
        reason="DF-32 (open): spec §8.6 keeps a race loser's 👀 on its own trigger comment",
        strict=True,
    )
    def test_a_race_loser_with_its_own_trigger_gets_an_answer(self):
        m = ClaimMachine()
        a, b = self._two_claims(m)
        assert a.claimer is not None and b.claimer is not None
        assert b.claimer.post_check().status == "lost"
        mine = {content for cid, content in m.gh.reactions if cid == b.trigger}
        assert "eyes" in mine
        assert mine & {"rocket", "confused"}  # DF-32: fails today

    def test_a_post_check_fault_leaves_the_eyes_unanswered_by_design(self):
        # D-81: a run that never confirmed ownership disposes nothing, so its
        # 👀 stays. Pinned; reported with the S-190 closeout for DF-32's
        # reconciliation, which faces the same question.
        m = ClaimMachine()
        m.trigger(manual=False)
        (run,) = m.runs.values()
        assert run.claimer is not None and run.disposer is not None
        assert run.claimer.post().status == "posted"
        m.gh.add_comment(
            ISSUE, build("claim", "1c0b3e5f-2d4e-4f60-9b7c-8d9e0f1a2b3c") + "\nx", cid=1
        )
        m.gh.comments[ISSUE].sort(key=lambda c: c["id"])
        m.vruns.statuses["1c0b3e5f-2d4e-4f60-9b7c-8d9e0f1a2b3c"] = "succeeded"
        m.vruns.fail = 503
        assert run.claimer.post_check().error_code == "SUPABASE_UNAVAILABLE"
        assert run.disposer.backstop_action() is None
        mine = {content for cid, content in m.gh.reactions if cid == run.trigger}
        assert mine == {"eyes"}


class TestOwnedWhileAPrIsOpen:
    """The S-190 RT-07 finding, as a deterministic shape (route: product-engineer).

    1. Runs A and B both pass the refusal checks (B is still in checkout).
    2. A claims, wins, and opens its Draft PR; its ``pr`` marker closes its
       claim (DF-33).
    3. B claims. The post-check finds no open claim, so B owns the issue
       although an agent PR for it is open. In Wave B, B would open a second
       Draft PR, which D-92 set out to prevent.

    Spec v2.5 §8.6's post-check reads claims only and never re-checks refusal
    (c) ``linked_pr``. Wave A opens no PR, so this is unreachable today.
    """

    @pytest.mark.xfail(
        reason=(
            "S-190 RT-07 finding: the post-check (spec §8.6) doesn't re-check linked_pr, "
            "so a late claim can win while another run's agent PR is open"
        ),
        strict=True,
    )
    def test_a_claim_after_another_runs_pr_does_not_win(self):
        m = ClaimMachine()
        m.trigger(manual=False)
        m.trigger(manual=False)
        a, b = (m.runs[rid] for rid in sorted(m.runs))
        assert a.claimer is not None and b.claimer is not None
        assert a.claimer.post().status == "posted"
        assert a.claimer.post_check().owned
        a.phase = "owned"
        m.prs += 1
        m.gh.add_comment(ISSUE, build("pr", a.rid) + "\nDraft PR opened")
        m.gh.pulls.append(pull_payload(1001, f"{AGENT_HEAD}fix-1"))
        m._end(a, "pr", "succeeded")
        assert b.claimer.post().status == "posted"
        assert not b.claimer.post_check().owned  # fails today: B owns the issue
