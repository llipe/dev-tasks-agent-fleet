"""L2 tests for the entrypoint's step orchestration (S-190 AC1–AC4; spec §4, §8.2–§8.9;
FR-5, FR-25–FR-27; D-20, D-58, D-67, D-81, D-92, D-94, D-104, D-112).

Every test drives ``main.invoke`` end to end:

- GitHub is the in-repo double :class:`FakeGitHub` (DF-186-02), never
  ``responses``; the real ``IssuesClient`` and retry policy run.
- ``v_runs`` is the PostgREST double from ``test_refusal``.
- The run reporter is the real ``RunReporter`` over a recording Supabase
  client, so ``run_steps``, ``run_events``, ``runs.result`` and
  ``runs.metrics`` are what production would write.
- Checkout clones a fixture repo from a local bare remote with real ``git``;
  ``fixer`` spawns go through :class:`SpawnSpy`, and install and the gates
  through :class:`StubSandbox`.
- The SIGTERM backstop is exercised by calling the handler's body
  (``signal_backstop.handle_termination``) with the getters ``main``
  installed, from inside the step that is running, then raising
  :class:`Died` (a ``BaseException``) as the process would die.

TC-190-01, -02, -06, -07, -08, -09, -11, -13; TC-189-08, TC-189-21; the
S-188 QA gap 1 end-to-end chain (refusal → checkout → claim → disposer with
the real ``Disposer`` and ``Config.run_link``); the S-185 residual (token
refresh errors mapped by ``exc.error_code``); the S-189 sysctl preflight.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import pytest

import agent_reporter
import main
import outcomes
import signal_backstop
from checkout import WorkPaths
from config import Config
from credentials import CredentialError, GitHubSession, PermissionMissing, TokenContext
from heartbeat import is_heartbeat_chunk, is_terminal_chunk, read_terminal_payload
from markers import build, parse_block
from run_link import RunLink
from tests.component.fake_github import APP_ID, TOKEN, Call, FakeGitHub
from tests.component.repo_fixtures import SpawnSpy, StubSandbox, make_remote, result
from tests.component.test_refusal import FakeSupabase as VRuns

RUN = "0b9a2f4e-1c3d-4e5f-8a6b-7c8d9e0f1a2b"
OTHER = "1c0b3e5f-2d4e-4f60-9b7c-8d9e0f1a2b3c"
ISSUE = 12
TRIGGER = 9_001
PANEL = "https://dt-agent-fleet-panel.fly.dev"
LINK = f"{PANEL}/runs/{RUN}"
SB_KEY = "sb_secret_" + "M" * 40
PEM = "-----BEGIN RSA PRIVATE KEY-----\nMIIfake\n-----END RSA PRIVATE KEY-----"
WAVE_A_STEPS = ["preflight", "refuse", "checkout", "claim"]


class Died(BaseException):
    """The process dying right after the SIGTERM handler (it re-raises SIGTERM)."""


# ---------------------------------------------------------------------------
# The reporter's Supabase client, recorded
# ---------------------------------------------------------------------------


class ReporterDB:
    """Stands in for ``agent_reporter._SupabaseClient``: records every write."""

    instances: list[ReporterDB] = []
    insert_fails: bool = False

    def __init__(self, url: str, key: str) -> None:
        self.url = url
        self.key = key
        self.calls: list[tuple[str, str, Any]] = []
        ReporterDB.instances.append(self)

    def insert(self, table: str, rows: Any) -> bool:
        self.calls.append(("insert", table, rows))
        # The vendored client never raises: on a failure it prints and returns False.
        return not ReporterDB.insert_fails

    def update(self, table: str, filt: str, patch: dict) -> bool:
        self.calls.append(("update", table, patch))
        return True

    def update_expect_rows(self, table: str, filt: str, patch: dict) -> int | None:
        self.calls.append(("update", table, patch))
        return 1

    # -- views ---------------------------------------------------------------

    def run_patches(self) -> list[dict]:
        return [p for (op, t, p) in self.calls if op == "update" and t == "runs"]

    def final(self) -> dict:
        return self.run_patches()[-1]

    def steps(self) -> list[dict]:
        return [
            r for (op, t, rows) in self.calls if op == "insert" and t == "run_steps" for r in rows
        ]

    def step_keys(self) -> list[str]:
        return [s["key"] for s in self.steps()]

    def step_updates(self) -> list[dict]:
        return [p for (op, t, p) in self.calls if op == "update" and t == "run_steps"]

    def events(self) -> list[dict]:
        return [
            r for (op, t, rows) in self.calls if op == "insert" and t == "run_events" for r in rows
        ]

    def messages(self) -> list[str]:
        return [e["message"] for e in self.events()]

    def events_by_step(self) -> dict[str, list[str]]:
        names = {s["id"]: s["key"] for s in self.steps()}
        out: dict[str, list[str]] = {}
        for e in self.events():
            out.setdefault(names.get(e["step_id"], "-"), []).append(e["message"])
        return out


# ---------------------------------------------------------------------------
# A GitHub double that can run a hook on a request
# ---------------------------------------------------------------------------


@dataclass
class HookedGitHub(FakeGitHub):
    hook: Callable[[Call], None] | None = None

    def request(self, method, url, **kwargs):  # type: ignore[override]
        resp = super().request(method, url, **kwargs)
        if self.hook is not None:
            self.hook(self.calls[-1])
        return resp


# ---------------------------------------------------------------------------
# The world one run sees
# ---------------------------------------------------------------------------


def _token(perms: dict[str, str] | None = None) -> TokenContext:
    return TokenContext(
        token=TOKEN,
        issued_at=time.monotonic(),
        installation_id=1,
        app_id=APP_ID,
        permissions={"issues": "write", "contents": "write"} if perms is None else perms,
    )


@dataclass
class World:
    tmp: Path
    fixture: str | None = "py-make-ok"
    trigger: int | None = TRIGGER
    fix_loop: bool = False
    panel: str | None = PANEL
    gh: HookedGitHub = field(default_factory=HookedGitHub)
    vruns: VRuns = field(default_factory=VRuns)
    sandbox: StubSandbox = field(default_factory=StubSandbox)
    spy: SpawnSpy = field(default_factory=SpawnSpy)
    resolve: Callable[..., GitHubSession] | None = None
    refresh: Callable[..., TokenContext] | None = None
    fix_runner: Any = None
    heartbeat_interval: float = 60.0
    backstop: dict[str, Any] = field(default_factory=dict)
    params: dict[str, Any] | None = None
    remote_url: str | None = None  # overrides the fixture remote

    def __post_init__(self) -> None:
        self.gh.add_issue(ISSUE)
        self.remote = make_remote(self.tmp, self.fixture) if self.fixture else None
        wrapper = self.tmp / "work" / "wrapper"
        repo = self.tmp / "work" / "repo"
        wrapper.mkdir(parents=True, mode=0o700)
        repo.mkdir(parents=True)
        self.paths = WorkPaths(wrapper_dir=str(wrapper), repo_dir=str(repo))
        self.proc = self.tmp / "proc-sys-fs"
        self.proc.mkdir()
        (self.proc / "protected_hardlinks").write_text("1\n")
        (self.proc / "protected_symlinks").write_text("1\n")
        if self.trigger is not None:
            self.gh.add_comment(ISSUE, "/bug-fix", app_id=None, user_type="User", cid=self.trigger)

    def config(self) -> Config:
        return Config(
            supabase_url="https://sb.example",
            supabase_key_secret_id="agent-fleet/prod/SUPABASE_SERVICE_ROLE_KEY",
            anthropic_key_secret_id="agent-fleet/prod/ANTHROPIC_API_KEY",
            model_id="claude-sonnet-5-5",
            projects_token_secret_id="agent-fleet/prod/GITHUB_PROJECTS_TOKEN",
            board_updates_enabled=True,
            board_disabled_reason=None,
            panel_base_url=self.panel,
            fix_loop_enabled=self.fix_loop,
        )

    def runtime(self) -> main.Runtime:
        url = self.remote_url or (self.remote.url if self.remote else None)
        return main.Runtime(
            github_session=self.gh,
            supabase_session=self.vruns,
            sandbox=self.sandbox,
            paths=self.paths,
            git_tools=self.spy.tools(),
            remote_url=lambda owner, repo: url,
            resolve_github=self.resolve or (lambda org, url, key: GitHubSession(_token(), PEM)),
            refresh=self.refresh or (lambda ctx, pem, app_id: ctx),
            sysctl_base=str(self.proc),
            heartbeat_interval=self.heartbeat_interval,
            fix_runner=self.fix_runner,
        )

    def payload(self) -> dict[str, Any]:
        params: dict[str, Any] = {"issue_number": ISSUE}
        if self.trigger is not None:
            params["trigger_comment_id"] = self.trigger
        return {
            "run_id": RUN,
            "repository_org": "o",
            "repository_name": "r",
            "base_branch": "main",
            "params": params if self.params is None else self.params,
        }


@pytest.fixture
def world(tmp_path, monkeypatch) -> Callable[..., World]:
    ReporterDB.instances = []
    ReporterDB.insert_fails = False
    monkeypatch.setattr(agent_reporter, "_SupabaseClient", ReporterDB)
    monkeypatch.setattr(main, "fetch_supabase_key", lambda secret_id: SB_KEY)
    made: list[World] = []

    def make(**kw: Any) -> World:
        w = World(tmp_path, **kw)
        made.append(w)
        monkeypatch.setattr(main, "load_config", w.config)
        monkeypatch.setattr(main, "default_runtime", w.runtime)

        def install(get_run, get_secrets, get_disposition=None, **_kw):
            w.backstop.update(run=get_run, secrets=get_secrets, disposition=get_disposition)

        monkeypatch.setattr(main, "install_termination_backstop", install)
        return w

    return make


def _invoke(w: World) -> tuple[dict[str, Any], list, ReporterDB]:
    async def go():
        return [c async for c in main.invoke(w.payload(), None)]

    chunks = asyncio.run(go())
    text = read_terminal_payload(chunks)
    assert text is not None, "no terminal chunk"
    return json.loads(text), chunks, ReporterDB.instances[-1]


def _sigterm(w: World) -> None:
    """The SIGTERM handler's body, with the getters main installed."""
    signal_backstop.handle_termination(
        w.backstop["run"], w.backstop["secrets"], w.backstop["disposition"], "SIGTERM", budget=5
    )


