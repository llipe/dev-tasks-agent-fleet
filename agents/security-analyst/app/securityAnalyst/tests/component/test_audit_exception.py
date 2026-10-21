"""Component tests for the time-boxed pip-audit exception (issue #355).

The ``audit`` Makefile target temporarily ignores CVE-2026-59951 (``mcp``
1.29.0, pinned exactly by semgrep). The exception MUST expire after
``AUDIT_EXCEPTION_EXPIRES`` (UTC, inclusive) and MUST fail closed when the
expiry or the resolved date is missing or malformed (AC-2a).

These tests drive the real ``make`` targets via ``subprocess.run`` but never
run the real pip-audit: a stub ``pip-audit`` is placed first on ``PATH`` to
record its arguments, so the suite stays offline (TESTING.md: no network).

Delete this file together with the exception when #360 is resolved.
Test plan: workstream/archive/test-plan-issue-355.md.
"""

from __future__ import annotations

import os
import random
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

PKG_DIR = Path(__file__).resolve().parents[2]
CVE = "CVE-2026-59951"
DEFAULT_EXPIRY = "20261026"
SEED = 355  # RT-1 replay seed — keep stable so failures reproduce.

_VALID = re.compile(r"[0-9]{8}")

pytestmark = pytest.mark.skipif(shutil.which("make") is None, reason="requires make")


def _make(target: str, *overrides: str, path_prefix: Path | None = None):
    env = {**os.environ, "LC_ALL": "C"}
    # The Makefile's `AUDIT_TODAY ?=` must not pick up a value from the
    # caller's environment; tests pass it explicitly as a make override.
    env.pop("AUDIT_TODAY", None)
    env.pop("AUDIT_EXCEPTION_EXPIRES", None)
    if path_prefix is not None:
        env["PATH"] = f"{path_prefix}{os.pathsep}{env['PATH']}"
    return subprocess.run(
        ["make", "-s", target, *overrides],
        cwd=PKG_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _check(*overrides: str):
    return _make("audit-exception-check", *overrides)


@pytest.fixture
def stub_pip_audit(tmp_path: Path):
    """A fake ``pip-audit`` that records its argv and exits with $STUB_EXIT."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "pip-audit.args"
    stub = bindir / "pip-audit"
    stub.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > "{log}"\nexit "${{STUB_EXIT:-0}}"\n')
    stub.chmod(0o755)
    return bindir, log


# --- AC-2: expiry boundary (inclusive, UTC) --------------------------------


def test_last_valid_day_passes():  # E2E-2a
    result = _check(f"AUDIT_TODAY={DEFAULT_EXPIRY}")
    assert result.returncode == 0, result.stdout + result.stderr


def test_first_day_after_expiry_fails_with_actionable_message():  # E2E-2c
    result = _check("AUDIT_TODAY=20261027")
    out = result.stdout + result.stderr
    assert result.returncode != 0
    assert CVE in out
    assert f"expired on {DEFAULT_EXPIRY}" in out
    assert "#360" in out


def test_default_date_uses_real_utc_clock():  # E2E-2g (date-independent)
    today = datetime.now(UTC).strftime("%Y%m%d")
    result = _check()
    assert (result.returncode == 0) == (today <= DEFAULT_EXPIRY), result.stdout


# --- AC-2a: fail closed on malformed input ---------------------------------


@pytest.mark.parametrize(
    "value",
    ["", "2026-10-26", "abc", "2026102", "202610260", "-1", "2026102a"],
)
def test_malformed_expiry_fails_closed(value: str):  # E2E-2d/2e/2f
    result = _check(f"AUDIT_EXCEPTION_EXPIRES={value}", "AUDIT_TODAY=20200101")
    assert result.returncode != 0
    assert "invalid AUDIT_EXCEPTION_EXPIRES" in result.stdout + result.stderr


@pytest.mark.parametrize("value", ["", "abc", "2026-10-20"])
def test_malformed_today_fails_closed(value: str):
    result = _check(f"AUDIT_TODAY={value}")
    assert result.returncode != 0
    assert "could not determine UTC date" in result.stdout + result.stderr


# --- AC-1 / AC-2 / CT-2: the audit target itself (stubbed pip-audit) -------


def test_audit_ignores_only_the_one_cve(stub_pip_audit):  # E2E-1b
    bindir, log = stub_pip_audit
    result = _make("audit", f"AUDIT_TODAY={DEFAULT_EXPIRY}", path_prefix=bindir)
    assert result.returncode == 0, result.stdout + result.stderr
    assert log.read_text().split() == [".", "--strict", "--ignore-vuln", CVE]


def test_expired_exception_never_runs_pip_audit(stub_pip_audit):  # E2E-2b
    bindir, log = stub_pip_audit
    result = _make("audit", "AUDIT_EXCEPTION_EXPIRES=20200101", path_prefix=bindir)
    out = result.stdout + result.stderr
    assert result.returncode != 0
    assert "20200101" in out and "#360" in out
    assert not log.exists()


def test_audit_propagates_pip_audit_failure(stub_pip_audit, monkeypatch):  # CT-2
    bindir, _ = stub_pip_audit
    monkeypatch.setenv("STUB_EXIT", "1")
    result = _make("audit", f"AUDIT_TODAY={DEFAULT_EXPIRY}", path_prefix=bindir)
    assert result.returncode != 0


# --- RT-1: property — passes iff both values valid and today <= expiry -----


def _random_value(rng: random.Random, anchor: int) -> str:
    if rng.random() < 0.6:
        return str(anchor + rng.randint(-3, 3))
    return rng.choice(
        [
            "",
            f"{anchor}"[:4] + "-" + f"{anchor}"[4:6] + "-" + f"{anchor}"[6:],
            str(anchor)[:7],
            str(anchor) + "0",
            "abcdefgh",
            f"{anchor} ",
            "-1",
        ]
    )


def _oracle(today: str, expires: str) -> bool:
    # make strips leading whitespace from command-line values (observed while
    # checking SG-1), so mirror that before validating.
    today, expires = today.lstrip(), expires.lstrip()
    return bool(_VALID.fullmatch(today) and _VALID.fullmatch(expires) and today <= expires)


def test_property_fail_closed_predicate():  # RT-1
    rng = random.Random(SEED)
    anchor = int(DEFAULT_EXPIRY)
    for i in range(100):
        today, expires = _random_value(rng, anchor), _random_value(rng, anchor)
        result = _check(f"AUDIT_TODAY={today}", f"AUDIT_EXCEPTION_EXPIRES={expires}")
        assert (result.returncode == 0) == _oracle(today, expires), (
            f"seed={SEED} case={i} today={today!r} expires={expires!r}: {result.stdout}"
        )
