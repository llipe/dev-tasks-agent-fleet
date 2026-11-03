"""
The gate runner (spec §8.7; S-189; D-14, D-19, D-51).

Runs the repo's four blocking gates, ``test``, ``lint``, ``format``
(``format:check`` script or ``format-check`` target) and ``typecheck``, then
``audit``, each as ``fixer`` in the script sandbox (``sandbox.py``,
``Mode.SCRIPT``: ``srt`` behind the ``setpriv`` drop, registry-only network,
no Anthropic key). Every gate runs, whatever an earlier one returned.

Each result is ``{pass, exit_code, tail}`` plus the command and an outcome
(``ok``, ``failed``, ``timeout``, ``signaled``, ``not_found``,
``not_executable``, ``unavailable`` or, for a repo without ``audit``,
``skipped``). The tail is stdout then stderr, scrubbed of every known secret
and secret shape **before** it is cut to :data:`TAIL_CHARS` (``scrubber.tail``),
so it is safe for ``run_events``, the PR body and a comment.

On the **base** tree the results are evidence only: each is a ``run_event``
and the :class:`GateReport` is kept for the PR body; nothing here blocks
(D-14). On the **final** tree (S-192) the caller decides from
:attr:`GateReport.blocking_passed`. ``audit`` never blocks.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from sandbox import Mode, SandboxError, SandboxResult
from scrubber import SecretsLike, scrub_all, tail
from toolchain import AUDIT, GATE_ORDER, Toolchain

log = logging.getLogger("bug_fix.gates")

GATE_KEYS: tuple[str, ...] = GATE_ORDER
GATE_TIMEOUT_SECONDS = 600.0
TAIL_CHARS = 4000


class SandboxLike(Protocol):
    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: str,
        timeout: float,
        mode: Mode = ...,
        anthropic_api_key: str | None = ...,
        node: str | None = ...,
    ) -> SandboxResult: ...


@dataclass(frozen=True)
class GateResult:
    name: str  # logical: test, lint, format, typecheck or audit
    command: str
    passed: bool | None  # None: not run (a repo without audit)
    exit_code: int | None
    tail: str
    outcome: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "pass": self.passed,
            "exit_code": self.exit_code,
            "tail": self.tail,
            "command": self.command,
            "outcome": self.outcome,
        }


@dataclass(frozen=True)
class GateReport:
    phase: str  # "base" or "final"
    results: tuple[GateResult, ...]

    def result(self, name: str) -> GateResult:
        for r in self.results:
            if r.name == name:
                return r
        raise KeyError(name)

    @property
    def blocking(self) -> tuple[GateResult, ...]:
        return tuple(r for r in self.results if r.name in GATE_KEYS)

    @property
    def failed_blocking(self) -> tuple[GateResult, ...]:
        return tuple(r for r in self.blocking if not r.passed)

    @property
    def blocking_passed(self) -> bool:
        return not self.failed_blocking

    @property
    def audit(self) -> GateResult | None:
        try:
            return self.result(AUDIT)
        except KeyError:
            return None

    def to_dict(self) -> dict[str, dict[str, Any]]:
        return {r.name: r.to_dict() for r in self.results}


def _event(run: Any, level: str, message: str, data: dict[str, Any]) -> None:
    if run is None:
        return
    try:
        getattr(run, level)(message, **data)
    except Exception:  # noqa: BLE001 — a reporting fault never changes a gate result
        log.warning("gate event could not be reported")


def _run_one(
    sandbox: SandboxLike,
    toolchain: Toolchain,
    name: str,
    work_tree: str,
    secrets: SecretsLike,
    timeout: float,
    tail_chars: int,
) -> GateResult:
    if name == AUDIT and toolchain.audit is None:
        return GateResult(name, "", None, None, "", "skipped")
    argv = toolchain.gate_argv(name)
    command = " ".join(argv)
    try:
        res = sandbox.run(
            argv, cwd=work_tree, timeout=timeout, mode=Mode.SCRIPT, node=toolchain.node_version
        )
    except SandboxError as exc:
        return GateResult(
            name, command, False, None, tail(str(exc), secrets, tail_chars), "unavailable"
        )
    output = res.stdout
    if res.stderr:
        output = f"{output}\n{res.stderr}" if output else res.stderr
    return GateResult(
        name,
        command,
        res.ok,
        res.exit_code,
        tail(output, secrets, tail_chars),
        str(res.outcome),
    )


def run_gates(
    sandbox: SandboxLike,
    toolchain: Toolchain,
    work_tree: str,
    *,
    secrets: SecretsLike,
    phase: str = "base",
    run: Any = None,
    timeout: float = GATE_TIMEOUT_SECONDS,
    tail_chars: int = TAIL_CHARS,
) -> GateReport:
    """Run the four gates, then ``audit``, in ``work_tree``; report each one."""
    results: list[GateResult] = []
    for name in (*GATE_KEYS, AUDIT):
        result = _run_one(sandbox, toolchain, name, work_tree, secrets, timeout, tail_chars)
        results.append(result)
        if result.outcome == "skipped":
            verdict = "skipped (no audit script or target)"
        elif result.passed:
            verdict = "pass"
        else:
            verdict = f"fail ({result.outcome}, exit {result.exit_code})"
        level = "warn" if result.passed is False else "info"
        _event(
            run,
            level,
            scrub_all(f"{phase} gate {name}: {verdict}", secrets),
            {"gate": name, "phase": phase, **result.to_dict()},
        )
    return GateReport(phase, tuple(results))