def _bodies(w: World) -> list[str]:
    return [
        c.json["body"] for c in w.gh.calls if c.method == "POST" and c.path.endswith("/comments")
    ]


def _kinds(body: str) -> list[str]:
    return [m.kind for m in parse_block(body)]


def _write_shapes(w: World) -> list[tuple[str, str]]:
    out = []
    for c in w.gh.writes():
        if c.path.endswith("/reactions"):
            out.append((c.method, f"reaction:{c.json['content']}"))
        elif c.method == "POST" and c.path.endswith("/comments"):
            out.append((c.method, "comment:" + ",".join(_kinds(c.json["body"])) or "comment"))
        else:
            out.append((c.method, c.path))
    return out


# ---------------------------------------------------------------------------
# TC-190-01, TC-190-02, S-188 QA gap 1: the Wave A happy path end to end
# ---------------------------------------------------------------------------


class TestWaveAHappyPath:
    def test_steps_in_order_and_each_emits_an_event(self, world):
        w = world()
        res, _, db = _invoke(w)
        assert res["status"] == "succeeded", res
        assert db.step_keys() == WAVE_A_STEPS
        by_step = db.events_by_step()
        for key in WAVE_A_STEPS:
            assert by_step.get(key), f"no run_event in step {key}"
        assert all(u["status"] == "succeeded" for u in db.step_updates())

    def test_fix_loop_disabled_disposes_and_ends_needs_review(self, world):
        w = world()
        res, _, db = _invoke(w)
        assert res == {
            "status": "succeeded",
            "outcome": "needs_review",
            "reason": "fix_loop_disabled",
            "summary": "fix loop not yet enabled",
        }
        final = db.final()
        assert (final["status"], final["outcome"]) == ("succeeded", "needs_review")
        assert final["result"] == {
            "summary": "fix loop not yet enabled",
            "reason": "fix_loop_disabled",
        }
        assert "fix" not in db.step_keys()

    def test_the_issue_side_is_claim_eyes_then_diagnosis_and_confused(self, world):
        w = world()
        _invoke(w)
        assert _write_shapes(w) == [
            ("POST", "comment:claim"),
            ("POST", "reaction:eyes"),
            ("POST", "comment:disposition"),
            ("POST", "reaction:confused"),
        ]
        assert [cid for cid, _ in w.gh.reactions] == [TRIGGER, TRIGGER]
        claim, diagnosis = _bodies(w)
        assert "fix loop not yet enabled" in diagnosis

    def test_the_claimer_gets_the_config_run_link_and_the_real_disposer(self, world, monkeypatch):
        import claim as claim_mod

        seen: dict[str, Any] = {}
        real = claim_mod.Claimer.__init__

        def spy(self, **kw):
            seen.update(kw)
            real(self, **kw)

        monkeypatch.setattr(claim_mod.Claimer, "__init__", spy)
        w = world()
        _invoke(w)
        from disposition import Disposer

        assert isinstance(seen["disposer"], Disposer)
        assert isinstance(seen["run_link"], RunLink) and seen["run_link"] == LINK
        assert seen["disposer"].run_link == LINK
        claim, diagnosis = _bodies(w)
        assert LINK in claim and LINK in diagnosis

    def test_a_manual_invoke_makes_no_reaction(self, world):
        w = world(trigger=None)
        res, _, _ = _invoke(w)
        assert res["outcome"] == "needs_review"
        assert _write_shapes(w) == [("POST", "comment:claim"), ("POST", "comment:disposition")]
        assert w.gh.reactions == []

    def test_no_panel_origin_names_the_run_id(self, world):
        w = world(panel=None)
        _invoke(w)
        claim, diagnosis = _bodies(w)
        assert f"`{RUN}`" in claim and f"`{RUN}`" in diagnosis

    def test_no_issue_change_before_the_repo_gate(self, world):
        # FR-5: everything before the claim comment is a read.
        w = world()
        _invoke(w)
        first_write = next(i for i, c in enumerate(w.gh.calls) if c in w.gh.writes())
        reads = w.gh.calls[:first_write]
        assert all(c.method == "GET" or c.path == "/graphql" for c in reads)
        assert any(c.argv[:2] == ("make", "install") for c in w.sandbox.calls)


