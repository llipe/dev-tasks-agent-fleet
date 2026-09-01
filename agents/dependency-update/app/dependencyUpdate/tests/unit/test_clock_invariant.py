"""
Unit tests for the timeout-clock consistency invariant (issue #98, AC4).

The agent runs three families of timeout "clocks" that must be mutually
consistent so a long inner operation cannot outlive an outer bound and get the
container reclaimed mid-step (the root cause of #98):

    TOOL_COMMAND_TIMEOUT  <=  TEST_TIMEOUT
                          <=  IDLE_SESSION_TIMEOUT
                          <=  MAX_LIFETIME
                          <=  REAPER_THRESHOLD   (max_runtime_seconds + grace_seconds)

Additionally the heartbeat must fire comfortably below the container idle bound
(EC-2): a heartbeat that fires at or after the idle timeout never resets the
idle clock, so the "fix" would silently fail.

These tests are the SC-4 / RT-2 / EC-2 coverage from the test plan.
"""

from __future__ import annotations

import random

import pytest

from config import (
    HEARTBEAT_INTERVAL,
    IDLE_SESSION_TIMEOUT,
    MAX_LIFETIME,
    REAPER_THRESHOLD_SECONDS,
    TEST_TIMEOUT,
    TOOL_COMMAND_TIMEOUT,
    ClockConsistencyError,
    assert_clock_invariant,
)

_PROP_SEED = "98_0831"


class TestShippedConfigIsConsistent:
    """The values actually shipped in config.py must satisfy the invariant."""

    def test_default_configuration_is_internally_consistent(self):
        # Must not raise with the real shipped constants.
        assert_clock_invariant()

    def test_ordering_holds_for_shipped_values(self):
        assert TOOL_COMMAND_TIMEOUT <= TEST_TIMEOUT
        assert TEST_TIMEOUT <= IDLE_SESSION_TIMEOUT
        assert IDLE_SESSION_TIMEOUT <= MAX_LIFETIME
        assert MAX_LIFETIME <= REAPER_THRESHOLD_SECONDS

    def test_heartbeat_fires_safely_below_idle_bound(self):
        # EC-2: heartbeat interval must leave room for at least two beats
        # before the idle timeout — a single beat exactly at the boundary is
        # too late. We require interval <= idle / 2.
        assert HEARTBEAT_INTERVAL > 0
        assert HEARTBEAT_INTERVAL <= IDLE_SESSION_TIMEOUT / 2


class TestInvariantRejectsInconsistency:
    """assert_clock_invariant must fail loudly on any violated relation (SC-4)."""

    def test_test_timeout_exceeding_idle_bound_is_rejected(self):
        with pytest.raises(ClockConsistencyError):
            assert_clock_invariant(test_timeout=601, idle_session_timeout=300)

    def test_tool_timeout_exceeding_test_timeout_is_rejected(self):
        with pytest.raises(ClockConsistencyError):
            assert_clock_invariant(tool_command_timeout=700, test_timeout=600)

    def test_idle_exceeding_lifetime_is_rejected(self):
        with pytest.raises(ClockConsistencyError):
            assert_clock_invariant(idle_session_timeout=4000, max_lifetime=3600)

    def test_lifetime_exceeding_reaper_threshold_is_rejected(self):
        with pytest.raises(ClockConsistencyError):
            assert_clock_invariant(max_lifetime=4000, reaper_threshold_seconds=3720)

    def test_heartbeat_at_or_above_idle_bound_is_rejected(self):
        # EC-2: interval == idle bound must be rejected.
        with pytest.raises(ClockConsistencyError):
            assert_clock_invariant(heartbeat_interval=300, idle_session_timeout=300)
        with pytest.raises(ClockConsistencyError):
            assert_clock_invariant(heartbeat_interval=200, idle_session_timeout=300)

    def test_valid_custom_values_pass(self):
        # A fully consistent custom set must not raise.
        assert_clock_invariant(
            tool_command_timeout=60,
            test_timeout=120,
            idle_session_timeout=300,
            max_lifetime=600,
            reaper_threshold_seconds=720,
            heartbeat_interval=90,
        )


class TestClockInvariantProperty:
    """RT-2: property — the check accepts iff every relation holds."""

    def _holds(self, tool, test, idle, life, reaper, hb) -> bool:
        return tool <= test <= idle <= life <= reaper and 0 < hb <= idle / 2

    def test_accepts_iff_all_relations_hold(self):
        rng = random.Random(_PROP_SEED)
        for _ in range(300):
            tool = rng.randint(1, 1000)
            test = rng.randint(1, 1000)
            idle = rng.randint(1, 4000)
            life = rng.randint(1, 5000)
            reaper = rng.randint(1, 6000)
            hb = rng.randint(1, 2000)
            expected_ok = self._holds(tool, test, idle, life, reaper, hb)
            try:
                assert_clock_invariant(
                    tool_command_timeout=tool,
                    test_timeout=test,
                    idle_session_timeout=idle,
                    max_lifetime=life,
                    reaper_threshold_seconds=reaper,
                    heartbeat_interval=hb,
                )
                got_ok = True
            except ClockConsistencyError:
                got_ok = False
            assert got_ok == expected_ok, (
                f"seed={_PROP_SEED} tool={tool} test={test} idle={idle} "
                f"life={life} reaper={reaper} hb={hb} expected_ok={expected_ok}"
            )
