"""
Drive ``main.invoke`` through the S-213 pipeline on recorded fixtures (S-213).

Everything below the AgentCore entrypoint is real: ``main.invoke``, the
``RunReporter`` lifecycle, ``pipeline.Pipeline``, the GitHub client with its
allowlist, the context readers, the budget fit, the prompt builder, the
Bedrock adapter, validation and rendering. Only the edges are replaced:

- the reporter's HTTP layer (``agent_reporter._SupabaseClient``) records every
  write in a ``ReporterSink``;
- the GitHub transport is a ``StubTransport`` (``tests/helpers/github_stub.py``)
  shared by every client the pipeline builds;
- Bedrock is a ``FakeConverse`` (``tests/fixtures/bedrock.py``) behind a
  recording client factory, so the production ``client_factory`` path runs;
- the clock is a ``ManualClock``, the prompt sink a list, and the heartbeat a
  spy that records the step it wraps;
- credential resolution returns ``TOKEN``; the Supabase key is ``SUPABASE_KEY``.

``main.pipeline_deps`` is monkeypatched to hand the pipeline these deps.
"""

from __future__ import annotations

import asyncio
import functools
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import agent_reporter
import main
from github_client import GitHubClient
from heartbeat import is_heartbeat_chunk, read_terminal_payload, run_with_heartbeat
from pipeline import PipelineDeps
from prompt import Prompt
from tests.fixtures.bedrock import FakeConverse, tool_use_response
from tests.helpers.github_stub import StubTransport, json_response, load_fixture, text_response

RUN_ID = "3f2b8c1e-5d4a-4f6b-9a7c-2e1d0b9a8c7f"
OTHER_RUN_ID = "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d"
TOKEN = "ghs_INSTALLATIONtokenSENTINEL0123456789"
SUPABASE_KEY = "svc-key-SENTINEL-5b1e9c"
ORG, REPO, PR = "acme", "widgets", 42
HEAD = "9f2c4e1a7b3d5f60812a4c6e8b0d2f4a6c8e0b1d"
BASE = "3a5c7e9b1d3f5a7c9e1b3d5f7a9c1e3b5d7f9a1c"
MERGE_BASE = "7e1d3c5b9a8f6e4d2c0b1a3f5e7d9c8b6a4f2e0d"
MOVED_HEAD = "0123456789abcdef0123456789abcdef01234567"
MODEL_ID = "us.openai.gpt-5-6-sol-v1:0"
PANEL = "https://panel.local"
RUN_URL = f"{PANEL}/runs/{RUN_ID}"
COMMENT_URL = "https://github.com/acme/widgets/pull/42#issuecomment-2000001"
START = 1_000.0

PREFIX = f"/repos/{ORG}/{REPO}"
PULL_PATH = f"{PREFIX}/pulls/{PR}"
FILES_PATH = f"{PREFIX}/pulls/{PR}/files"
FILES_Q = (("page", "1"), ("per_page", "100"))
COMMENTS_PATH = f"{PREFIX}/issues/{PR}/comments"
COMPARE_PATH = f"{PREFIX}/compare/{BASE}...{HEAD}"

# The hidden marker, anchored at the start of the body (S-212 carry-forward).
MARKER_RE = re.compile(r"\A<!-- code-review-agent:v1 run=([0-9a-f-]{36}) sha=([0-9a-f]{40}) -->")

V1_NOT_REPRODUCED = {
    "candidate_id": "V1",
    "status": "not_reproduced",
    "reason": "The report predates the change.",
}
V1_CONFIRMED = {"candidate_id": "V1", "status": "confirmed", "reason": "Still visible in the diff."}


def review(findings: list[dict[str, Any]] | None = None, checks: Any = None) -> dict[str, Any]:
    """A forced ``submit_review`` response; V1 not reproduced unless ``checks`` says otherwise."""
    return tool_use_response(
        {
            "findings": list(findings or []),
            "verifier_checks": [V1_NOT_REPRODUCED] if checks is None else list(checks),
        },
        usage=(1000, 200),
    )


def blocking(**overrides: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "severity": "blocking",
        "category": "correctness",
        "file": "src/app.py",
        "line_start": 2,
        "line_end": 2,
        "title": "SIZES drops the empty case",
        "failure_scenario": "A caller passes an empty size and gets an IndexError.",
        "consequence": "The widget page returns 500.",
        "rank": 1,
    }
    out.update(overrides)
    return out


def suggestion(**overrides: Any) -> dict[str, Any]:
    return blocking(severity="suggestion", **overrides)


# ---------------------------------------------------------------------------
# Reporter sink
# ---------------------------------------------------------------------------