class TestFixStep:
    def test_with_fix_loop_enabled_a_fix_step_runs_after_the_claim(self, world):
        calls: list[Any] = []

        def runner(ctx):
            calls.append(ctx)
            return main.dispose_needs_review(ctx, "fix_gave_up", "the model gave up", "tried x")

        w = world(fix_loop=True, fix_runner=runner)
        res, _, db = _invoke(w)
        assert db.step_keys() == [*WAVE_A_STEPS, "fix"]
        assert (res["outcome"], res["reason"]) == ("needs_review", "fix_gave_up")
        assert len(calls) == 1
        assert _kinds(_bodies(w)[-1]) == ["disposition"]

    def test_fix_loop_enabled_without_a_runner_disposes_and_names_it(self, world):
        w = world(fix_loop=True)
        res, _, db = _invoke(w)
        assert db.step_keys() == [*WAVE_A_STEPS, "fix"]
        assert res["outcome"] == "needs_review"
        assert res["reason"] == "fix_unavailable"
        assert "not available" in res["summary"]


# ---------------------------------------------------------------------------
# Refusals and TC-189-08 / TC-189-21 (the repo gate) through main
# ---------------------------------------------------------------------------


class TestRefusals:
    @pytest.mark.parametrize(
        ("setup", "code"),
        [
            (lambda w: w.gh.add_issue(ISSUE, pull_request=True), "pull_request"),
            (lambda w: w.gh.add_issue(ISSUE, state="closed"), "closed"),
            (lambda w: w.gh.add_closing_ref(ISSUE, 77), "linked_pr"),
        ],
        ids=["pull_request", "closed", "linked_pr"],
    )
    def test_a_refusal_ends_after_refuse_with_one_reply(self, world, setup, code):
        w = world()
        setup(w)
        res, _, db = _invoke(w)
        assert (res["status"], res["outcome"], res["reason"]) == (
            "succeeded",
            "not_applicable",
            code,
        )
        assert db.step_keys() == ["preflight", "refuse"]
        assert _write_shapes(w) == [("POST", "comment:refusal")]
        assert w.sandbox.calls == []

    def test_active_run_refuses(self, world):
        w = world()
        w.gh.add_comment(ISSUE, build("claim", OTHER) + "\nworking")
        w.vruns.statuses[OTHER] = "running"
        res, _, db = _invoke(w)
        assert res["reason"] == "active_run"
        assert db.step_keys() == ["preflight", "refuse"]

    def test_invalid_params_ends_after_preflight_with_the_reply(self, world):
        # TC-190-11 (1).
        w = world(params={"issue_number": ISSUE, "max_turns": 1})
        res, _, db = _invoke(w)
        assert (res["outcome"], res["reason"]) == ("not_applicable", "invalid_params")
        assert db.step_keys() == ["preflight"]
        assert _write_shapes(w) == [("POST", "comment:refusal")]
        assert "max_turns" in res["summary"]

    @pytest.mark.parametrize(
        ("fixture", "item"),
        [
            ("js-missing-typecheck", "typecheck"),
            ("py-no-developer-md", "developer.md"),
            ("py-no-install", "install"),
            ("js-no-scripts", "test"),
            ("js-format-dash", "format:check"),
            ("py-format-underscore", "format-check"),
            ("none", "package.json or Makefile"),
        ],
    )
    def test_every_repo_gate_failure_posts_one_marked_reply_and_nothing_else(
        self, world, fixture, item
    ):
        # TC-189-08 (AC-2(e), AC-4, D-92, D-112).
        w = world(fixture=fixture)
        res, _, db = _invoke(w)
        assert (res["status"], res["outcome"], res["reason"]) == (
            "succeeded",
            "not_applicable",
            "repo_gate",
        )
        assert db.step_keys() == ["preflight", "refuse", "checkout"]
        assert _write_shapes(w) == [("POST", "comment:refusal")]
        (body,) = _bodies(w)
        (marker,) = parse_block(body)
        assert (marker.kind, marker.reason) == ("refusal", "repo_gate")
        assert w.gh.reactions == []
        assert all("claim" not in _kinds(b) for b in _bodies(w))
        assert item in res["summary"]
        assert w.gh.projects_calls() == []
        # D-112: a Python repo without `make install` never runs an install.
        assert not any(c.argv[-1:] == ("install",) for c in w.sandbox.calls)

    def test_a_repo_gate_refusal_makes_zero_board_calls(self, world):
        # TC-189-21 (FR-32). DF-35 (where the board look-up sits) is still
        # undecided; spec v2.5 §8.10 and D-103 place it after the refusal
        # checks. Wave A has no board client (projects.py is S-199), so the
        # agent makes no Projects call on any path: zero reads, zero mutations.
        w = world(fixture="js-missing-typecheck")
        _invoke(w)
        assert w.gh.projects_calls() == []
        assert not any(
            "projectV2" in str(c.json) or "projectsV2" in str(c.json) for c in w.gh.calls
        )


