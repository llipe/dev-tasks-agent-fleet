"""L2 tests for the gate runner, ``gates.py`` (S-189 AC7, AC8; D-14, D-19).

The runner is driven against a stub sandbox (the story's Testing
Requirements): TC-189-11 (argv per stack, ``Mode.SCRIPT``, per-gate
``{pass, exit_code, tail}``), TC-189-12 (a scrubbed, bounded tail), TC-189-13
(base results in ``run_events``, kept for the PR body, never blocking).
"""

from __future__ import annotations

import json

import pytest

from gates import GATE_KEYS, TAIL_CHARS, GateReport, run_gates
from sandbox import Mode, SandboxUnavailable
from scrubber import SecretSet
from tests.component.repo_fixtures import StubSandbox, result
from tests.unit.test_toolchain import MK_OK, MapReader, js, py
from toolchain import check_repo_gate

SECRET = "sk-ant-api03-" + "S" * 40
PAT = "ghp_" + "Q" * 36
WORK = "/work/repo"


class FakeRun:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict]] = []

    def info(self, msg, **d):
        self.events.append(("info", msg, d))

    def warn(self, msg, **d):
        self.events.append(("warn", msg, d))

    def error(self, msg, **d):
        self.events.append(("error", msg, d))


def secrets() -> SecretSet:
    s = SecretSet()
    s.add("ANTHROPIC_API_KEY", SECRET)
    return s


def toolchain_for(files):
    gate = check_repo_gate(MapReader(files))
    assert gate.ok, gate.summary
    return gate.toolchain


# ---------------------------------------------------------------------------
# TC-189-11: argv per stack, as fixer, Mode.SCRIPT
# ---------------------------------------------------------------------------


class TestArgv:
    @pytest.mark.parametrize(
        ("files", "pm"),
        [(js(lock="pnpm-lock.yaml"), "pnpm"), (js(lock="package-lock.json"), "npm")],
    )
    def test_js_runs_pm_run_each_gate_then_audit(self, files, pm):
        sb = StubSandbox()
        report = run_gates(sb, toolchain_for(files), WORK, secrets=secrets())
        assert sb.argvs() == [
            (pm, "run", "test"),
            (pm, "run", "lint"),
            (pm, "run", "format:check"),
            (pm, "run", "typecheck"),
            (pm, "run", "audit"),
        ]
        assert [r.name for r in report.results] == [*GATE_KEYS, "audit"]

    def test_python_runs_make_targets(self):
        sb = StubSandbox()
        run_gates(sb, toolchain_for(py()), WORK, secrets=secrets())
        assert sb.argvs() == [
            ("make", "test"),
            ("make", "lint"),
            ("make", "format-check"),
            ("make", "typecheck"),
            ("make", "audit"),
        ]

    def test_every_gate_runs_in_the_script_sandbox_in_the_work_tree(self):
        sb = StubSandbox()
        run_gates(sb, toolchain_for(js()), WORK, secrets=secrets(), timeout=123)
        for call in sb.calls:
            assert call.mode is Mode.SCRIPT
            assert call.cwd == WORK
            assert call.timeout == 123
            # Repo scripts never get the Anthropic key (spec §8.7, D-51).
            assert call.anthropic_api_key is None

    def test_each_result_is_pass_exit_code_tail(self):
        sb = StubSandbox(
            answers={
                ("pnpm", "run", "test"): result(0, "5 passed\n"),
                ("pnpm", "run", "lint"): result(1, "", "lint: 2 errors\n"),
            }
        )
        report = run_gates(sb, toolchain_for(js()), WORK, secrets=secrets())
        data = report.to_dict()
        assert data["test"]["pass"] is True
        assert data["test"]["exit_code"] == 0
        assert "5 passed" in data["test"]["tail"]
        assert data["lint"] == {
            "pass": False,
            "exit_code": 1,
            "tail": data["lint"]["tail"],
            "command": "pnpm run lint",
            "outcome": "failed",
        }
        assert "lint: 2 errors" in data["lint"]["tail"]
        assert json.loads(json.dumps(data)) == data

    def test_missing_audit_is_recorded_as_skipped_and_never_run(self):
        scripts = {"test": "t", "lint": "l", "format:check": "f", "typecheck": "c"}
        sb = StubSandbox()
        report = run_gates(sb, toolchain_for(js(scripts)), WORK, secrets=secrets())
        assert ("pnpm", "run", "audit") not in sb.argvs()
        assert report.audit is not None
        assert report.audit.outcome == "skipped"
        assert report.audit.passed is None
        assert report.blocking_passed

    def test_a_timeout_is_a_failed_gate(self):
        sb = StubSandbox(answers={("make", "test"): result(None, timed_out=True)})
        report = run_gates(sb, toolchain_for(py()), WORK, secrets=secrets())
        test = report.result("test")
        assert test.passed is False
        assert test.outcome == "timeout"
        assert not report.blocking_passed

    def test_an_unavailable_sandbox_is_a_failed_gate_not_a_crash(self):
        sb = StubSandbox(answers={("make", "lint"): SandboxUnavailable(f"srt missing {SECRET}")})
        report = run_gates(sb, toolchain_for(py()), WORK, secrets=secrets())
        lint = report.result("lint")
        assert lint.passed is False
        assert lint.outcome == "unavailable"
        assert lint.exit_code is None
        assert SECRET not in lint.tail
        # The other gates still ran.
        assert len(sb.calls) == 5


