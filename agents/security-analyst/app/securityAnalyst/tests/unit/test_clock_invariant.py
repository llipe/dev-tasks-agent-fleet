"""
Unit tests for the timeout-clock consistency invariant (spec S9.2, PRD AC31 groundwork).

security-analyst inherits the sibling agent's (dependency-update, ADR-006 /
issue #98) heartbeat/clock-invariant mechanism wholesale, but recomputes the
invariant chain for its own, higher bounds (PRD S12.3):

    FIX_COMMAND_TIMEOUT  <=  SCANNER_TIMEOUT
                         <=  IDLE_SESSION_TIMEOUT
                         <=  MAX_LIFETIME
                         <=  REAPER_THRESHOLD_SECONDS  (MAX_LIFETIME + grace_seconds)

and 0 < HEARTBEAT_INTERVAL <= IDLE_SESSION_TIMEOUT / 2.

Mirrors dependency-update's ``test_clock_invariant.py`` structure (same test
classes/shape), scoped to this agent's own constant names.
"""

from __future__ import annotations

import random

import pytest

from config import (
    FIX_COMMAND_TIMEOUT,
    HEARTBEAT_INTERVAL,
    IDLE_SESSION_TIMEOUT,
    MAX_LIFETIME,
    REAPER_THRESHOLD_SECONDS,
    SCANNER_TIMEOUT,
    ClockConsistencyError,
    assert_clock_invariant,
)

_PROP_SEED = "S125_0915"


class TestShippedConfigIsConsistent:
    """The values actually shipped in config.py must satisfy the invariant."""

    def test_default_configuration_is_internally_consistent(self):
        # Must not raise with the real shipped constants.
        assert_clock_invariant()

    def test_ordering_holds_for_shipped_values(self):
        assert FIX_COMMAND_TIMEOUT <= SCANNER_TIMEOUT
        assert SCANNER_TIMEOUT <= IDLE_SESSION_TIMEOUT
        assert IDLE_SESSION_TIMEOUT <= MAX_LIFETIME
        assert MAX_LIFETIME <= REAPER_THRESHOLD_SECONDS

    def test_shipped_values_match_prd_12_3(self):
        # PRD S12.3's own numbers, pinned so a silent drift is caught.
        assert SCANNER_TIMEOUT == 600
        assert FIX_COMMAND_TIMEOUT == 180
        assert IDLE_SESSION_TIMEOUT == 900
        assert MAX_LIFETIME == 5400
        assert HEARTBEAT_INTERVAL == 120
        assert REAPER_THRESHOLD_SECONDS == MAX_LIFETIME + 120

    def test_heartbeat_fires_safely_below_idle_bound(self):
        # Heartbeat interval must leave room for at least two beats before the
        # idle timeout — a single beat exactly at the boundary is too late.
        assert HEARTBEAT_INTERVAL > 0
        assert HEARTBEAT_INTERVAL <= IDLE_SESSION_TIMEOUT / 2


class TestInvariantRejectsInconsistency:
    """assert_clock_invariant must fail loudly on any violated relation."""

    def test_scanner_timeout_exceeding_idle_bound_is_rejected(self):
        with pytest.raises(ClockConsistencyError):
            assert_clock_invariant(scanner_timeout=901, idle_session_timeout=900)

    def test_fix_command_timeout_exceeding_scanner_timeout_is_rejected(self):
        with pytest.raises(ClockConsistencyError):
            assert_clock_invariant(fix_command_timeout=700, scanner_timeout=600)

    def test_idle_exceeding_lifetime_is_rejected(self):
        with pytest.raises(ClockConsistencyError):
            assert_clock_invariant(idle_session_timeout=6000, max_lifetime=5400)

    def test_lifetime_exceeding_reaper_threshold_is_rejected(self):
        with pytest.raises(ClockConsistencyError):
            assert_clock_invariant(max_lifetime=6000, reaper_threshold_seconds=5520)

    def test_heartbeat_at_or_above_idle_bound_is_rejected(self):
        with pytest.raises(ClockConsistencyError):
            assert_clock_invariant(heartbeat_interval=300, idle_session_timeout=300)
        with pytest.raises(ClockConsistencyError):
            assert_clock_invariant(heartbeat_interval=200, idle_session_timeout=300)

    def test_deliberately_misordered_constant_fails_fast(self):
        # PRD AC31 groundwork (task 1.13): a deliberately misordered constant
        # (MAX_LIFETIME below IDLE_SESSION_TIMEOUT) must raise immediately.
        with pytest.raises(ClockConsistencyError):
            assert_clock_invariant(idle_session_timeout=5400, max_lifetime=900)

    def test_valid_custom_values_pass(self):
        assert_clock_invariant(
            fix_command_timeout=60,
            scanner_timeout=120,
            idle_session_timeout=300,
            max_lifetime=600,
            reaper_threshold_seconds=720,
            heartbeat_interval=90,
        )


class TestClockInvariantProperty:
    """Property: the check accepts iff every relation holds."""

    def _holds(self, fix, scan, idle, life, reaper, hb) -> bool:
        return fix <= scan <= idle <= life <= reaper and 0 < hb <= idle / 2

    def test_accepts_iff_all_relations_hold(self):
        rng = random.Random(_PROP_SEED)
        for _ in range(300):
            fix = rng.randint(1, 1000)
            scan = rng.randint(1, 1000)
            idle = rng.randint(1, 4000)
            life = rng.randint(1, 6000)
            reaper = rng.randint(1, 7000)
            hb = rng.randint(1, 2000)
            expected_ok = self._holds(fix, scan, idle, life, reaper, hb)
            try:
                assert_clock_invariant(
                    fix_command_timeout=fix,
                    scanner_timeout=scan,
                    idle_session_timeout=idle,
                    max_lifetime=life,
                    reaper_threshold_seconds=reaper,
                    heartbeat_interval=hb,
                )
                got_ok = True
            except ClockConsistencyError:
                got_ok = False
            assert got_ok == expected_ok, (
                f"seed={_PROP_SEED} fix={fix} scan={scan} idle={idle} "
                f"life={life} reaper={reaper} hb={hb} expected_ok={expected_ok}"
            )
