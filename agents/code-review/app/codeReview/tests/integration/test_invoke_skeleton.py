"""
S-204 AC3/AC4/AC7 — ``main.invoke`` skeleton against a reporter sink.

TC-204-11: invalid params end ``failed``/``INVALID_PARAMS`` with zero GitHub
calls. TC-204-12 (invoke half): the clock invariant runs before ``started``.
TC-204-18: valid params start the run and open ``load_pr``. Since S-213 the
step runs the real pipeline, so here (credential resolution refused by the
sink) it ends ``failed``/``INTERNAL_ERROR`` with no GitHub call and no failure
comment (no token, so no client). The full pipeline is covered by
``test_pipeline_e2e.py``.

The sink replaces only the vendored reporter's HTTP layer
(``agent_reporter._SupabaseClient``), so the real ``RunReporter`` lifecycle runs.
``requests`` transport is stubbed to record (and refuse) every call.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field

import pytest
import requests

import agent_reporter
import main
from heartbeat import read_terminal_payload

RUN_ID = "3f2b8c1e-5d4a-4f6b-9a7c-2e1d0b9a8c7f"
SUPABASE_KEY = "svc-key-sentinel-5b1e"


@dataclass
class Sink:
    """Ordered record of reporter writes, GitHub attempts and startup checks."""

    events: list[tuple] = field(default_factory=list)
    github_calls: list[tuple] = field(default_factory=list)
    credential_calls: list[str] = field(default_factory=list)
    backstops: int = 0

    def writes(self, table: str) -> list[tuple]:
        return [e for e in self.events if e[0] in {"POST", "PATCH"} and e[1] == table]

    def run_patches(self) -> list[dict]:
        return [e[2] for e in self.writes("runs")]

    def step_inserts(self) -> list[dict]:
        return [row for e in self.writes("run_steps") if e[0] == "POST" for row in e[2]]

    def messages(self) -> list[str]:
        return [row["message"] for e in self.writes("run_events") for row in e[2]]


@pytest.fixture
def sink(monkeypatch) -> Sink:
    s = Sink()

    def _request(self, method, path, payload):
        table = path.lstrip("/").split("?", 1)[0]
        s.events.append((method, table, payload))
        return True

    def _update_expect_rows(self, table, filt, patch):
        s.events.append(("PATCH", table, patch))
        return 1

    monkeypatch.setattr(agent_reporter._SupabaseClient, "_request", _request)
    monkeypatch.setattr(agent_reporter._SupabaseClient, "update_expect_rows", _update_expect_rows)

    def _send(self, request, **kwargs):
        s.github_calls.append((request.method, request.url))
        raise AssertionError(f"unexpected HTTP call {request.method} {request.url}")

    monkeypatch.setattr(requests.Session, "send", _send)

    def _resolve(org, *a, **k):
        s.credential_calls.append(org)
        raise AssertionError("resolve_github_credentials must not be called")

    monkeypatch.setattr(main, "resolve_github_credentials", _resolve)
    monkeypatch.setattr(main, "fetch_supabase_key", lambda *a, **k: SUPABASE_KEY)

    def _backstop(get_run, get_secrets):
        s.backstops += 1

    monkeypatch.setattr(main, "install_termination_backstop", _backstop)

    real_invariant = main.assert_clock_invariant

    def _invariant(**kwargs):
        s.events.append(("CLOCK", "assert_clock_invariant", kwargs))
        return real_invariant(**kwargs)

    monkeypatch.setattr(main, "assert_clock_invariant", _invariant)

    for key, value in {
        "SUPABASE_URL": "http://supabase.local",
        "SUPABASE_KEY_SECRET_ID": "agent-fleet/test/key",
        "MODEL_ID": "test-model",
        "PANEL_BASE_URL": "https://panel.local",
    }.items():
        monkeypatch.setenv(key, value)
    return s


def _drive(raw: object) -> dict:
    async def _drain():
        return [item async for item in main.invoke(raw, None)]

    chunks = asyncio.run(_drain())
    text = read_terminal_payload(chunks)
    assert text is not None, f"no terminal chunk in {chunks!r}"
    return json.loads(text)


def _payload(params: object = None, **overrides: object) -> dict:
    p: dict = {
        "run_id": RUN_ID,
        "repository_org": "llipe",
        "repository_name": "dev-tasks-agent-fleet",
        "params": {"pr_number": 7} if params is None else params,
    }
    p.update(overrides)
    return p


def _assert_no_github(sink: Sink) -> None:
    assert sink.github_calls == []
    assert sink.credential_calls == []


# ---------------------------------------------------------------------------
# TC-204-11 — invalid params
# ---------------------------------------------------------------------------

INVALID_PARAMS = [
    {"pr_number": 0},
    {"pr_number": True},
    {"pr_number": "7"},
    {"pr_number": 1, "max_context_tokens": 19999},
    {"pr_number": 1, "reasoning_effort": "max"},
    {"pr_number": 1, "foo": 1},
    {},
    [],
]


@pytest.mark.parametrize("params", INVALID_PARAMS, ids=repr)
def test_invalid_params_fail_invalid_params_with_no_github_call(sink, params):
    result = _drive(_payload(params))

    assert result["status"] == "failed"
    assert result["error_code"] == "INVALID_PARAMS"
    assert result["comment_url"] is None
    _assert_no_github(sink)

    terminal = sink.run_patches()[-1]
    assert terminal["status"] == "failed"
    assert terminal["error_code"] == "INVALID_PARAMS"
    assert sink.step_inserts() == [], "no step may open for invalid params"


def test_invalid_params_message_names_the_field(sink):
    _drive(_payload({"pr_number": 1, "max_suggestions": 21}))
    assert "params.max_suggestions" in sink.run_patches()[-1]["error_message"]


def test_params_absent_is_invalid(sink):
    raw = _payload()
    del raw["params"]
    assert _drive(raw)["error_code"] == "INVALID_PARAMS"
    _assert_no_github(sink)


def test_wrapped_invalid_params_still_reported(sink):
    raw = {"prompt": json.dumps({"prompt": json.dumps(_payload({"pr_number": -1}))})}
    assert _drive(raw)["error_code"] == "INVALID_PARAMS"
    assert sink.run_patches()[-1]["error_code"] == "INVALID_PARAMS"


@pytest.mark.parametrize(
    "raw",
    [
        {"prompt": "not json"},
        {"repository_org": "o", "repository_name": "r", "params": {"pr_number": 1}},
        _payload(run_id="r-1"),
        _payload(run_id=5),
        "a string payload",
    ],
    ids=["wrapper-only", "no-run-id", "run-id-not-uuid", "run-id-int", "str"],
)
def test_unreportable_payload_writes_nothing(sink, raw):
    """Without a valid run_id there is no run row to update: terminal chunk only."""
    result = _drive(raw)
    assert result["error_code"] == "INVALID_PARAMS"
    assert [e for e in sink.events if e[0] != "CLOCK"] == []
    _assert_no_github(sink)


@pytest.mark.parametrize("field", ["repository_org", "repository_name"])
def test_bad_repository_field_with_valid_run_id_is_reported(sink, field):
    result = _drive(_payload(**{field: 5}))
    assert result["error_code"] == "INVALID_PARAMS"
    terminal = sink.run_patches()[-1]
    assert terminal["error_code"] == "INVALID_PARAMS"
    assert field in terminal["error_message"]
    assert sink.step_inserts() == []
    _assert_no_github(sink)


# ---------------------------------------------------------------------------
# TC-204-12 — clock invariant runs before `started`
# ---------------------------------------------------------------------------


def test_clock_invariant_runs_before_started(sink):
    _drive(_payload())
    kinds = [(e[0], e[1]) for e in sink.events]
    clock_at = kinds.index(("CLOCK", "assert_clock_invariant"))
    started_at = next(
        i for i, e in enumerate(sink.events) if e[1] == "runs" and e[2].get("status") == "running"
    )
    assert clock_at < started_at


def test_clock_invariant_failure_refuses_to_start(sink, monkeypatch):

    def _broken(**kwargs):
        raise main.ClockConsistencyError("run_timeout_seconds (900) must be <= 600")

    monkeypatch.setattr(main, "assert_clock_invariant", _broken)
    result = _drive(_payload())
    assert result["status"] == "failed"
    assert result["error_code"] == "INTERNAL_ERROR"
    assert sink.events == []
    _assert_no_github(sink)


# ---------------------------------------------------------------------------
# TC-204-18 — skeleton invoke with valid params
# ---------------------------------------------------------------------------


def test_valid_params_open_load_pr_and_resolve_credentials(sink):
    result = _drive(_payload())

    assert result == {
        "status": "failed",
        "outcome": "not_applicable",
        "verdict": None,
        "comment_url": None,
        "error_code": "INTERNAL_ERROR",
    }

    patches = sink.run_patches()
    assert patches[0]["status"] == "running"
    assert patches[-1]["status"] == "failed"
    assert patches[-1]["error_code"] == "INTERNAL_ERROR"
    assert patches[-1]["error_message"].startswith("INTERNAL_ERROR in step load_pr:")

    steps = sink.step_inserts()
    assert [s["key"] for s in steps] == ["load_pr"]
    step_patches = [e[2] for e in sink.writes("run_steps") if e[0] == "PATCH"]
    assert step_patches and step_patches[-1]["status"] == "failed"

    assert sink.backstops == 1
    assert sink.credential_calls == ["llipe"]
    assert sink.github_calls == []
    assert any("failure comment not posted" in m for m in sink.messages())


def test_pipeline_deps_resolve_the_installation_token(monkeypatch):
    """main.pipeline_deps mints the token through resolve_github_credentials."""
    from config import Settings
    from credentials import TokenContext

    seen = []

    def _resolve(org, url, key):
        seen.append((org, url, key))
        return TokenContext(token="ghs_x", issued_at=0.0, installation_id=1)

    monkeypatch.setattr(main, "resolve_github_credentials", _resolve)
    settings = Settings("http://sb.local", "sid", "model", "https://panel.local")
    deps = main.pipeline_deps(settings, "svc-key")
    assert deps.resolve_token("acme") == "ghs_x"
    assert seen == [("acme", "http://sb.local", "svc-key")]


def test_valid_wrapped_payload_reaches_load_pr(sink):
    raw = {"prompt": json.dumps({"prompt": json.dumps(_payload())})}
    _drive(raw)
    assert [s["key"] for s in sink.step_inserts()] == ["load_pr"]


def test_supabase_key_never_reaches_run_events(sink):
    _drive(_payload())
    assert all(SUPABASE_KEY not in m for m in sink.messages())
    assert all(SUPABASE_KEY not in json.dumps(e[2]) for e in sink.events)


# ---------------------------------------------------------------------------
# Startup failures before any run can be reported
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("var", ["SUPABASE_URL", "MODEL_ID", "PANEL_BASE_URL"])
def test_missing_config_fails_internal_error_without_writes(sink, monkeypatch, var):
    monkeypatch.delenv(var)
    result = _drive(_payload())
    assert result["error_code"] == "INTERNAL_ERROR"
    assert [e for e in sink.events if e[0] != "CLOCK"] == []
    _assert_no_github(sink)


def test_supabase_key_failure_fails_internal_error(sink, monkeypatch):
    def _boom(*a, **k):
        raise main.CredentialError("SUPABASE_KEY_UNAVAILABLE", "denied")

    monkeypatch.setattr(main, "fetch_supabase_key", _boom)
    result = _drive(_payload())
    assert result["error_code"] == "INTERNAL_ERROR"
    assert [e for e in sink.events if e[0] != "CLOCK"] == []