# ---------------------------------------------------------------------------
# Faults (TC-190-11) and the S-185 residual
# ---------------------------------------------------------------------------


class TestFaults:
    def test_github_unavailable_during_refuse_is_failed_with_no_write(self, world):
        w = world()
        w.gh.faults["issue"] = [502, 502, 502]
        res, _, db = _invoke(w)
        assert (res["status"], res["error_code"]) == ("failed", "GITHUB_UNAVAILABLE")
        assert w.gh.writes() == []
        assert db.step_keys() == ["preflight", "refuse"]
        assert db.step_updates()[-1]["status"] == "failed"
        assert db.final()["error_code"] == "GITHUB_UNAVAILABLE"
        assert "GITHUB_UNAVAILABLE" in res["summary"]

    def test_a_422_on_the_claim_comment_is_rejected_with_no_disposition(self, world):
        w = world()
        w.gh.faults["comments_post"] = [422]
        res, _, db = _invoke(w)
        assert (res["status"], res["error_code"]) == ("failed", "GITHUB_REQUEST_REJECTED")
        assert [c.method for c in w.gh.writes()] == ["POST"]  # the refused claim POST only
        assert db.step_keys() == WAVE_A_STEPS
        assert "claim comment" in res["summary"]

    def test_supabase_unavailable_in_the_post_check_keeps_the_claim(self, world):
        w = world()
        w.gh.add_comment(ISSUE, build("claim", OTHER) + "\nold")
        w.vruns.statuses[OTHER] = "succeeded"
        reads = {"n": 0}
        real_get = w.vruns.get

        def get(url, **kw):
            reads["n"] += 1
            if reads["n"] == 2:  # the post-check's read
                w.vruns.fail = 503
            return real_get(url, **kw)

        w.vruns.get = get  # type: ignore[method-assign]
        res, _, _ = _invoke(w)
        assert res["error_code"] == "SUPABASE_UNAVAILABLE"
        assert _write_shapes(w) == [("POST", "comment:claim"), ("POST", "reaction:eyes")]

    def test_a_clone_failure_is_clone_failed_with_no_issue_write(self, world):
        w = world(remote_url="file:///nonexistent/remote.git")
        res, _, db = _invoke(w)
        assert (res["status"], res["error_code"]) == ("failed", "CLONE_FAILED")
        assert w.gh.writes() == []
        assert db.step_keys() == ["preflight", "refuse", "checkout"]

    def test_an_install_failure_is_install_failed_with_no_issue_write(self, world):
        w = world()
        w.sandbox.answers[("make", "install")] = result(2, "", "boom")
        res, _, _ = _invoke(w)
        assert (res["status"], res["error_code"]) == ("failed", "INSTALL_FAILED")
        assert w.gh.writes() == []

    def test_a_credential_failure_at_preflight_makes_no_github_call(self, world):
        def resolve(org, url, key):
            raise CredentialError("PEM_UNAVAILABLE", "denied")

        w = world(resolve=resolve)
        res, _, db = _invoke(w)
        assert (res["status"], res["error_code"]) == ("failed", "CREDENTIALS_UNAVAILABLE")
        assert w.gh.calls == []
        assert db.step_keys() == ["preflight"]

    def test_missing_issues_write_at_preflight_makes_no_github_call(self, world):
        w = world(resolve=lambda org, url, key: GitHubSession(_token({"contents": "write"}), PEM))
        res, _, _ = _invoke(w)
        assert (res["status"], res["error_code"]) == ("failed", "GITHUB_PERMISSION_MISSING")
        assert w.gh.calls == []

    @pytest.mark.parametrize(
        ("exc", "code"),
        [
            (
                PermissionMissing("the refreshed installation token lacks issues: write"),
                "GITHUB_PERMISSION_MISSING",
            ),
            (
                CredentialError("TOKEN_MINT_FAILED", "GitHub answered 500"),
                "CREDENTIALS_UNAVAILABLE",
            ),
        ],
        ids=["permission-missing", "mint-failed"],
    )
    def test_a_token_refresh_error_maps_by_its_error_code(self, world, exc, code):
        # S-185 residual: the caller of refresh_if_stale maps exc.error_code.
        calls = {"n": 0}

        def refresh(ctx, pem, app_id):
            calls["n"] += 1
            if calls["n"] >= 3:  # after the first refusal reads
                raise exc
            return ctx

        w = world(refresh=refresh)
        res, _, _ = _invoke(w)
        assert (res["status"], res["error_code"]) == ("failed", code)
        assert w.gh.writes() == []

    def test_a_refreshed_token_is_used_and_scrubbed(self, world):
        new = "ghs_" + "N" * 36

        def refresh(ctx, pem, app_id):
            assert pem == PEM and app_id == APP_ID
            return replace(ctx, token=new)

        w = world(refresh=refresh)
        w.sandbox.answers[("make", "test")] = result(1, f"leaked {new} and {TOKEN}", "")
        _invoke(w)
        assert all(c.headers["Authorization"] == f"Bearer {new}" for c in w.gh.calls)
        db = ReporterDB.instances[-1]
        dump = json.dumps(db.calls)
        assert (
            new not in dump and TOKEN not in dump and SB_KEY not in dump and "MIIfake" not in dump
        )


# ---------------------------------------------------------------------------
# TC-190-06, -07, -08: the backstop and the finally path, after confirmed ownership only
# ---------------------------------------------------------------------------