# ---------------------------------------------------------------------------
# TC-189-12: the tail is scrubbed and bounded
# ---------------------------------------------------------------------------


class TestTail:
    def test_registered_secret_is_redacted(self):
        sb = StubSandbox(default=result(1, f"token={SECRET}\n", f"err {SECRET}\n"))
        report = run_gates(sb, toolchain_for(py()), WORK, secrets=secrets())
        for r in report.results:
            assert SECRET not in r.tail
            assert "***" in r.tail

    def test_unregistered_token_shape_is_redacted(self):
        sb = StubSandbox(default=result(0, f"leak {PAT}\n"))
        report = run_gates(sb, toolchain_for(py()), WORK, secrets=secrets())
        assert all(PAT not in r.tail for r in report.results)

    def test_tail_is_bounded_and_keeps_the_end(self):
        big = "x" * (TAIL_CHARS * 3) + "THE-END"
        sb = StubSandbox(default=result(1, big))
        report = run_gates(sb, toolchain_for(py()), WORK, secrets=secrets())
        tail = report.result("test").tail
        assert len(tail) <= TAIL_CHARS
        assert tail.endswith("THE-END")

    def test_secret_straddling_the_cut_leaves_no_fragment(self):
        out = "y" * 10 + SECRET + "z" * (TAIL_CHARS - 20)
        sb = StubSandbox(default=result(1, out))
        report = run_gates(sb, toolchain_for(py()), WORK, secrets=secrets())
        assert SECRET[-20:] not in report.result("test").tail

    def test_stderr_and_stdout_are_both_kept(self):
        sb = StubSandbox(default=result(1, "OUT-LINE\n", "ERR-LINE\n"))
        tail = run_gates(sb, toolchain_for(py()), WORK, secrets=secrets()).result("test").tail
        assert "OUT-LINE" in tail
        assert "ERR-LINE" in tail


# ---------------------------------------------------------------------------
# TC-189-13: base results land in run_events, are kept, and never block
# ---------------------------------------------------------------------------


class TestBaseResults:
    def test_red_base_test_does_not_stop_the_run(self):
        sb = StubSandbox(answers={("make", "test"): result(2, "1 failed\n")})
        run = FakeRun()
        report = run_gates(sb, toolchain_for(py()), WORK, secrets=secrets(), run=run)
        assert len(sb.calls) == 5  # every gate ran after the red test
        assert report.phase == "base"
        assert not report.blocking_passed
        assert [r.name for r in report.failed_blocking] == ["test"]

    def test_each_gate_is_a_run_event_with_its_result(self):
        sb = StubSandbox(
            answers={("make", "lint"): result(1, f"bad {SECRET}\n")},
        )
        run = FakeRun()
        run_gates(sb, toolchain_for(py()), WORK, secrets=secrets(), run=run)
        gate_events = [e for e in run.events if e[2].get("gate")]
        assert [e[2]["gate"] for e in gate_events] == [*GATE_KEYS, "audit"]
        lint = next(e for e in gate_events if e[2]["gate"] == "lint")
        assert lint[0] == "warn"
        assert lint[2]["phase"] == "base"
        assert lint[2]["pass"] is False
        assert lint[2]["exit_code"] == 1
        assert SECRET not in json.dumps(run.events)
        test = next(e for e in gate_events if e[2]["gate"] == "test")
        assert test[0] == "info"
        assert "base gate test: pass" in test[1]

    def test_the_report_is_kept_for_the_pr_body(self):
        sb = StubSandbox()
        report = run_gates(sb, toolchain_for(py()), WORK, secrets=secrets())
        assert isinstance(report, GateReport)
        data = report.to_dict()
        assert set(data) == {*GATE_KEYS, "audit"}
        assert data["format"]["command"] == "make format-check"

    def test_a_run_reporter_fault_never_changes_the_report(self):
        class Broken(FakeRun):
            def info(self, msg, **d):
                raise RuntimeError("supabase down")

            warn = info

        sb = StubSandbox()
        report = run_gates(sb, toolchain_for(py()), WORK, secrets=secrets(), run=Broken())
        assert report.blocking_passed

    def test_final_phase_label(self):
        run = FakeRun()
        run_gates(
            StubSandbox(), toolchain_for(py()), WORK, secrets=secrets(), run=run, phase="final"
        )
        assert any("final gate test: pass" in e[1] for e in run.events)


def test_python_without_audit_target():
    tc = toolchain_for(py(MK_OK.replace("audit:\n\t@true\n", "")))
    sb = StubSandbox()
    report = run_gates(sb, tc, WORK, secrets=secrets())
    assert ("make", "audit") not in sb.argvs()
    assert report.to_dict()["audit"]["pass"] is None
