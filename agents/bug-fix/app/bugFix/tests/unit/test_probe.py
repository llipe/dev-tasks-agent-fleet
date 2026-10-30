"""L1 tests for probe mode (S-182 tasks 3.2, 3.14, 3.15; TC-182-06, -07, -14, -16; D-70, D-105).

Probe mode needs **both** a top-level payload key ``__probe: true`` (a real
JSON boolean, outside ``params``; the panel can't send it) and ``ALLOW_PROBE=1``
on the runtime. Anything else never runs a probe check:

- top-level ``__probe: true`` without ``ALLOW_PROBE=1`` -> refused, with a reason;
- ``params.__probe`` -> ignored like any unknown param (normal path);
- a non-boolean top-level value (``"true"``, ``1``) -> normal path;
- ``ALLOW_PROBE=1`` alone -> normal path.

In probe mode each check is reported as exactly one ``run_event`` with
``{check, verdict, detail}``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any

import pytest

import agent_reporter
import main
import probe
from heartbeat import read_terminal_payload
from probe import CheckResult, Verdict
from sandbox import Outcome, SandboxResult, SandboxUnavailable
from scrubber import SecretSet
from tests.unit.test_main_stub import (
    CONFIG,
    NORMAL_SUMMARY,
    PAYLOAD,
    SUPABASE_KEY,
    FakeSupabase,
    _fake_execute,
)

ANTHROPIC_KEY = "sk-ant-api03-probe-sentinel-0123456789abcdef"
PAT = "ghp_" + "P" * 36
APP_TOKEN = "ghs_" + "A" * 36


def _drain(agen) -> list:
    async def _go():
        return [item async for item in agen]

    return asyncio.run(_go())


def _result(chunks: list) -> dict:
    text = read_terminal_payload(chunks)
    assert text is not None
    return json.loads(text)


@pytest.fixture
def probe_calls(monkeypatch):
    calls: list[dict[str, Any]] = []

    def _fake_execute_probe(run, cfg, secrets, supabase_key):
        calls.append({"run": run, "cfg": cfg})
        for c in ("net.blocked.example.com", "proc.environ.uid"):
            run.log(f"probe {c}: PASS", check=c, verdict="PASS", detail="ok")
        return {"probe": True, "passed": 2, "failed": 0, "checks": []}

    FakeSupabase.instances = []
    monkeypatch.setattr(agent_reporter, "_SupabaseClient", FakeSupabase)
    monkeypatch.setattr(main, "load_config", lambda: CONFIG)
    monkeypatch.setattr(main, "fetch_supabase_key", lambda secret_id: SUPABASE_KEY)
    monkeypatch.setattr(
        main, "install_termination_backstop", lambda get_run, get_secrets, get_disposition: None
    )
    monkeypatch.setattr(main, "execute_probe", _fake_execute_probe)
    # The normal path is the orchestration, replaced by the shell tests' fake.
    monkeypatch.setattr(main, "execute", _fake_execute)
    monkeypatch.delenv("ALLOW_PROBE", raising=False)
    return calls


def _with(**top: Any) -> dict:
    payload = json.loads(json.dumps(PAYLOAD))
    payload.update(top)
    return payload


# ---------------------------------------------------------------------------
# TC-182-06 / TC-182-14: the gate
# ---------------------------------------------------------------------------


class TestGate:
    def test_top_level_probe_without_allow_is_refused(self, probe_calls):
        result = _result(_drain(main.invoke(_with(__probe=True), None)))
        assert probe_calls == []
        assert result["status"] == "failed"
        assert result["error_code"] == "PROBE_REFUSED"
        assert "ALLOW_PROBE" in result["summary"]
        final = FakeSupabase.instances[0].run_patches()[-1]
        assert final["status"] == "failed"
        assert final["error_code"] == "PROBE_REFUSED"

    @pytest.mark.parametrize("value", ["0", "true", "yes", "", " 1", "1 "])
    def test_allow_must_be_exactly_1(self, probe_calls, monkeypatch, value):
        monkeypatch.setenv("ALLOW_PROBE", value)
        result = _result(_drain(main.invoke(_with(__probe=True), None)))
        assert probe_calls == []
        assert result["error_code"] == "PROBE_REFUSED"

    def test_allow_and_top_level_true_runs_the_probe(self, probe_calls, monkeypatch):
        monkeypatch.setenv("ALLOW_PROBE", "1")
        result = _result(_drain(main.invoke(_with(__probe=True), None)))
        assert len(probe_calls) == 1
        assert result["status"] == "succeeded"
        assert result["outcome"] == "not_applicable"
        assert result["probe"]["passed"] == 2
        final = FakeSupabase.instances[0].run_patches()[-1]
        assert final["status"] == "succeeded"
        assert final["result"]["probe"] is True

    def test_prompt_wrapped_top_level_probe(self, probe_calls, monkeypatch):
        monkeypatch.setenv("ALLOW_PROBE", "1")
        _drain(main.invoke({"prompt": json.dumps(_with(__probe=True))}, None))
        assert len(probe_calls) == 1

    def test_allow_without_probe_key_takes_normal_path(self, probe_calls, monkeypatch):
        monkeypatch.setenv("ALLOW_PROBE", "1")
        result = _result(_drain(main.invoke(_with(), None)))
        assert probe_calls == []
        assert result["summary"] == NORMAL_SUMMARY

    def test_params_probe_is_ignored_even_with_allow(self, probe_calls, monkeypatch):
        monkeypatch.setenv("ALLOW_PROBE", "1")
        payload = _with()
        payload["params"]["__probe"] = True
        result = _result(_drain(main.invoke(payload, None)))
        assert probe_calls == []
        assert result["status"] == "succeeded"
        assert result["summary"] == NORMAL_SUMMARY

    def test_params_probe_without_allow_never_probes(self, probe_calls):
        payload = _with()
        payload["params"]["__probe"] = True
        result = _result(_drain(main.invoke(payload, None)))
        assert probe_calls == []
        assert result["summary"] == NORMAL_SUMMARY

    @pytest.mark.parametrize("value", ["true", 1, "1", [True], {"x": True}, None, False])
    def test_non_boolean_top_level_is_not_probe_mode(self, probe_calls, monkeypatch, value):
        monkeypatch.setenv("ALLOW_PROBE", "1")
        result = _result(_drain(main.invoke(_with(__probe=value), None)))
        assert probe_calls == []
        assert result["summary"] == NORMAL_SUMMARY

    @pytest.mark.parametrize("value", ["true", 1])
    def test_non_boolean_top_level_without_allow_never_probes(self, probe_calls, value):
        result = _result(_drain(main.invoke(_with(__probe=value), None)))
        assert probe_calls == []
        assert result["status"] == "succeeded"

    def test_pure_helpers(self):
        assert probe.is_probe_request({"__probe": True}) is True
        assert probe.is_probe_request({"params": {"__probe": True}}) is False
        assert probe.is_probe_request({"__probe": "true"}) is False
        assert probe.is_probe_request({"__probe": 1}) is False
        assert probe.probe_allowed({"ALLOW_PROBE": "1"}) is True
        assert probe.probe_allowed({}) is False
        assert probe.probe_allowed({"ALLOW_PROBE": "true"}) is False

    def test_probe_allowed_reads_the_process_env_by_default(self, monkeypatch):
        monkeypatch.setenv("ALLOW_PROBE", "1")
        assert probe.probe_allowed() is True
        monkeypatch.delenv("ALLOW_PROBE")
        assert probe.probe_allowed() is False

    def test_probe_errors_are_reported_scrubbed(self, probe_calls, monkeypatch):
        monkeypatch.setenv("ALLOW_PROBE", "1")

        def _boom(run, cfg, secrets, supabase_key):
            raise RuntimeError(f"probe exploded {SUPABASE_KEY}")

        monkeypatch.setattr(main, "execute_probe", _boom)
        result = _result(_drain(main.invoke(_with(__probe=True), None)))
        assert result["error_code"] == "UNHANDLED_ERROR"
        assert SUPABASE_KEY not in json.dumps(result)


# ---------------------------------------------------------------------------
# TC-182-07: one run_event per check
# ---------------------------------------------------------------------------


class FakeRun:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict]] = []

    def log(self, message: str, level: str = "info", **data: Any) -> None:
        self.events.append((message, level, data))


class TestRunProbe:
    def test_each_check_emits_exactly_one_event(self):
        run = FakeRun()
        checks = [
            ("a", lambda: [CheckResult("a.one", Verdict.PASS, "fine")]),
            (
                "b",
                lambda: [
                    CheckResult("b.one", Verdict.FAIL, "bad"),
                    CheckResult("b.two", Verdict.PASS, "ok"),
                ],
            ),
        ]
        summary = probe.run_probe(checks, run, SecretSet())
        assert [e[2]["check"] for e in run.events] == ["a.one", "b.one", "b.two"]
        for _msg, _lvl, data in run.events:
            assert set(data) == {"check", "verdict", "detail"}
            assert data["verdict"] in ("PASS", "FAIL")
        assert summary["passed"] == 2
        assert summary["failed"] == 1
        assert summary["probe"] is True
        assert [c["check"] for c in summary["checks"]] == ["a.one", "b.one", "b.two"]

    def test_fail_is_logged_as_warn(self):
        run = FakeRun()
        probe.run_probe([("x", lambda: [CheckResult("x", Verdict.FAIL, "d")])], run, SecretSet())
        assert run.events[0][1] == "warn"

    def test_a_raising_group_is_one_fail_and_others_still_run(self):
        run = FakeRun()

        def _boom():
            raise RuntimeError("kaput")

        checks = [("net", _boom), ("proc", lambda: [CheckResult("proc.x", Verdict.PASS, "")])]
        summary = probe.run_probe(checks, run, SecretSet())
        assert [e[2]["check"] for e in run.events] == ["net", "proc.x"]
        assert run.events[0][2]["verdict"] == "FAIL"
        assert "kaput" in run.events[0][2]["detail"]
        assert summary["failed"] == 1

    def test_details_and_messages_are_scrubbed(self):
        run = FakeRun()
        secrets = SecretSet()
        secrets.add("PAT", PAT)
        secrets.add("ANTHROPIC_API_KEY", ANTHROPIC_KEY)
        checks = [("leak", lambda: [CheckResult("leak", Verdict.FAIL, f"{PAT} {ANTHROPIC_KEY}")])]
        summary = probe.run_probe(checks, run, secrets)
        text = json.dumps(run.events) + json.dumps(summary)
        assert PAT not in text and ANTHROPIC_KEY not in text

    def test_as_event(self):
        assert CheckResult("c", Verdict.PASS, "d").as_event() == {
            "check": "c",
            "verdict": "PASS",
            "detail": "d",
        }


# ---------------------------------------------------------------------------
# Check groups over a fake inner runner
# ---------------------------------------------------------------------------


class FakeInner:
    """Answers ``probe_inner.py`` subcommands with scripted JSON."""

    def __init__(self, answers: dict[tuple[str, str], Any]) -> None:
        self.answers = answers
        self.calls: list[tuple[str, tuple[str, ...], str]] = []

    def call(self, sub: str, *args: str, where: str = "sandbox", timeout: float = 60) -> dict:
        self.calls.append((sub, args, where))
        key = (sub, where)
        ans = self.answers.get(
            (sub + ":" + (args[0] if args else ""), where), self.answers.get(key)
        )
        if isinstance(ans, Exception):
            raise ans
        if callable(ans):
            return dict(ans(*args))
        assert isinstance(ans, dict), f"no scripted answer for {sub}/{where}"
        return dict(ans)


def _verdicts(results: list[CheckResult]) -> dict[str, str]:
    return {r.check: r.verdict.value for r in results}


class TestNetChecks:
    def test_blocked_targets_pass_and_registries_pass(self):
        inner = FakeInner(
            {
                ("net", "sandbox"): lambda url, host, port: {
                    "http": "blocked",
                    "tcp": "blocked",
                    "detail": "proxy 403",
                },
                ("tool", "sandbox"): {"rc": 0, "out": "1.3.0"},
            }
        )
        v = _verdicts(probe.net_checks(inner))
        for name in ("169.254.170.2", "169.254.169.254", "example.com"):
            assert v[f"net.blocked.{name}"] == "PASS"
        assert v["net.reachable.registry.npmjs.org"] == "PASS"
        assert v["net.reachable.pypi.org"] == "PASS"
        assert all(w == "sandbox" for (_s, _a, w) in inner.calls)

    def test_any_http_answer_from_a_blocked_target_fails(self):
        inner = FakeInner(
            {
                ("net", "sandbox"): {"http": "status:200", "tcp": "blocked", "detail": ""},
                ("tool", "sandbox"): {"rc": 1, "out": "E403"},
            }
        )
        v = _verdicts(probe.net_checks(inner))
        assert v["net.blocked.169.254.169.254"] == "FAIL"
        assert v["net.reachable.registry.npmjs.org"] == "FAIL"

    def test_raw_tcp_connect_fails_the_check(self):
        inner = FakeInner(
            {
                ("net", "sandbox"): {"http": "blocked", "tcp": "connected", "detail": ""},
                ("tool", "sandbox"): {"rc": 0, "out": ""},
            }
        )
        assert _verdicts(probe.net_checks(inner))["net.blocked.example.com"] == "FAIL"

    def test_proxy_403_counts_as_blocked(self):
        inner = FakeInner(
            {
                ("net", "sandbox"): {
                    "http": "status:403",
                    "proxy_error": True,
                    "tcp": "blocked",
                    "detail": "blocked-by-sandbox-runtime",
                },
                ("tool", "sandbox"): {"rc": 0, "out": ""},
            }
        )
        assert _verdicts(probe.net_checks(inner))["net.blocked.example.com"] == "PASS"


class TestLocalhostCheck:
    """Re-probes 2b/2c: srt's proxy is ``localhost``; it must resolve to loopback
    inside the sandbox, IPv4 first (srt's in-namespace bridge may listen on
    IPv4 only). The detail names the route the wrapper's preflight found:
    ``via=hosts`` (``/etc/hosts``), ``via=nss`` (``libnss-myhostname``) or
    ``via=none``."""

    def _inner(self, resolve: Any) -> FakeInner:
        return FakeInner(
            {
                ("resolve", "sandbox"): resolve,
                ("net", "sandbox"): {"http": "blocked", "tcp": "blocked"},
                ("tool", "sandbox"): {"rc": 0, "out": ""},
            }
        )

    def test_loopback_passes_and_reports_the_route(self):
        inner = self._inner(
            {"addrs": ["127.0.0.1", "::1"], "hosts": [], "nsswitch": "files myhostname dns"}
        )
        (r,) = [x for x in probe.net_checks(inner, localhost_via=lambda: "nss") if
                x.check == "net.localhost"]  # fmt: skip
        assert r.verdict is Verdict.PASS
        assert "via=nss" in r.detail
        assert "127.0.0.1" in r.detail
        assert "files myhostname dns" in r.detail
        assert ("resolve", ("localhost",), "sandbox") in inner.calls

    def test_via_hosts_is_reported(self):
        inner = self._inner({"addrs": ["127.0.0.1"], "hosts": ["127.0.0.1\tlocalhost"]})
        r = probe.net_checks(inner, localhost_via=lambda: "hosts")[0]
        assert r.verdict is Verdict.PASS
        assert "via=hosts" in r.detail

    def test_it_runs_first(self):
        inner = self._inner({"addrs": ["127.0.0.1", "::1"], "hosts": []})
        assert probe.net_checks(inner)[0].check == "net.localhost"

    @pytest.mark.parametrize(
        "answer",
        [
            {"addrs": [], "error": "gaierror: [Errno -3] Temporary failure in name resolution"},
            {"addrs": ["10.0.0.5"]},
            {"addrs": ["127.0.0.1", "10.0.0.5"]},
            # Loopback, but IPv6 first: a v4-only bridge would refuse it.
            {"addrs": ["::1", "127.0.0.1"]},
            {"addrs": ["::1"]},
        ],
    )
    def test_unresolved_non_loopback_or_ipv6_first_fails(self, answer):
        r = probe.net_checks(self._inner(answer))[0]
        assert r.check == "net.localhost"
        assert r.verdict is Verdict.FAIL

    def test_default_route_is_unchecked(self):
        r = probe.net_checks(self._inner({"addrs": ["127.0.0.1"]}))[0]
        assert "via=unchecked" in r.detail

    def test_preflight_failure_reports_via_none(self):
        refused = SandboxUnavailable("sandbox cannot resolve localhost: x")
        r = probe.net_checks(self._inner(refused), localhost_via=lambda: "none")[0]
        assert r.check == "net.localhost"
        assert r.verdict is Verdict.FAIL
        assert "via=none" in r.detail
        assert "cannot resolve localhost" in r.detail


class TestProcAndEnvChecks:
    def test_unreadable_environ_and_mem_pass(self):
        inner = FakeInner(
            {
                ("proc", "sandbox"): {
                    "environ": "unreadable:ENOENT",
                    "mem": "unreadable:ENOENT",
                    "visible": False,
                },
                ("proc", "uid"): {
                    "environ": "unreadable:EACCES",
                    "mem": "unreadable:EACCES",
                    "visible": True,
                },
            }
        )
        v = _verdicts(probe.proc_checks(inner, 77))
        assert v == {"proc.wrapper.sandbox": "PASS", "proc.wrapper.uid": "PASS"}
        assert inner.calls[0][1] == ("77",)

    def test_readable_environ_fails(self):
        inner = FakeInner(
            {
                ("proc", "sandbox"): {"environ": "unreadable:ENOENT", "mem": "unreadable:ENOENT"},
                ("proc", "uid"): {"environ": "readable:812", "mem": "unreadable:EACCES"},
            }
        )
        assert _verdicts(probe.proc_checks(inner, 77))["proc.wrapper.uid"] == "FAIL"

    def test_env_names_only_allow_list(self):
        inner = FakeInner(
            {
                ("env", "sandbox"): {
                    "names": ["ANTHROPIC_API_KEY", "CI", "HOME", "HTTPS_PROXY", "LANG", "PATH"]
                },
                ("env", "uid"): {"names": ["CI", "HOME", "LANG", "PATH"]},
            }
        )
        v = _verdicts(probe.env_checks(inner))
        assert v == {"env.fixer.sandbox": "PASS", "env.fixer.uid": "PASS"}

    @pytest.mark.parametrize(
        "bad",
        [
            "AWS_ACCESS_KEY_ID",
            "AWS_CONTAINER_CREDENTIALS_FULL_URI",
            "SUPABASE_URL",
            "GITHUB_TOKEN",
            "GH_TOKEN",
            "PROJECTS_TOKEN_SECRET_ID",
            "GITHUB_PROJECTS_TOKEN",
        ],
    )
    def test_env_with_forbidden_name_fails(self, bad):
        inner = FakeInner(
            {("env", "sandbox"): {"names": ["CI", bad]}, ("env", "uid"): {"names": ["CI"]}}
        )
        r = {x.check: x for x in probe.env_checks(inner)}
        assert r["env.fixer.sandbox"].verdict is Verdict.FAIL
        assert bad in r["env.fixer.sandbox"].detail

    def test_policy_and_secret_checks(self):
        inner = FakeInner(
            {
                ("write", "sandbox"): {"written": False, "error": "EROFS"},
                ("read", "sandbox"): {"readable": False, "error": "EACCES"},
                ("read", "uid"): {"readable": False, "error": "EACCES"},
            }
        )
        v = _verdicts(probe.policy_checks(inner, _canary))
        assert v == {
            "policy.tamper": "PASS",
            "secrets.dir.sandbox": "PASS",
            "secrets.dir.uid": "PASS",
        }

    def test_policy_written_fails(self):
        inner = FakeInner(
            {
                ("write", "sandbox"): {"written": True},
                ("read", "sandbox"): {"readable": True},
                ("read", "uid"): {"readable": False},
            }
        )
        v = _verdicts(probe.policy_checks(inner, _canary))
        assert v["policy.tamper"] == "FAIL"
        assert v["secrets.dir.sandbox"] == "FAIL"


def _canary() -> tuple[str, Any]:
    return "/work/secrets/probe-canary-test", lambda: None


class TestSecretCanary:
    def test_canary_is_read_and_removed(self, tmp_path):
        removed: list[bool] = []
        inner = FakeInner(
            {
                ("write", "sandbox"): {"written": False},
                ("read", "sandbox"): {"readable": False, "error": "EACCES"},
                ("read", "uid"): {"readable": False, "error": "EACCES"},
            }
        )

        def _make():
            return str(tmp_path / "canary"), lambda: removed.append(True)

        v = _verdicts(probe.policy_checks(inner, _make))
        assert v["secrets.dir.sandbox"] == "PASS"
        reads = [c for c in inner.calls if c[0] == "read"]
        assert [c[1] for c in reads] == [(str(tmp_path / "canary"),)] * 2
        assert removed == [True]

    def test_canary_write_failure_fails_both(self):
        def _make():
            raise PermissionError(13, "denied")

        inner = FakeInner({("write", "sandbox"): {"written": False}})
        v = _verdicts(probe.policy_checks(inner, _make))
        assert v["secrets.dir.sandbox"] == "FAIL" and v["secrets.dir.uid"] == "FAIL"

    def test_write_secret_canary(self, tmp_path):
        import stat

        path, remove = probe.write_secret_canary(str(tmp_path))
        assert stat.S_IMODE((tmp_path / path.rsplit("/", 1)[1]).stat().st_mode) == 0o600
        remove()
        remove()  # idempotent
        assert list(tmp_path.iterdir()) == []


class TestPatAbsent:
    def test_hash_is_passed_never_the_token(self):
        inner = FakeInner(
            {
                ("scan", "sandbox"): {"matches": 0, "files": 12},
                ("scan", "uid"): {"matches": 0, "files": 30},
            }
        )
        v = _verdicts(probe.pat_absent_checks(inner, PAT))
        assert v == {"board.pat_absent.sandbox": "PASS", "board.pat_absent.uid": "PASS"}
        for _sub, args, _w in inner.calls:
            assert PAT not in " ".join(args)
            assert args[0] == hashlib.sha256(PAT.encode()).hexdigest()

    def test_match_fails(self):
        inner = FakeInner(
            {
                ("scan", "sandbox"): {"matches": 1, "files": 3},
                ("scan", "uid"): {"matches": 0, "files": 3},
            }
        )
        assert _verdicts(probe.pat_absent_checks(inner, PAT))["board.pat_absent.sandbox"] == "FAIL"

    def test_no_pat_fails_with_reason(self):
        r = probe.pat_absent_checks(FakeInner({}), None)
        assert [x.verdict for x in r] == [Verdict.FAIL]
        assert "not configured" in r[0].detail


class TestBoardDisabledWithoutPat:
    def test_disabled_and_run_continues(self):
        env = {
            "SUPABASE_URL": "https://x.supabase.co",
            "SUPABASE_KEY_SECRET_ID": "s",
            "ANTHROPIC_KEY_SECRET_ID": "a",
            "MODEL_ID": "claude-sonnet-5-5",
            "BOARD_UPDATES_ENABLED": "1",
            "PROJECTS_TOKEN_SECRET_ID": "agent-fleet/prod/GITHUB_PROJECTS_TOKEN",
        }
        (r,) = probe.board_disabled_without_pat(env)
        assert r.check == "board.disabled_without_pat"
        assert r.verdict is Verdict.PASS
        assert "no_token_secret_id" in r.detail

    def test_config_error_fails(self):
        (r,) = probe.board_disabled_without_pat({})
        assert r.verdict is Verdict.FAIL


# ---------------------------------------------------------------------------
# claude -p checks (SC-IC-04)
# ---------------------------------------------------------------------------


class FakeSandbox:
    def __init__(self, stdout: str, outcome: Outcome = Outcome.OK) -> None:
        self.stdout = stdout
        self.outcome = outcome
        self.calls: list[dict[str, Any]] = []
        self.localhost_via = "nss"

    def run(self, argv, **kw):
        self.calls.append({"argv": list(argv), **kw})
        return SandboxResult(
            outcome=self.outcome,
            exit_code=0 if self.outcome is Outcome.OK else 1,
            timed_out=self.outcome is Outcome.TIMEOUT,
            stdout=self.stdout,
            stderr="",
            duration_s=1.0,
        )


def _cli_json(denials: list[dict]) -> str:
    return json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": "done",
            "permission_denials": denials,
        }
    )


DEFAULT_TOOLS = ["Bash", "Edit", "Glob", "Grep", "Read", "Write"]


def _cli_stream(denials: list[dict], tools: list[str] | None = None) -> str:
    """``--output-format stream-json --verbose``: the init event, then the result."""
    lines = []
    if tools is not None:
        lines.append(
            json.dumps(
                {"type": "system", "subtype": "init", "tools": tools, "permissionMode": "default"}
            )
        )
    lines.append(json.dumps({"type": "assistant", "message": {"content": []}}))
    lines.append(_cli_json(denials))
    return "\n".join(lines) + "\n"


DROPPED = {
    "uid": [10002, 10002, 10002, 10002],
    "gid": [10002, 10002, 10002, 10002],
    "groups": [],
    "cap_inh": "0000000000000000",
    "cap_prm": "0000000000000000",
    "cap_eff": "0000000000000000",
    "cap_amb": "0000000000000000",
    "cap_bnd": "000001ffffffffff",
    "no_new_privs": 1,
}
ROOT_IDS = {
    "uid": [0, 0, 0, 0],
    "gid": [0, 0, 0, 0],
    "groups": [0],
    "cap_eff": "00000000a80425fb",  # Docker's default set: includes SETUID/SETGID
    "no_new_privs": 1,
}
REFUSED = {
    "setuid0": "EPERM",
    "setgid0": "EPERM",
    "su": {"rc": 1, "err": "su: Authentication failure"},
    "setpriv_root": {"rc": 1, "err": "setpriv: setresuid failed: Operation not permitted"},
    "no_new_privs": 1,
    "sudo_on_path": False,
}


class TestSetprivChecks:
    """D-110: the root wrapper drops to fixer with setpriv (replaces sudo.*)."""

    def _inner(self, uid=DROPPED, sandbox=DROPPED) -> FakeInner:
        return FakeInner({("ids", "uid"): uid, ("ids", "sandbox"): sandbox})

    def test_all_pass(self):
        v = _verdicts(probe.setpriv_checks(self._inner(), self_ids=lambda: ROOT_IDS))
        assert v == {
            "setpriv.wrapper.root": "PASS",
            "setpriv.drop.uid": "PASS",
            "setpriv.drop.sandbox": "PASS",
        }

    def test_uid_form_checked_first(self):
        inner = self._inner()
        probe.setpriv_checks(inner, self_ids=lambda: ROOT_IDS)
        assert [(c[0], c[2]) for c in inner.calls] == [("ids", "uid"), ("ids", "sandbox")]

    def test_wrapper_not_root_fails(self):
        ids = {**ROOT_IDS, "uid": [10001, 10001, 10001, 10001]}
        r = {x.check: x for x in probe.setpriv_checks(self._inner(), self_ids=lambda: ids)}
        assert r["setpriv.wrapper.root"].verdict is Verdict.FAIL
        assert "10001" in r["setpriv.wrapper.root"].detail

    def test_wrapper_without_setuid_cap_fails(self):
        ids = {**ROOT_IDS, "cap_eff": "0000000000000000"}
        r = {x.check: x for x in probe.setpriv_checks(self._inner(), self_ids=lambda: ids)}
        assert r["setpriv.wrapper.root"].verdict is Verdict.FAIL
        assert "CAP_SETUID" in r["setpriv.wrapper.root"].detail

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("uid", [10002, 0, 10002, 10002]),
            ("gid", [10002, 10002, 0, 10002]),
            ("groups", [0]),
            ("cap_eff", "0000000000000040"),
            ("cap_prm", "0000000000000080"),
            ("cap_inh", "0000000000000001"),
            ("cap_amb", "0000000000000001"),
            ("no_new_privs", 0),
            ("uid", None),
        ],
    )
    def test_any_privilege_left_fails(self, field, value):
        bad = {**DROPPED, field: value}
        v = _verdicts(probe.setpriv_checks(self._inner(uid=bad), self_ids=lambda: ROOT_IDS))
        assert v["setpriv.drop.uid"] == "FAIL"
        assert v["setpriv.drop.sandbox"] == "PASS"

    def test_detail_names_uid_caps_and_nnp(self):
        r = {x.check: x for x in probe.setpriv_checks(self._inner(), self_ids=lambda: ROOT_IDS)}
        detail = r["setpriv.drop.uid"].detail
        assert "uid=10002" in detail and "CapEff=0000000000000000" in detail
        assert "NoNewPrivs=1" in detail

    def test_error_from_inner_is_a_fail_of_that_check_only(self):
        inner = FakeInner(
            {("ids", "uid"): DROPPED, ("ids", "sandbox"): probe.ProbeError("bwrap: denied")}
        )
        v = _verdicts(probe.setpriv_checks(inner, self_ids=lambda: ROOT_IDS))
        assert v["setpriv.drop.uid"] == "PASS"
        assert v["setpriv.drop.sandbox"] == "FAIL"

    def test_default_self_ids_reads_own_status(self, monkeypatch):
        seen: list[str] = []

        def _ids(path="/proc/self/status"):
            seen.append(path)
            return ROOT_IDS

        monkeypatch.setattr(probe.probe_inner, "cmd_ids", _ids)
        probe.setpriv_checks(self._inner())
        assert seen == ["/proc/self/status"]


class TestNoEscalateChecks:
    def _inner(self, uid=REFUSED, sandbox=REFUSED) -> FakeInner:
        return FakeInner({("escalate", "uid"): uid, ("escalate", "sandbox"): sandbox})

    def test_all_pass(self):
        v = _verdicts(
            probe.noescalate_checks(self._inner(), which=lambda n: None, exists=lambda p: False)
        )
        assert v == {
            "noescalate.fixer.uid": "PASS",
            "noescalate.fixer.sandbox": "PASS",
            "noescalate.no_sudo": "PASS",
        }

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("setuid0", "ok"),
            ("setgid0", "ok"),
            ("su", {"rc": 0, "err": ""}),
            ("setpriv_root", {"rc": 0, "err": ""}),
            ("no_new_privs", 0),
            ("sudo_on_path", True),
        ],
    )
    def test_any_way_back_fails(self, field, value):
        bad = {**REFUSED, field: value}
        v = _verdicts(
            probe.noescalate_checks(
                self._inner(uid=bad), which=lambda n: None, exists=lambda p: False
            )
        )
        assert v["noescalate.fixer.uid"] == "FAIL"
        assert v["noescalate.fixer.sandbox"] == "PASS"

    def test_sudo_binary_present_fails(self):
        r = {
            x.check: x
            for x in probe.noescalate_checks(
                self._inner(), which=lambda n: "/usr/bin/sudo", exists=lambda p: False
            )
        }
        assert r["noescalate.no_sudo"].verdict is Verdict.FAIL
        assert "/usr/bin/sudo" in r["noescalate.no_sudo"].detail

    def test_sudoers_file_present_fails(self):
        v = _verdicts(
            probe.noescalate_checks(
                self._inner(),
                which=lambda n: None,
                exists=lambda p: p == "/etc/sudoers.d/bug-fix",
            )
        )
        assert v["noescalate.no_sudo"] == "FAIL"


USERNS_OK = {
    "bwrap": {"rc": 0, "err": ""},
    "unshare": {"rc": 0, "err": ""},
    "sysctl": {"max_user_namespaces": "15000", "unprivileged_userns_clone": None},
}
USERNS_DENIED = {
    "bwrap": {"rc": 1, "err": "bwrap: No permissions to create a new namespace"},
    "unshare": {"rc": 1, "err": "unshare: unshare failed: Operation not permitted"},
    "sysctl": {"max_user_namespaces": "0", "unprivileged_userns_clone": None},
}


class TestUsernsCheck:
    """``userns.available``: reported on its own, so the run says precisely
    whether AgentCore allows the namespaces bwrap/srt need (D-110)."""

    def test_pass_when_bwrap_creates_them(self):
        inner = FakeInner({("userns", "uid"): USERNS_OK})
        (r,) = probe.userns_checks(inner, root_userns=lambda: USERNS_OK)
        assert r.check == "userns.available"
        assert r.verdict is Verdict.PASS
        assert inner.calls == [("userns", (), "uid")]

    def test_fail_when_bwrap_is_refused(self):
        inner = FakeInner({("userns", "uid"): USERNS_DENIED})
        (r,) = probe.userns_checks(inner, root_userns=lambda: USERNS_DENIED)
        assert r.verdict is Verdict.FAIL
        assert "No permissions" in r.detail
        assert "max_user_namespaces=0" in r.detail

    def test_root_result_is_in_the_detail_only(self):
        inner = FakeInner({("userns", "uid"): USERNS_DENIED})
        (r,) = probe.userns_checks(inner, root_userns=lambda: USERNS_OK)
        assert r.verdict is Verdict.FAIL
        assert "root: bwrap rc=0" in r.detail

    def test_root_measure_error_does_not_hide_the_fixer_result(self):
        def _boom():
            raise OSError("python missing")

        inner = FakeInner({("userns", "uid"): USERNS_OK})
        (r,) = probe.userns_checks(inner, root_userns=_boom)
        assert r.verdict is Verdict.PASS
        assert "OSError" in r.detail

    def test_default_root_measure_runs_probe_inner_as_the_wrapper(self):
        seen: dict[str, Any] = {}

        def _run(cmd, **kw):
            seen["cmd"] = cmd
            seen["env"] = kw["env"]
            return _Done(json.dumps(USERNS_OK))

        inner = FakeInner({("userns", "uid"): USERNS_OK})
        probe.userns_checks(inner, run=_run, paths=probe.default_paths())
        p = probe.default_paths()
        assert seen["cmd"] == [p.python, "-I", probe.INNER_SCRIPT, "userns"]
        assert set(seen["env"]) == {"PATH", "HOME", "LANG", "CI"}


class TestCliChecks:
    def _inner(self, refs: int = 0) -> FakeInner:
        return FakeInner(
            {
                ("mkrepo", "sandbox"): {"ok": True, "dir": "/work/repo/probe-x"},
                ("refs", "sandbox"): {"refs": refs},
            }
        )

    def test_denials_pass(self):
        sb = FakeSandbox(
            _cli_json(
                [
                    {"tool_name": "Bash", "tool_input": {"command": "git push origin HEAD:main"}},
                    {"tool_name": "WebFetch", "tool_input": {"url": "https://example.com"}},
                ]
            )
        )
        paths = probe.default_paths()
        v = _verdicts(
            probe.cli_checks(sb, self._inner(), paths, ANTHROPIC_KEY, "claude-sonnet-5-5")
        )
        assert v["cli.deny.git_push"] == "PASS"
        assert v["cli.deny.webfetch"] == "PASS"
        call = sb.calls[0]
        assert call["argv"][0] == paths.claude
        assert call["anthropic_api_key"] == ANTHROPIC_KEY
        argv = call["argv"]
        assert argv[argv.index("--output-format") + 1] == "stream-json"
        assert "--verbose" in argv
        assert ANTHROPIC_KEY not in " ".join(call["argv"])
        assert "--dangerously-skip-permissions" not in call["argv"]

    def test_push_landing_on_remote_fails_even_with_a_denial(self):
        sb = FakeSandbox(
            _cli_json(
                [
                    {"tool_name": "Bash", "tool_input": {"command": "git push origin HEAD:main"}},
                    {"tool_name": "WebFetch", "tool_input": {}},
                ]
            )
        )
        v = _verdicts(
            probe.cli_checks(sb, self._inner(refs=1), probe.default_paths(), ANTHROPIC_KEY, "m")
        )
        assert v["cli.deny.git_push"] == "FAIL"

    def test_not_attempted_is_fail(self):
        sb = FakeSandbox(_cli_json([]))
        v = _verdicts(
            probe.cli_checks(sb, self._inner(), probe.default_paths(), ANTHROPIC_KEY, "m")
        )
        assert v["cli.deny.git_push"] == "FAIL"
        assert v["cli.deny.webfetch"] == "FAIL"

    def test_tools_removed_from_the_model_pass_without_a_denial(self):
        """Re-probe 2b: a tool-wide deny removes the tool from the init tool list,
        so the model never calls it and there is no permission_denials entry.
        That is the deny working, not failing open."""
        sb = FakeSandbox(
            _cli_stream(
                [{"tool_name": "Bash", "tool_input": {"command": "git push origin HEAD:main"}}],
                tools=DEFAULT_TOOLS,
            )
        )
        r = probe.cli_checks(sb, self._inner(), probe.default_paths(), ANTHROPIC_KEY, "m")
        v = _verdicts(r)
        assert v["cli.deny.webfetch"] == "PASS"
        assert v["cli.deny.websearch"] == "PASS"
        detail = {x.check: x.detail for x in r}["cli.deny.webfetch"]
        assert "offered=False" in detail

    def test_tool_offered_and_not_denied_fails(self):
        sb = FakeSandbox(_cli_stream([], tools=[*DEFAULT_TOOLS, "WebFetch", "WebSearch"]))
        v = _verdicts(
            probe.cli_checks(sb, self._inner(), probe.default_paths(), ANTHROPIC_KEY, "m")
        )
        assert v["cli.deny.webfetch"] == "FAIL"
        assert v["cli.deny.websearch"] == "FAIL"

    def test_tool_offered_but_denied_passes(self):
        sb = FakeSandbox(
            _cli_stream(
                [{"tool_name": "WebFetch", "tool_input": {}}],
                tools=[*DEFAULT_TOOLS, "WebFetch"],
            )
        )
        v = _verdicts(
            probe.cli_checks(sb, self._inner(), probe.default_paths(), ANTHROPIC_KEY, "m")
        )
        assert v["cli.deny.webfetch"] == "PASS"

    def test_no_init_event_and_no_denial_fails(self):
        sb = FakeSandbox(_cli_stream([], tools=None))
        v = _verdicts(
            probe.cli_checks(sb, self._inner(), probe.default_paths(), ANTHROPIC_KEY, "m")
        )
        assert v["cli.deny.webfetch"] == "FAIL"
        assert v["cli.deny.websearch"] == "FAIL"

    def test_unparseable_output_fails_both(self):
        sb = FakeSandbox("not json", outcome=Outcome.FAILED)
        r = probe.cli_checks(sb, self._inner(), probe.default_paths(), ANTHROPIC_KEY, "m")
        assert {x.verdict for x in r} == {Verdict.FAIL}

    def test_no_key_fails_without_running(self):
        sb = FakeSandbox("")
        r = probe.cli_checks(sb, self._inner(), probe.default_paths(), None, "m")
        assert sb.calls == []
        assert {x.verdict for x in r} == {Verdict.FAIL}
        assert "ANTHROPIC" in r[0].detail

    def test_version_check(self):
        sb = FakeSandbox("2.1.309 (Claude Code)\n")
        (r,) = probe.cli_version_check(sb, probe.default_paths(), "2.1.309")
        assert r.verdict is Verdict.PASS
        assert "rc=0" in r.detail
        (r2,) = probe.cli_version_check(sb, probe.default_paths(), "9.9.9")
        assert r2.verdict is Verdict.FAIL

    def test_version_failure_reports_exit_code_and_stderr(self):
        # Probe run 1 showed only `claude --version=''`: the cause is in stderr.
        class SB(FakeSandbox):
            def run(self, argv, **kw):
                self.calls.append({"argv": list(argv), **kw})
                return SandboxResult(
                    outcome=Outcome.FAILED,
                    exit_code=1,
                    timed_out=False,
                    stdout="",
                    stderr='sudo: The "no new privileges" flag is set',
                    duration_s=0.1,
                )

        (r,) = probe.cli_version_check(SB(""), probe.default_paths(), "2.1.309")
        assert r.verdict is Verdict.FAIL
        assert "rc=1" in r.detail
        assert "outcome=failed" in r.detail
        assert "no new privileges" in r.detail

    def test_version_on_stderr_counts(self):
        class SB(FakeSandbox):
            def run(self, argv, **kw):
                return SandboxResult(Outcome.OK, 0, False, "", "2.1.309 (Claude Code)\n", 0.1)

        (r,) = probe.cli_version_check(SB(""), probe.default_paths(), "2.1.309")
        assert r.verdict is Verdict.PASS

    def test_version_nonzero_exit_fails_even_with_version_text(self):
        class SB(FakeSandbox):
            def run(self, argv, **kw):
                return SandboxResult(Outcome.FAILED, 2, False, "2.1.309", "boom", 0.1)

        (r,) = probe.cli_version_check(SB(""), probe.default_paths(), "2.1.309")
        assert r.verdict is Verdict.FAIL

    def test_version_sandbox_error_is_reported(self):

        class SB(FakeSandbox):
            def run(self, argv, **kw):
                raise SandboxUnavailable("sandbox setpriv is missing: /usr/bin/setpriv")

        (r,) = probe.cli_version_check(SB(""), probe.default_paths(), "2.1.309")
        assert r.verdict is Verdict.FAIL
        assert "setpriv is missing" in r.detail

    def test_version_without_pin_fails(self):
        (r,) = probe.cli_version_check(FakeSandbox("2.1.309"), probe.default_paths(), None)
        assert r.verdict is Verdict.FAIL


# ---------------------------------------------------------------------------
# TC-182-16: board probe with the Projects GraphQL mocked
# ---------------------------------------------------------------------------


class Resp:
    def __init__(self, status: int, body: Any) -> None:
        self.status_code = status
        self._body = body

    def json(self) -> Any:
        return self._body


class FakeGitHub:
    """Routes GraphQL by operation and REST by method+path; records the auth used."""

    def __init__(
        self,
        *,
        existing_issue: bool = False,
        pre_item: bool = False,
        fail_on: str | None = None,
        boards: list[int] | None = None,
        readback_wrong: bool = False,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self.existing_issue = existing_issue
        self.pre_item = pre_item
        self.fail_on = fail_on
        self.boards = boards if boards is not None else [3, 5]
        self.readback_wrong = readback_wrong
        self.status = None
        self.items_added = 0

    def _auth(self, headers: dict) -> str:
        return headers["Authorization"].split(" ", 1)[1]

    def post(self, url: str, headers: dict, json: dict, timeout: float) -> Resp:
        assert timeout <= 10
        if url.endswith("/graphql"):
            return self._graphql(headers, json)
        return self.request("POST", url, headers=headers, json=json, timeout=timeout)

    def request(
        self,
        method: str,
        url: str,
        headers: dict,
        json: Any = None,
        timeout: float = 10,
        params: Any = None,
    ) -> Resp:
        assert timeout <= 10
        self.calls.append(
            {
                "kind": "rest",
                "method": method,
                "url": url,
                "token": self._auth(headers),
                "json": json,
            }
        )
        if method == "GET" and "/issues" in url:
            items = [{"title": "something else", "number": 1, "node_id": "I_1"}]
            if self.existing_issue:
                items.append(
                    {
                        "title": probe.PROBE_ISSUE_TITLE,
                        "number": 42,
                        "node_id": "I_42",
                        "state": "closed",
                    }
                )
            return Resp(200, items)
        if method == "POST" and url.endswith("/issues"):
            return Resp(201, {"number": 43, "node_id": "I_43", "title": json["title"]})
        if method == "PATCH":
            return Resp(200, {"state": json["state"]})
        return Resp(404, {})

    def _graphql(self, headers: dict, body: dict) -> Resp:
        q = body["query"]
        v = body.get("variables", {})
        op = q.split("(")[0].split()[-1]
        self.calls.append(
            {"kind": "graphql", "op": op, "token": self._auth(headers), "variables": v}
        )
        if self.fail_on and self.fail_on == op:
            raise RuntimeError(f"{op} exploded")
        if op == "Boards":
            nodes = [{"id": f"PVT_{n}", "number": n, "title": f"Board {n}"} for n in self.boards]
            return Resp(200, {"data": {"repository": {"projectsV2": {"nodes": nodes}}}})
        if op == "IssueItems":
            nodes = [{"id": "PVTI_pre", "project": {"id": "PVT_5"}}] if self.pre_item else []
            nodes.append({"id": "PVTI_other", "project": {"id": "PVT_3"}})
            return Resp(200, {"data": {"node": {"projectItems": {"nodes": nodes}}}})
        if op == "AddItem":
            self.items_added += 1
            item = "PVTI_pre" if self.pre_item else "PVTI_new"
            return Resp(200, {"data": {"addProjectV2ItemById": {"item": {"id": item}}}})
        if op == "StatusField":
            opts = [
                {"id": "o1", "name": "Todo"},
                {"id": "o2", "name": "In Progress"},
                {"id": "o3", "name": "In review"},
                {"id": "o4", "name": "READY"},
            ]
            return Resp(200, {"data": {"node": {"field": {"id": "F1", "options": opts}}}})
        if op == "SetStatus":
            self.status = v["optionId"]
            return Resp(
                200,
                {"data": {"updateProjectV2ItemFieldValue": {"projectV2Item": {"id": v["itemId"]}}}},
            )
        if op == "ReadStatus":
            names = {"o1": "Todo", "o2": "In Progress", "o3": "In review", "o4": "READY"}
            name = "Todo" if self.readback_wrong else names.get(str(self.status), "")
            return Resp(
                200,
                {"data": {"node": {"fieldValueByName": {"name": name, "optionId": self.status}}}},
            )
        if op == "DeleteItem":
            return Resp(200, {"data": {"deleteProjectV2Item": {"deletedItemId": v["itemId"]}}})
        return Resp(200, {"errors": [{"message": f"unknown op {op}"}]})


def _board(gh: FakeGitHub) -> probe.Board:
    return probe.Board(pat=PAT, app_token=lambda: APP_TOKEN, http=gh)


class TestBoardProbe:
    def test_happy_path(self):
        gh = FakeGitHub()
        v = _verdicts(probe.board_probe(_board(gh)))
        assert v == {
            "board.detect": "PASS",
            "board.add_idempotent": "PASS",
            "board.status.in_progress": "PASS",
            "board.status.in_review": "PASS",
            "board.status.ready": "PASS",
            "board.cleanup": "PASS",
        }
        assert gh.items_added == 2

    def test_every_board_call_uses_the_pat_and_never_the_app_token(self):
        gh = FakeGitHub()
        probe.board_probe(_board(gh))
        for c in gh.calls:
            if c["kind"] == "graphql":
                assert c["token"] == PAT
            else:
                assert c["token"] == APP_TOKEN  # issue create/close only
                assert "/repos/llipe/dev-tasks/issues" in c["url"]

    def test_cleanup_deletes_only_the_added_item_and_closes_issue(self):
        gh = FakeGitHub()
        probe.board_probe(_board(gh))
        deletes = [c for c in gh.calls if c.get("op") == "DeleteItem"]
        assert len(deletes) == 1
        assert deletes[0]["variables"]["itemId"] == "PVTI_new"
        assert deletes[0]["variables"]["projectId"] == "PVT_5"
        closes = [c for c in gh.calls if c["kind"] == "rest" and c["method"] == "PATCH"]
        assert closes[-1]["json"] == {"state": "closed"}
        assert closes[-1]["url"].endswith("/issues/43")

    @pytest.mark.parametrize("op", ["AddItem", "StatusField", "SetStatus", "ReadStatus"])
    def test_cleanup_runs_when_a_later_step_raises(self, op):
        gh = FakeGitHub(fail_on=op)
        results = probe.board_probe(_board(gh))
        v = _verdicts(results)
        assert "board.cleanup" in v
        closes = [c for c in gh.calls if c["kind"] == "rest" and c["method"] == "PATCH"]
        assert closes and closes[-1]["json"] == {"state": "closed"}
        deletes = [c for c in gh.calls if c.get("op") == "DeleteItem"]
        if op == "AddItem":
            assert deletes == []  # nothing was added, nothing deleted
        else:
            assert [d["variables"]["itemId"] for d in deletes] == ["PVTI_new"]
        assert "FAIL" in v.values()

    def test_pre_existing_card_is_never_deleted(self):
        gh = FakeGitHub(existing_issue=True, pre_item=True)
        v = _verdicts(probe.board_probe(_board(gh)))
        assert [c for c in gh.calls if c.get("op") == "DeleteItem"] == []
        assert v["board.cleanup"] == "PASS"
        reopen = [c for c in gh.calls if c["kind"] == "rest" and c["method"] == "PATCH"]
        assert reopen[0]["json"] == {"state": "open"}
        assert reopen[0]["url"].endswith("/issues/42")

    def test_existing_issue_is_reused_not_recreated(self):
        gh = FakeGitHub(existing_issue=True)
        probe.board_probe(_board(gh))
        assert not [c for c in gh.calls if c["kind"] == "rest" and c["method"] == "POST"]

    def test_board_not_found_fails_and_touches_nothing(self):
        gh = FakeGitHub(boards=[3])
        v = _verdicts(probe.board_probe(_board(gh)))
        assert v["board.detect"] == "FAIL"
        assert not [c for c in gh.calls if c["kind"] == "rest"]
        assert not [c for c in gh.calls if c.get("op") in ("AddItem", "DeleteItem")]

    def test_readback_mismatch_fails_status(self):
        gh = FakeGitHub(readback_wrong=True)
        v = _verdicts(probe.board_probe(_board(gh)))
        assert v["board.status.in_progress"] == "FAIL"
        assert v["board.cleanup"] == "PASS"

    def test_graphql_errors_surface_as_fail(self):
        class Errors(FakeGitHub):
            def _graphql(self, headers, body):
                super()._graphql(headers, body)
                return Resp(200, {"errors": [{"message": "Resource not accessible"}]})

        v = _verdicts(probe.board_probe(_board(Errors())))
        assert v["board.detect"] == "FAIL"

    def test_http_error_status_is_fail(self):
        class Http500(FakeGitHub):
            def _graphql(self, headers, body):
                super()._graphql(headers, body)
                return Resp(502, {"message": "bad gateway"})

        v = _verdicts(probe.board_probe(_board(Http500())))
        assert v["board.detect"] == "FAIL"

    def test_no_pat_reports_disabled(self):
        r = probe.board_probe(probe.Board(pat=None, app_token=lambda: APP_TOKEN, http=FakeGitHub()))
        assert {x.verdict for x in r} == {Verdict.FAIL}
        assert "not configured" in r[0].detail


# ---------------------------------------------------------------------------
# Inner: how probe_inner.py is started as fixer
# ---------------------------------------------------------------------------


class _Done:
    def __init__(self, stdout: str, returncode: int = 0, stderr: str = "") -> None:
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


class _SweepSandbox(FakeSandbox):
    def __init__(self, stdout: str, outcome: Outcome = Outcome.OK) -> None:
        super().__init__(stdout, outcome)
        self.paths = probe.default_paths()
        self.swept = 0

    def sweep(self) -> None:
        self.swept += 1


class TestInner:
    def test_sandbox_form_goes_through_the_sandbox(self):
        sb = _SweepSandbox('noise\n{"names": ["CI"]}\n')
        d = probe.Inner(sb).call("env")  # type: ignore[arg-type]
        assert d == {"names": ["CI"]}
        argv = sb.calls[0]["argv"]
        assert argv[:4] == [sb.paths.python, "-I", probe.INNER_SCRIPT, "env"]
        assert sb.calls[0]["cwd"] == probe.PROBE_ROOT

    def test_sandbox_form_without_output_raises(self):
        sb = _SweepSandbox("", outcome=Outcome.FAILED)
        with pytest.raises(probe.ProbeError):
            probe.Inner(sb).call("env")  # type: ignore[arg-type]

    def test_uid_form_drops_with_setpriv_without_srt_and_sweeps(self):
        sb = _SweepSandbox("")
        seen: dict[str, Any] = {}

        def _run(cmd, **kw):
            seen["cmd"] = cmd
            seen["env"] = kw["env"]
            return _Done('{"rc": 1}')

        d = probe.Inner(sb, run=_run).call("escalate", where="uid")  # type: ignore[arg-type]
        assert d == {"rc": 1}
        cmd = seen["cmd"]
        assert cmd[0] == sb.paths.setpriv
        assert cmd[1:6] == [
            "--reuid=10002",
            "--regid=10002",
            "--clear-groups",
            "--inh-caps=-all",
            "--no-new-privs",
        ]
        assert sb.paths.srt not in cmd
        assert cmd[-4:] == [sb.paths.python, "-I", probe.INNER_SCRIPT, "escalate"]
        assert set(seen["env"]) == {"PATH", "HOME", "LANG", "CI"}
        assert sb.swept == 1

    def test_uid_form_without_output_raises(self):
        sb = _SweepSandbox("")
        with pytest.raises(probe.ProbeError):
            probe.Inner(sb, run=lambda *a, **k: _Done("", 1, "setpriv: setresuid failed")).call(  # type: ignore[arg-type]
                "env", where="uid"
            )

    def test_unknown_where(self):
        with pytest.raises(ValueError):
            probe.Inner(_SweepSandbox("")).call("env", where="root")  # type: ignore[arg-type]

    def test_non_json_output_raises(self):
        with pytest.raises(probe.ProbeError):
            probe.Inner(_SweepSandbox("just text\n")).call("env")  # type: ignore[arg-type]


class TestSandboxChecks:
    def test_available_and_starts(self):
        class SB(_SweepSandbox):
            def check_available(self, mode):
                return None

        v = _verdicts(probe.sandbox_checks(SB("")))  # type: ignore[arg-type]
        assert v == {
            "sandbox.available.script": "PASS",
            "sandbox.available.cli": "PASS",
            "sandbox.starts": "PASS",
        }

    def test_unavailable(self):

        class SB(_SweepSandbox):
            def check_available(self, mode):
                raise SandboxUnavailable("sandbox srt is missing: /usr/bin/srt")

            def run(self, argv, **kw):
                raise SandboxUnavailable("sandbox srt is missing: /usr/bin/srt")

        v = _verdicts(probe.sandbox_checks(SB("")))  # type: ignore[arg-type]
        assert set(v.values()) == {"FAIL"}

    def test_bwrap_failure_is_fail(self):
        class SB(_SweepSandbox):
            def check_available(self, mode):
                return None

        r = {x.check: x for x in probe.sandbox_checks(SB("", outcome=Outcome.FAILED))}  # type: ignore[arg-type]
        assert r["sandbox.starts"].verdict is Verdict.FAIL


# ---------------------------------------------------------------------------
# build_checks / execute: wiring, secrets, the App token
# ---------------------------------------------------------------------------


def _all_ok_inner() -> FakeInner:
    return FakeInner(
        {
            ("net", "sandbox"): {"http": "blocked", "tcp": "blocked"},
            ("resolve", "sandbox"): {"addrs": ["127.0.0.1"], "hosts": ["127.0.0.1 localhost"]},
            ("tool", "sandbox"): {"rc": 0, "out": "ok"},
            ("proc", "sandbox"): {"environ": "unreadable:ENOENT", "mem": "unreadable:ENOENT"},
            ("proc", "uid"): {"environ": "unreadable:EACCES", "mem": "unreadable:EACCES"},
            ("env", "sandbox"): {"names": ["CI"]},
            ("env", "uid"): {"names": ["CI"]},
            ("ids", "sandbox"): DROPPED,
            ("ids", "uid"): DROPPED,
            ("escalate", "sandbox"): REFUSED,
            ("escalate", "uid"): REFUSED,
            ("userns", "uid"): USERNS_OK,
            ("write", "sandbox"): {"written": False},
            ("read", "sandbox"): {"readable": False},
            ("read", "uid"): {"readable": False},
            ("scan", "sandbox"): {"matches": 0, "files": 1},
            ("scan", "uid"): {"matches": 0, "files": 1},
            ("mkrepo", "sandbox"): {"ok": True, "dir": "/work/repo/probe-x"},
            ("refs", "sandbox"): {"refs": 0},
        }
    )


class TestBuildChecks:
    def _fetch(self, values: dict[str, str]):
        def _f(secret_id: str) -> str:
            if secret_id not in values:
                from credentials import CredentialError

                raise CredentialError("SECRET_UNAVAILABLE", f"no {secret_id}")
            return values[secret_id]

        return _f

    def test_groups_and_secrets_registered(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_VERSION", "2.1.309")
        secrets = SecretSet()
        sb = _SweepSandbox(
            _cli_json(
                [
                    {"tool_name": "Bash", "tool_input": {"command": "git push origin HEAD:main"}},
                    {"tool_name": "WebFetch", "tool_input": {}},
                ]
            )
        )
        groups = probe.build_checks(
            CONFIG,
            secrets,
            SUPABASE_KEY,
            sb=sb,
            inner=_all_ok_inner(),  # type: ignore[arg-type]
            fetch=self._fetch(
                {
                    CONFIG.anthropic_key_secret_id: ANTHROPIC_KEY,
                    str(CONFIG.projects_token_secret_id): PAT,
                }
            ),
            mint_app_token=lambda: APP_TOKEN,
            http=FakeGitHub(),
            wrapper_pid=77,
        )
        names = [g[0] for g in groups]
        assert names == [
            "setpriv",
            "sandbox",
            "userns",
            "net",
            "proc",
            "env",
            "noescalate",
            "policy",
            "cli.version",
            "cli",
            "board.pat_absent",
            "board",
            "board.disabled_without_pat",
        ]
        assert set(secrets.names()) == {"ANTHROPIC_API_KEY", "GITHUB_PROJECTS_TOKEN"}
        run = FakeRun()
        summary = probe.run_probe(groups, run, secrets)
        assert "GITHUB_APP_TOKEN" in secrets.names()  # minted lazily, then registered
        checks = {c["check"]: c["verdict"] for c in summary["checks"]}
        assert checks["board.detect"] == "PASS"
        assert checks["board.cleanup"] == "PASS"
        assert checks["cli.deny.git_push"] == "PASS"
        text = json.dumps(run.events) + json.dumps(summary)
        for secret in (ANTHROPIC_KEY, PAT, APP_TOKEN, SUPABASE_KEY):
            assert secret not in text

    def test_missing_secrets_fail_dependent_checks_only(self):
        secrets = SecretSet()
        groups = probe.build_checks(
            CONFIG,
            secrets,
            SUPABASE_KEY,
            sb=_SweepSandbox(""),
            inner=_all_ok_inner(),  # type: ignore[arg-type]
            fetch=self._fetch({}),
            mint_app_token=lambda: APP_TOKEN,
            http=FakeGitHub(),
            wrapper_pid=77,
        )
        summary = probe.run_probe(groups, FakeRun(), secrets)
        checks = {c["check"]: c for c in summary["checks"]}
        assert checks["cli.deny.git_push"]["verdict"] == "FAIL"
        assert checks["board.detect"]["verdict"] == "FAIL"
        assert "SECRET_UNAVAILABLE" in checks["board.detect"]["detail"]
        assert checks["proc.wrapper.uid"]["verdict"] == "PASS"
        assert secrets.names() == []

    def test_no_projects_secret_id(self):
        from dataclasses import replace

        cfg = replace(CONFIG, projects_token_secret_id=None)
        groups = probe.build_checks(
            cfg,
            SecretSet(),
            SUPABASE_KEY,
            sb=_SweepSandbox(""),
            inner=_all_ok_inner(),  # type: ignore[arg-type]
            fetch=self._fetch({}),
            http=FakeGitHub(),
            wrapper_pid=77,
        )
        board = dict(groups)["board"]()
        assert "not configured" in board[0].detail

    def test_default_app_token_uses_the_installation(self, monkeypatch):
        import credentials

        class Ctx:
            token = APP_TOKEN

        seen: dict[str, Any] = {}

        def _resolve(org, url, key):
            seen.update(org=org, url=url, key=key)
            return Ctx()

        monkeypatch.setattr(credentials, "resolve_github_credentials", _resolve)
        secrets = SecretSet()
        groups = probe.build_checks(
            CONFIG,
            secrets,
            SUPABASE_KEY,
            sb=_SweepSandbox(""),
            inner=_all_ok_inner(),  # type: ignore[arg-type]
            fetch=self._fetch({str(CONFIG.projects_token_secret_id): PAT}),
            http=FakeGitHub(),
            wrapper_pid=77,
        )
        dict(groups)["board"]()
        assert seen == {"org": "llipe", "url": CONFIG.supabase_url, "key": SUPABASE_KEY}
        assert "GITHUB_APP_TOKEN" in secrets.names()


class TestExecute:
    def test_execute_runs_build_checks_and_adds_versions(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_VERSION", "2.1.309")
        monkeypatch.setenv("SANDBOX_RUNTIME_VERSION", "0.0.81")
        monkeypatch.setattr(
            probe,
            "build_checks",
            lambda cfg, secrets, key: [("x", lambda: [CheckResult("x", Verdict.PASS, "")])],
        )
        run = FakeRun()
        summary = probe.execute(run, CONFIG, SecretSet(), SUPABASE_KEY)
        assert summary["versions"] == {"claude_code": "2.1.309", "sandbox_runtime": "0.0.81"}
        assert summary["summary"] == "probe: 1 PASS, 0 FAIL"
        assert run.events[0][0].startswith("probe mode")


class TestIsolatedChecks:
    """One broken sandbox call fails that check only; the uid-only checks still report."""

    def test_sandbox_failure_leaves_uid_checks_reported(self):
        from probe import ProbeError

        err = ProbeError("sandbox failed (exit 1): bwrap: No permissions to create a new namespace")
        answers: dict[tuple[str, str], Any] = {
            (sub, "sandbox"): err
            for sub in ("net", "tool", "proc", "env", "ids", "escalate", "write", "read", "scan")
        }
        answers.update(
            {
                ("proc", "uid"): {"environ": "unreadable:EACCES", "mem": "unreadable:EACCES"},
                ("env", "uid"): {"names": ["CI", "HOME", "LANG", "PATH"]},
                ("ids", "uid"): DROPPED,
                ("escalate", "uid"): REFUSED,
                ("read", "uid"): {"readable": False, "error": "EACCES"},
                ("scan", "uid"): {"matches": 0, "files": 9},
            }
        )
        inner = FakeInner(answers)

        results = (
            probe.net_checks(inner)
            + probe.proc_checks(inner, 7)
            + probe.env_checks(inner)
            + probe.setpriv_checks(inner, self_ids=lambda: ROOT_IDS)
            + probe.noescalate_checks(inner, which=lambda n: None, exists=lambda p: False)
            + probe.policy_checks(inner, _canary)
            + probe.pat_absent_checks(inner, PAT)
        )
        v = _verdicts(results)
        for name in (
            "proc.wrapper.uid",
            "env.fixer.uid",
            "setpriv.wrapper.root",
            "setpriv.drop.uid",
            "noescalate.fixer.uid",
            "noescalate.no_sudo",
            "secrets.dir.uid",
            "board.pat_absent.uid",
        ):
            assert v[name] == "PASS", name
        for name in (
            "net.blocked.example.com",
            "net.reachable.pypi.org",
            "proc.wrapper.sandbox",
            "env.fixer.sandbox",
            "setpriv.drop.sandbox",
            "noescalate.fixer.sandbox",
            "policy.tamper",
            "board.pat_absent.sandbox",
        ):
            assert v[name] == "FAIL", name
        bad = next(r for r in results if r.check == "proc.wrapper.sandbox")
        assert "bwrap" in bad.detail
        assert len(results) == len(v)  # one result per check name