class TestOwnershipGate:
    def test_sigterm_during_checkout_makes_no_disposition_and_no_write(self, world):
        # TC-190-07.
        w = world()

        def install(call):
            _sigterm(w)
            raise Died()

        w.sandbox.answers[("make", "install")] = install
        with pytest.raises(Died):
            _invoke(w)
        assert w.gh.writes() == []
        final = ReporterDB.instances[-1].final()
        assert (final["status"], final["error_code"]) == ("failed", "SIGNAL_TERMINATION")
        assert "ownership was not confirmed" in final["error_message"]

    def test_sigterm_after_the_claim_is_confirmed_disposes_then_fails(self, world):
        # TC-190-06 (D-81): the handler disposes before fail().
        w = world()
        state = {"comment_gets": 0, "fired": False}

        def hook(call: Call) -> None:
            claimed = any("claim" in s for _, s in _write_shapes(w))
            if not (claimed and call.method == "GET" and call.path.endswith("/comments")):
                return
            state["comment_gets"] += 1
            if state["comment_gets"] == 2 and not state["fired"]:  # main's own disposition
                state["fired"] = True
                _sigterm(w)
                raise Died()

        w.gh.hook = hook
        with pytest.raises(Died):
            _invoke(w)
        shapes = _write_shapes(w)
        assert shapes.count(("POST", "comment:disposition")) == 1
        assert ("POST", "reaction:confused") in shapes
        final = ReporterDB.instances[-1].final()
        assert (final["status"], final["error_code"]) == ("failed", "SIGNAL_TERMINATION")
        assert "Disposition posted before stopping" in final["error_message"]
        # The disposition comment landed before the terminal report.
        diagnosis = next(b for b in _bodies(w) if _kinds(b) == ["disposition"])
        assert "termination signal" in diagnosis

    def test_an_exception_before_ownership_keeps_the_claim_and_disposes_nothing(self, world):
        # TC-190-08 (1).
        w = world()
        w.gh.add_comment(ISSUE, build("claim", OTHER) + "\nold")
        w.vruns.statuses[OTHER] = "succeeded"
        reads = {"n": 0}
        real_get = w.vruns.get

        def get(url, **kw):
            reads["n"] += 1
            if reads["n"] == 2:
                raise RuntimeError("v_runs client blew up " + SB_KEY)
            return real_get(url, **kw)

        w.vruns.get = get  # type: ignore[method-assign]
        res, _, db = _invoke(w)
        assert (res["status"], res["error_code"]) == ("failed", "UNHANDLED_ERROR")
        assert _write_shapes(w) == [("POST", "comment:claim"), ("POST", "reaction:eyes")]
        assert SB_KEY not in json.dumps(res) and SB_KEY not in json.dumps(db.calls)
        assert db.step_updates()[-1]["status"] == "failed"

    def test_an_exception_after_ownership_disposes_in_the_finally_path(self, world):
        # TC-190-08 (2).
        def runner(ctx):
            raise RuntimeError("the fix step exploded")

        w = world(fix_loop=True, fix_runner=runner)
        res, _, db = _invoke(w)
        assert (res["status"], res["error_code"]) == ("failed", "UNHANDLED_ERROR")
        assert _write_shapes(w) == [
            ("POST", "comment:claim"),
            ("POST", "reaction:eyes"),
            ("POST", "comment:disposition"),
            ("POST", "reaction:confused"),
        ]
        assert "UNHANDLED_ERROR" in _bodies(w)[-1]
        assert db.final()["error_code"] == "UNHANDLED_ERROR"

    def test_the_finally_path_never_disposes_twice(self, world):
        def runner(ctx):
            main.dispose_needs_review(ctx, "fix_gave_up", "gave up", "tried")
            raise RuntimeError("after the disposition")

        w = world(fix_loop=True, fix_runner=runner)
        res, _, _ = _invoke(w)
        assert res["error_code"] == "UNHANDLED_ERROR"
        assert [s for s in _write_shapes(w) if s == ("POST", "comment:disposition")] == [
            ("POST", "comment:disposition")
        ]

    def test_the_backstop_is_installed_with_a_disposition_getter(self, world):
        w = world()
        _invoke(w)
        assert set(w.backstop) == {"run", "secrets", "disposition"}
        assert SB_KEY in w.backstop["secrets"]()
        assert TOKEN in w.backstop["secrets"]()


# ---------------------------------------------------------------------------
# The reporter: a flush failure never masks the outcome (11.2, TC-190-08 (3))
# ---------------------------------------------------------------------------


class TestReporter:
    def test_a_failed_event_flush_keeps_the_outcome(self, world):
        ReporterDB.insert_fails = True
        w = world()
        res, _, db = _invoke(w)
        assert res["outcome"] == "needs_review"
        assert (db.final()["status"], db.final()["outcome"]) == ("succeeded", "needs_review")

    def test_a_raising_reporter_keeps_the_terminal_chunk(self, world, monkeypatch):
        def boom(self, table, rows):
            raise OSError("supabase unreachable")

        monkeypatch.setattr(ReporterDB, "insert", boom)
        w = world()
        res, _, _ = _invoke(w)
        assert (res["status"], res["outcome"]) == ("succeeded", "needs_review")

    def test_heartbeats_flow_during_a_long_step_and_the_result_is_last(self, world):
        w = world(heartbeat_interval=0.02)

        def slow(call):
            time.sleep(0.15)
            return result(0, "ok")

        w.sandbox.answers[("make", "install")] = slow
        res, chunks, _ = _invoke(w)
        assert res["outcome"] == "needs_review"
        assert any(is_heartbeat_chunk(c) for c in chunks)
        assert is_terminal_chunk(chunks[-1])
        assert sum(is_terminal_chunk(c) for c in chunks) == 1


# ---------------------------------------------------------------------------
# TC-190-09: metrics; the sysctl preflight
# ---------------------------------------------------------------------------


class TestMetrics:
    def test_issue_number_and_step_timings(self, world):
        w = world()
        _, _, db = _invoke(w)
        metrics = db.final()["metrics"]
        assert metrics["issue_number"] == ISSUE
        timings = metrics["step_timings_ms"]
        assert list(timings) == WAVE_A_STEPS
        assert all(
            isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in timings.values()
        )
        assert set(metrics["gates_base"]) >= {"test", "lint", "typecheck"}

    def test_a_refusal_records_metrics_too(self, world):
        w = world()
        w.gh.add_issue(ISSUE, state="closed")
        _, _, db = _invoke(w)
        metrics = db.final()["metrics"]
        assert metrics["issue_number"] == ISSUE
        assert list(metrics["step_timings_ms"]) == ["preflight", "refuse"]

    def test_a_fault_records_metrics_too(self, world):
        w = world()
        w.gh.faults["issue"] = [502, 502, 502]
        _, _, db = _invoke(w)
        assert db.final()["metrics"]["issue_number"] == ISSUE

    def test_invalid_issue_number_records_none(self, world):
        w = world(params={"issue_number": "x"})
        _, _, db = _invoke(w)
        assert db.final()["metrics"]["issue_number"] is None