@dataclass
class ReporterSink:
    """Ordered record of every reporter write (runs, run_steps, run_events, run_artifacts)."""

    writes: list[tuple[str, str, Any]] = field(default_factory=list)

    def install(self, monkeypatch: Any) -> None:
        def _request(_self: Any, method: str, path: str, payload: Any) -> bool:
            table = path.lstrip("/").split("?", 1)[0]
            self.writes.append((method, table, json.loads(json.dumps(payload, default=str))))
            return True

        def _update_expect_rows(_self: Any, table: str, filt: str, patch: dict) -> int:
            self.writes.append(("PATCH", table, json.loads(json.dumps(patch, default=str))))
            return 1

        monkeypatch.setattr(agent_reporter._SupabaseClient, "_request", _request)
        monkeypatch.setattr(
            agent_reporter._SupabaseClient, "update_expect_rows", _update_expect_rows
        )

    def table(self, name: str, method: str | None = None) -> list[Any]:
        return [p for m, t, p in self.writes if t == name and (method is None or m == method)]

    def run_patches(self) -> list[dict[str, Any]]:
        return self.table("runs", "PATCH")

    @property
    def terminal(self) -> dict[str, Any]:
        return self.run_patches()[-1]

    def steps(self) -> list[dict[str, Any]]:
        return [row for batch in self.table("run_steps", "POST") for row in batch]

    def step_keys(self) -> list[str]:
        return [s["key"] for s in self.steps()]

    def step_statuses(self) -> list[str]:
        return [p["status"] for p in self.table("run_steps", "PATCH")]

    def events(self) -> list[dict[str, Any]]:
        return [row for batch in self.table("run_events", "POST") for row in batch]

    def events_for(self, key: str) -> list[dict[str, Any]]:
        ids = {s["id"] for s in self.steps() if s["key"] == key}
        return [e for e in self.events() if e["step_id"] in ids]

    def messages(self, level: str | None = None) -> list[str]:
        return [e["message"] for e in self.events() if level is None or e["level"] == level]

    def artifacts(self) -> list[dict[str, Any]]:
        return [row for batch in self.table("run_artifacts", "POST") for row in batch]

    def dump(self) -> str:
        return json.dumps(self.writes)


# ---------------------------------------------------------------------------
# Clock and heartbeat spy
# ---------------------------------------------------------------------------


class ManualClock:
    """Monotonic seconds that move only when a test advances them."""

    def __init__(self, now: float = START) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