class TestSysctlPreflight:
    def test_link_protection_is_a_preflight_event(self, world):
        # S-189 QA-189-01, wired into the run's preflight step.
        w = world()
        (w.proc / "protected_hardlinks").write_text("0\n")
        _, _, db = _invoke(w)
        pre = db.events_by_step()["preflight"]
        assert "preflight: fs.protected_hardlinks=0 fs.protected_symlinks=1" in pre
        event = next(e for e in db.events() if e["message"].startswith("preflight: fs."))
        assert event["level"] == "warn"
        assert event["data"] == {"protected_hardlinks": "0", "protected_symlinks": "1"}
        assert not any(
            m.startswith("preflight: fs.") for m in db.events_by_step().get("checkout", [])
        )

    def test_expected_values_log_at_info(self, world):
        w = world()
        _, _, db = _invoke(w)
        event = next(e for e in db.events() if e["message"].startswith("preflight: fs."))
        assert event["level"] == "info"


# ---------------------------------------------------------------------------
# TC-190-13: one shot, one issue
# ---------------------------------------------------------------------------


def _paths_scenarios() -> dict[str, Callable[[World], None]]:
    def lost(w: World) -> None:
        state = {"done": False}

        def hook(call: Call) -> None:
            if state["done"] or not (call.method == "POST" and call.path.endswith("/comments")):
                return
            if _kinds(call.json["body"]) == ["claim"]:
                state["done"] = True
                # Another run's claim, older than ours.
                w.gh.add_comment(ISSUE, build("claim", OTHER) + "\nfirst", cid=1)
                w.gh.comments[ISSUE].sort(key=lambda c: c["id"])
                w.vruns.statuses[OTHER] = "running"

        w.gh.hook = hook

    return {
        "happy": lambda w: None,
        "closed": lambda w: w.gh.add_issue(ISSUE, state="closed"),
        "linked_pr": lambda w: w.gh.add_closing_ref(ISSUE, 77),
        "lost_race": lost,
        "fault": lambda w: w.gh.faults.__setitem__("issue", [502, 502, 502]),
    }


@pytest.mark.parametrize("scenario", sorted(_paths_scenarios()))
def test_every_github_call_is_scoped_to_the_one_issue(world, scenario):
    w = world()
    w.gh.add_issue(ISSUE + 1)  # another issue the run must never touch
    w.gh.add_comment(ISSUE + 1, "unrelated", app_id=None, user_type="User", cid=555)
    _paths_scenarios()[scenario](w)
    res, _, _ = _invoke(w)
    if scenario == "lost_race":
        assert (res["outcome"], res["reason"]) == ("not_applicable", "active_run")
    on_issue = {c["id"] for c in w.gh.comments.get(ISSUE, [])} | set(w.gh.deleted) | {TRIGGER}
    import re as _re

    for call in w.gh.calls:
        assert "/search" not in call.path
        assert call.path != "/repos/o/r/issues", "an issue listing"
        m = _re.match(r"^/repos/o/r/issues/(\d+)(/.*)?$", call.path)
        if m:
            assert int(m.group(1)) == ISSUE, call.path
        m = _re.match(r"^/repos/o/r/issues/comments/(\d+)", call.path)
        if m:
            assert int(m.group(1)) in on_issue, call.path
        if call.path == "/graphql":
            assert (call.json or {}).get("variables", {}).get("number") == ISSUE
    assert 555 not in [cid for cid, _ in w.gh.reactions]
    assert not any(c.path.endswith(f"/issues/{ISSUE + 1}/comments") for c in w.gh.calls)


# ---------------------------------------------------------------------------
# Edges of the ownership gate and the token source
# ---------------------------------------------------------------------------


def _fault_disposition_post(w: World, status: int = 502) -> None:
    """From the post-check's comment listing on, the next comment POST fails."""
    state = {"gets": 0}

    def hook(call: Call) -> None:
        claimed = any("claim" in s for _, s in _write_shapes(w))
        if claimed and call.method == "GET" and call.path.endswith("/comments"):
            state["gets"] += 1
            if state["gets"] == 1:  # the post-check
                w.gh.faults["comments_post"] = [status]

    w.gh.hook = hook


class TestEdges:
    def test_a_refresh_error_a_best_effort_reply_swallowed_still_fails_the_run(self, world):
        calls = {"n": 0}

        def refresh(ctx, pem, app_id):
            calls["n"] += 1
            if calls["n"] >= 2:  # GET issue works; the refusal reply's POST doesn't
                raise PermissionMissing("the refreshed installation token lacks issues: write")
            return ctx

        w = world(refresh=refresh)
        w.gh.add_issue(ISSUE, state="closed")
        res, _, db = _invoke(w)
        assert (res["status"], res["error_code"]) == ("failed", "GITHUB_PERMISSION_MISSING")
        assert w.gh.writes() == []
        assert db.step_updates()[-1]["status"] == "failed"

    def test_a_fault_on_the_disposition_post_is_failed_and_never_retried(self, world):
        w = world()
        _fault_disposition_post(w)
        res, _, _ = _invoke(w)
        assert (res["status"], res["error_code"]) == ("failed", "GITHUB_UNAVAILABLE")
        posts = [c for c in w.gh.calls if c.method == "POST" and c.path.endswith("/comments")]
        assert len(posts) == 2  # the claim, and one disposition attempt

    def test_a_failing_finally_disposition_keeps_the_original_fault(self, world):
        def runner(ctx):
            raise RuntimeError("the fix step exploded")

        w = world(fix_loop=True, fix_runner=runner)
        _fault_disposition_post(w)
        res, _, db = _invoke(w)
        assert res["error_code"] == "UNHANDLED_ERROR"
        assert any("disposition after the fault failed" in m for m in db.messages())

    def test_a_fix_runner_without_a_result_still_disposes(self, world):
        w = world(fix_loop=True, fix_runner=lambda ctx: None)
        res, _, _ = _invoke(w)
        assert (res["outcome"], res["reason"]) == ("needs_review", "fix_unavailable")
        assert _kinds(_bodies(w)[-1]) == ["disposition"]

    @pytest.mark.parametrize("key", ["repository_org", "repository_name", "base_branch"])
    def test_a_payload_without_a_repository_field_is_invalid_payload(self, world, key):
        w = world()
        payload = w.payload()
        del payload[key]
        w.payload = lambda: payload  # type: ignore[method-assign]
        res, _, db = _invoke(w)
        assert (res["status"], res["error_code"]) == ("failed", "INVALID_PAYLOAD")
        assert key in res["summary"]
        assert w.gh.calls == []
        assert db.step_keys() == ["preflight"]


class TestTokenSource:
    def _source(self, refresh, ctx=None):
        from scrubber import SecretSet

        secrets = SecretSet()
        return main.TokenSource(GitHubSession(ctx or _token(), PEM), refresh, secrets), secrets

    def test_a_refresh_error_is_kept_and_raised_on_every_later_use(self):
        exc = PermissionMissing("lost issues: write")
        calls = {"n": 0}

        def refresh(ctx, pem, app_id):
            calls["n"] += 1
            raise exc

        source, _ = self._source(refresh)
        for _ in range(2):
            with pytest.raises(PermissionMissing):
                source()
        assert calls["n"] == 1
        assert source.failure is exc

    def test_a_context_without_an_app_id_fails_closed(self):
        ctx = TokenContext(token=TOKEN, issued_at=0.0, installation_id=1, permissions={})
        source, _ = self._source(lambda c, p, a: c, ctx)
        with pytest.raises(CredentialError) as info:
            source()
        assert info.value.error_code == "CREDENTIALS_UNAVAILABLE"

    def test_a_new_token_is_registered_with_the_scrubber(self):
        new = "ghs_" + "Z" * 36
        source, secrets = self._source(lambda c, p, a: replace(c, token=new))
        assert source() == new
        assert new in secrets.values()


# ---------------------------------------------------------------------------
# qa-engineer, S-190 completion gate: the ownership gate at every step
# boundary, payload shapes, the stream closing mid-run, secrets in the logs
# ---------------------------------------------------------------------------


def _die(w: World) -> None:
    _sigterm(w)
    raise Died()


def _sigterm_in_step(name: str) -> Callable[[World, pytest.MonkeyPatch], None]:
    def arm(w: World, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(main, f"_{name}", lambda ctx: _die(w))

    return arm


def _sigterm_on_the_claim_post(w: World, monkeypatch: pytest.MonkeyPatch) -> None:
    # The claim comment landed; the post-check has not run yet.
    def hook(call: Call) -> None:
        if call.method == "POST" and call.path.endswith("/comments"):
            _die(w)

    w.gh.hook = hook


def _sigterm_after_the_disposition(w: World, monkeypatch: pytest.MonkeyPatch) -> None:
    # Wave A: the claim step disposed; SIGTERM before the terminal report.
    monkeypatch.setattr(main, "_report", lambda ctx, result: _die(w))


# (arm, fix_loop, the writes that must exist, ownership confirmed)
_BOUNDARIES: dict[str, tuple[Callable[..., None], bool, list[str], bool]] = {
    "preflight": (_sigterm_in_step("preflight"), False, [], False),
    "refuse": (_sigterm_in_step("refuse"), False, [], False),
    "checkout": (_sigterm_in_step("checkout"), False, [], False),
    "claim_posted_unconfirmed": (_sigterm_on_the_claim_post, False, ["comment:claim"], False),
    "fix_start": (
        _sigterm_in_step("fix"),
        True,
        ["comment:claim", "reaction:eyes", "comment:disposition", "reaction:confused"],
        True,
    ),
    "after_disposition": (
        _sigterm_after_the_disposition,
        False,
        ["comment:claim", "reaction:eyes", "comment:disposition", "reaction:confused"],
        True,
    ),
}


class TestQAOwnershipAtEveryBoundary:
    """D-81: nothing is disposed before the post-check confirms ownership, and
    exactly one disposition exists after it, whoever posts it (the run or the
    SIGTERM backstop)."""

    @pytest.mark.parametrize("where", sorted(_BOUNDARIES))
    def test_sigterm_at_a_step_boundary(self, world, monkeypatch, where):
        arm, fix_loop, expected, owned = _BOUNDARIES[where]
        w = world(fix_loop=fix_loop)
        arm(w, monkeypatch)
        with pytest.raises(Died):
            _invoke(w)
        assert [s for _, s in _write_shapes(w)] == expected
        final = ReporterDB.instances[-1].final()
        assert (final["status"], final["error_code"]) == ("failed", "SIGNAL_TERMINATION")
        if owned:
            assert "ownership was not confirmed" not in final["error_message"]
        else:
            assert "ownership was not confirmed" in final["error_message"]


def _with_payload(w: World, **changes: Any) -> World:
    payload = w.payload()
    for key, value in changes.items():
        if value is ...:
            payload.pop(key, None)
        else:
            payload[key] = value
    w.payload = lambda: payload  # type: ignore[method-assign]
    return w


class TestQAPayloadShapes:
    @pytest.mark.parametrize(
        ("changes", "says"),
        [
            ({"repository_org": 123}, "repository_org has the wrong type"),
            ({"repository_name": None}, "repository_name missing"),
            ({"base_branch": ["main"]}, "base_branch has the wrong type"),
            ({"repository_org": "   "}, "repository_org missing"),
            ({"repository_name": ...}, "repository_name missing"),
            ({"base_branch": {"name": "main"}}, "base_branch has the wrong type"),
        ],
    )
    def test_a_wrongly_typed_repository_field_is_invalid_payload(self, world, changes, says):
        w = _with_payload(world(), **changes)
        res, _, db = _invoke(w)
        assert (res["status"], res["error_code"]) == ("failed", "INVALID_PAYLOAD")
        assert says in res["summary"]
        if "wrong type" in says:
            # QA gap 5: a field that is present but not a string is not "missing".
            assert "missing" not in res["summary"]
        assert w.gh.calls == []
        assert db.step_keys() == ["preflight"]

    def test_a_missing_and_a_wrongly_typed_field_are_both_named(self, world):
        w = _with_payload(world(), repository_org=7, base_branch=...)
        res, _, _ = _invoke(w)
        assert res["error_code"] == "INVALID_PAYLOAD"
        assert "base_branch missing" in res["summary"]
        assert "repository_org has the wrong type" in res["summary"]

    @pytest.mark.parametrize("params", [..., [ISSUE], "12", {"trigger_comment_id": TRIGGER}])
    def test_params_without_a_usable_issue_refuse_with_no_github_write(self, world, params):
        w = _with_payload(world(), params=params)
        res, _, _ = _invoke(w)
        assert (res["status"], res["outcome"], res["reason"]) == (
            "succeeded",
            "not_applicable",
            "invalid_params",
        )
        assert w.gh.writes() == []

    def test_a_top_level_issue_number_is_never_read_in_place_of_params(self, world):
        w = _with_payload(world(), params={"trigger_comment_id": TRIGGER}, issue_number=ISSUE)
        res, _, db = _invoke(w)
        assert res["reason"] == "invalid_params"
        assert "issue_number" in res["summary"]
        assert w.gh.writes() == []
        assert db.final()["metrics"]["issue_number"] is None

    def test_an_extra_top_level_field_is_ignored(self, world):
        w = _with_payload(world(), extra="x")
        res, _, _ = _invoke(w)
        assert (res["status"], res["outcome"]) == ("succeeded", "needs_review")

    @pytest.mark.parametrize("value", ["true", 1, "1", {"x": 1}])
    def test_a_non_boolean_probe_flag_is_a_normal_run(self, world, value):
        w = _with_payload(world(), __probe=value)
        res, _, db = _invoke(w)
        assert res["outcome"] == "needs_review"
        assert db.step_keys() == WAVE_A_STEPS

    def test_a_prompt_wrapped_probe_is_refused_with_no_github_call(self, world, monkeypatch):
        monkeypatch.delenv("ALLOW_PROBE", raising=False)
        w = world()
        inner = {**w.payload(), "__probe": True}
        w.payload = lambda: {"prompt": json.dumps(inner)}  # type: ignore[method-assign]
        res, _, db = _invoke(w)
        assert (res["status"], res["error_code"]) == ("failed", "PROBE_REFUSED")
        assert w.gh.calls == []
        assert db.step_keys() == []
        assert db.final()["error_code"] == "PROBE_REFUSED"

    @pytest.mark.parametrize("run_id", ["not-a-uuid", "0b9a2f4e", f"{RUN}x", f" {RUN}/.."])
    def test_a_non_uuid_run_id_is_invalid_payload(self, world, run_id):
        """QA-190-02: failed/INVALID_PAYLOAD at preflight, with no GitHub call."""
        w = _with_payload(world(), run_id=run_id)
        res, _, db = _invoke(w)
        assert w.gh.calls == []
        assert (res["status"], res["error_code"]) == ("failed", "INVALID_PAYLOAD")
        assert "run_id is not a UUID" in res["summary"]
        assert run_id.strip() not in res["summary"]
        assert db.step_keys() == ["preflight"]
        final = db.final()
        assert (final["status"], final["error_code"]) == ("failed", "INVALID_PAYLOAD")
        assert "outcome" not in final


def _slow_install(w: World) -> None:
    def slow(call):
        time.sleep(0.3)
        return result(0, "ok")

    w.sandbox.answers[("make", "install")] = slow


async def _close_after_first_heartbeat(w: World) -> None:
    agen = main.invoke(w.payload(), None)
    first = await agen.__anext__()
    assert is_heartbeat_chunk(first)
    await agen.aclose()


async def _cancel_the_consumer(w: World) -> None:
    async def consume() -> list:
        return [c async for c in main.invoke(w.payload(), None)]

    task = asyncio.ensure_future(consume())
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


class TestQAStreamClosedMidRun:
    """The panel resolves ``invokeAgentRuntime`` once AgentCore accepts the call
    and the webhook path aborts it on a timeout, so the response stream can close
    while the steps run. ``asyncio.run`` joins the worker before these asserts."""

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "QA-190-01: closing or cancelling the invoke stream mid-run raises "
            "GeneratorExit/CancelledError through `with run:`; RunReporter.__exit__ "
            "then writes failed with error_code 'GeneratorExit'/'CancelledError' "
            "(outside the closed set, counts toward the breaker) and an unscrubbed "
            "traceback to run_events, while the worker goes on to claim and dispose"
        ),
    )
    @pytest.mark.parametrize("close", [_close_after_first_heartbeat, _cancel_the_consumer])
    def test_the_terminal_row_stays_in_the_closed_set(self, world, close):
        w = world(heartbeat_interval=0.02)
        _slow_install(w)
        asyncio.run(close(w))
        db = ReporterDB.instances[-1]
        final = db.final()
        assert final["status"] == "succeeded" or final["error_code"] in outcomes.ERROR_CODES
        assert not any("Traceback" in m for m in db.messages())