@dataclass
class Harness:
    monkeypatch: Any
    stub: StubTransport = field(default_factory=lambda: load_fixture("sample-pr"))
    fake: FakeConverse = field(default_factory=FakeConverse)
    clock: ManualClock = field(default_factory=ManualClock)
    reporter: ReporterSink = field(default_factory=ReporterSink)
    prompts: list[Prompt] = field(default_factory=list)
    bedrock_factory_calls: list[dict[str, Any]] = field(default_factory=list)
    heartbeat_steps: list[str] = field(default_factory=list)
    token_resolutions: list[str] = field(default_factory=list)
    heartbeat_interval: float = 120.0
    chunks: list[Any] = field(default_factory=list)
    model_id: str = MODEL_ID
    backstops: int = 0
    org: str = ORG
    repo: str = REPO
    pr: int = PR

    def __post_init__(self) -> None:
        self.reporter.install(self.monkeypatch)
        # A reporter left with buffered events (the SIGTERM case) must not flush
        # for real at interpreter exit, after the sink is gone.
        self.monkeypatch.setattr(agent_reporter.atexit, "register", lambda fn, *a, **k: fn)
        self.monkeypatch.setattr(main, "fetch_supabase_key", lambda *a, **k: SUPABASE_KEY)
        self.monkeypatch.setattr(main, "pipeline_deps", lambda settings, key: self.deps())
        self.monkeypatch.setattr(main, "install_termination_backstop", self._backstop)
        for key, value in {
            "SUPABASE_URL": "http://supabase.local",
            "SUPABASE_KEY_SECRET_ID": "agent-fleet/test/key",
            "MODEL_ID": self.model_id,
            "PANEL_BASE_URL": PANEL,
        }.items():
            self.monkeypatch.setenv(key, value)
        for var in ("PRICE_INPUT_PER_MTOK", "PRICE_OUTPUT_PER_MTOK"):
            self.monkeypatch.delenv(var, raising=False)

    def _backstop(self, get_run: Any, get_secrets: Any) -> None:
        self.backstops += 1

    # -- deps ------------------------------------------------------------------

    def resolve_token(self, org: str) -> str:
        self.token_resolutions.append(org)
        return TOKEN

    def bedrock_factory(self, **kwargs: Any) -> FakeConverse:
        self.bedrock_factory_calls.append(kwargs)
        return self.fake

    def heartbeat(self, fn: Callable[[], Any], *, interval: float, seq_start: int = 0) -> Any:
        steps = self.reporter.step_keys()
        self.heartbeat_steps.append(steps[-1] if steps else "")
        return run_with_heartbeat(fn, interval=interval, seq_start=seq_start)

    def deps(self) -> PipelineDeps:
        return PipelineDeps(
            resolve_token=self.resolve_token,
            make_github=functools.partial(GitHubClient, transport=self.stub, sleep=lambda s: None),
            bedrock_factory=self.bedrock_factory,
            clock=self.clock,
            sink=self.prompts.append,
            nonce_factory=_nonces(),
            heartbeat=self.heartbeat,
            heartbeat_interval=self.heartbeat_interval,
        )

    # -- driving -----------------------------------------------------------------

    def payload(self, params: Any = None, run_id: str = RUN_ID) -> dict[str, Any]:
        return {
            "run_id": run_id,
            "repository_org": self.org,
            "repository_name": self.repo,
            "params": {"pr_number": self.pr} if params is None else params,
        }

    def drive(self, params: Any = None, *, run_id: str = RUN_ID) -> dict[str, Any]:
        async def _drain() -> list[Any]:
            return [item async for item in main.invoke(self.payload(params, run_id), None)]

        self.chunks = asyncio.run(_drain())
        text = read_terminal_payload(self.chunks)
        assert text is not None, f"no terminal chunk in {self.chunks!r}"
        result: dict[str, Any] = json.loads(text)
        return result

    @property
    def heartbeat_chunks(self) -> list[Any]:
        return [c for c in self.chunks if is_heartbeat_chunk(c)]

    # -- GitHub traffic ----------------------------------------------------------

    def calls(self, method: str | None = None, path: str | None = None) -> list[Any]:
        return [
            c
            for c in self.stub.calls
            if (method is None or c.method == method) and (path is None or c.path == path)
        ]

    @property
    def prefix(self) -> str:
        return f"/repos/{self.org}/{self.repo}"

    def posts(self) -> list[str]:
        return [
            c.json["body"] for c in self.calls("POST", f"{self.prefix}/issues/{self.pr}/comments")
        ]

    def content_calls(self) -> list[Any]:
        return [c for c in self.stub.calls if c.path.startswith(f"{self.prefix}/contents/")]

    # -- fixture edits -------------------------------------------------------------

    def set_pull(self, **overrides: Any) -> None:
        self.stub.add(("GET", PULL_PATH), json_response(pull_json(**overrides)))

    def set_files(self, files: list[dict[str, Any]]) -> None:
        self.stub.add(("GET", FILES_PATH, FILES_Q), json_response(files))

    def set_content(self, path: str, ref: str, text: str) -> None:
        from urllib.parse import quote

        encoded = "/".join(quote(s, safe="") for s in path.split("/"))
        self.stub.add(
            ("GET", f"{self.prefix}/contents/{encoded}", (("ref", ref),)), text_response(text)
        )

    def set_issue(self, number: int, **overrides: Any) -> None:
        from tests.helpers.github_stub import fixture_json

        body = fixture_json("sample-pr", "issue_41.json")
        body["number"] = number
        body.update(overrides)
        self.stub.add(("GET", f"{self.prefix}/issues/{number}"), json_response(body))


def pull_json(**overrides: Any) -> dict[str, Any]:
    from tests.helpers.github_stub import fixture_json

    body: dict[str, Any] = fixture_json("sample-pr", "pull.json")
    head = overrides.pop("head_sha", None)
    if head is not None:
        body["head"] = {**body["head"], "sha": head}
    body.update(overrides)
    return body


def file_entry(
    filename: str, additions: int = 1, deletions: int = 0, status: str = "modified", **kw: Any
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "filename": filename,
        "status": status,
        "additions": additions,
        "deletions": deletions,
        "patch": kw.pop("patch", "@@ -1 +1 @@\n-a\n+b\n"),
    }
    out.update(kw)
    return out


def _nonces() -> Callable[[], str]:
    counter = iter(range(1, 10_000))
    return lambda: f"{next(counter):016x}"


def marker(body: str) -> tuple[str, str] | None:
    """``(run_id, sha)`` from a marker anchored at the start of ``body``, else ``None``."""
    m = MARKER_RE.match(body)
    return (m.group(1).lower(), m.group(2)) if m else None