class TestQASecretsInLogs:
    """capture_logging=False: the standard logging stream never reaches
    run_events, but it reaches CloudWatch, so it is scrubbed too."""

    @pytest.mark.parametrize("scenario", ["happy", "github_fault", "secret_bearing_exception"])
    def test_no_secret_in_logs_events_result_or_metrics(self, world, caplog, scenario):
        w = world(fix_loop=scenario == "secret_bearing_exception")
        if scenario == "github_fault":
            w.gh.faults["issue"] = [502, 502, 502]
        if scenario == "secret_bearing_exception":

            def runner(ctx):
                raise RuntimeError(f"boom {TOKEN} {SB_KEY} {PEM}")

            w.fix_runner = runner
        with caplog.at_level("DEBUG"):
            res, chunks, db = _invoke(w)
        emitted = caplog.text + json.dumps(chunks) + json.dumps(db.calls, default=str)
        for secret in (TOKEN, SB_KEY, PEM, "MIIfake"):
            assert secret not in emitted
        assert res["status"] in ("succeeded", "failed")
        metrics = db.final()["metrics"]
        assert set(metrics) <= {"issue_number", "step_timings_ms", "gates_base"}
        for gate in metrics.get("gates_base", {}).values():
            assert set(gate) == {"pass", "exit_code"}


class TestRunLinkHostIsChecked:
    """DF-190-12: every comment the run posts checks its link against the
    configured ``PANEL_BASE_URL``, not only against the origin the link carries."""

    OFF_HOST = "https://other.example"

    def _off_host(self, monkeypatch) -> None:
        monkeypatch.setattr(
            Config, "run_link", lambda self, rid: RunLink(TestRunLinkHostIsChecked.OFF_HOST, rid)
        )

    def test_a_link_on_another_host_never_reaches_the_claim_or_the_diagnosis(
        self, world, monkeypatch
    ):
        self._off_host(monkeypatch)
        w = world()
        res, _, _ = _invoke(w)
        assert res["outcome"] == "needs_review"
        bodies = _bodies(w)
        assert len(bodies) == 2  # the claim and the diagnosis
        for body in bodies:
            assert self.OFF_HOST not in body
            assert f"`{RUN}`" in body

    def test_a_link_on_another_host_never_reaches_a_refusal_reply(self, world, monkeypatch):
        self._off_host(monkeypatch)
        w = world()
        w.gh.add_issue(ISSUE, state="closed")
        res, _, _ = _invoke(w)
        assert res["reason"] == "closed"
        (body,) = _bodies(w)
        assert self.OFF_HOST not in body
        assert body.endswith(f"`{RUN}`")

    def test_the_configured_host_still_links(self, world):
        w = world()
        _invoke(w)
        assert all(LINK in body for body in _bodies(w))
