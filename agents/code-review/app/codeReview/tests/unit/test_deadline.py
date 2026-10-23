"""
S-213 AC8 — the run deadline and the heartbeat (D-32, spec §8.9; TC-213-17, TC-213-18).

The deadline is ``start + run_timeout_seconds - 60`` on the injected monotonic
clock and bounds every step: it is checked before each step and when each
blocking phase returns, and ``bounded`` stops waiting for a blocking phase at
the deadline in real time. Reaching it ends the run ``failed``/``RUN_TIMEOUT``
with a failure comment, posted inside the 60 s reserve. The heartbeat wraps the
GitHub fetches (``load_pr``, ``context``) and the Converse call (``review``),
never ``validate`` or ``post``.

The pipeline cases drive ``main.invoke`` with the L2 harness (fakes only, no
network); they sit here because they pin the deadline contract.
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest
from botocore.exceptions import ReadTimeoutError

from bedrock_adapter import MAX_READ_TIMEOUT_SECONDS, call_timeouts
from config import DEADLINE_RESERVE_SECONDS
from heartbeat import HeartbeatResult, is_heartbeat_chunk, run_with_heartbeat
from pipeline import RunTimeout, bounded, run_deadline
from tests.helpers.pipeline_run import (
    COMPARE_PATH,
    RUN_URL,
    START,
    Harness,
    review,
)

# ---------------------------------------------------------------------------
# run_deadline
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("timeout", "deadline"), [(900, 1_840.0), (120, 1_060.0), (600, 1_540.0)])
def test_deadline_is_start_plus_timeout_minus_reserve(timeout, deadline):
    assert DEADLINE_RESERVE_SECONDS == 60
    assert run_deadline(1_000.0, timeout) == deadline


# ---------------------------------------------------------------------------
# bounded: heartbeat + deadline around one blocking phase
# ---------------------------------------------------------------------------


def _collect(agen):
    async def _go():
        return [item async for item in agen]

    return asyncio.run(_go())


def test_bounded_returns_the_value_last():
    items = _collect(
        bounded(lambda: 42, deadline=time.monotonic() + 30, clock=time.monotonic, interval=5)
    )
    assert isinstance(items[-1], HeartbeatResult)
    assert items[-1].value == 42
    assert all(is_heartbeat_chunk(i) for i in items[:-1])


def test_bounded_yields_heartbeats_while_the_phase_runs():
    def slow():
        time.sleep(0.12)
        return "done"

    items = _collect(
        bounded(slow, deadline=time.monotonic() + 30, clock=time.monotonic, interval=0.02)
    )
    beats = [i for i in items if is_heartbeat_chunk(i)]
    assert beats, "a phase longer than the interval must emit heartbeats"
    assert items[-1].value == "done"


def test_bounded_reraises_the_phase_error():
    def boom():
        raise ValueError("phase failed")

    with pytest.raises(ValueError, match="phase failed"):
        _collect(bounded(boom, deadline=time.monotonic() + 30, clock=time.monotonic, interval=5))


def test_bounded_refuses_to_start_past_the_deadline():
    called = []
    with pytest.raises(RunTimeout):
        _collect(
            bounded(
                lambda: called.append(1),
                deadline=time.monotonic() - 1,
                clock=time.monotonic,
                interval=5,
            )
        )
    assert called == []


def test_bounded_stops_waiting_at_the_deadline():
    """A phase that outlives the deadline is abandoned at the deadline, not at its end."""
    release = threading.Event()

    def stuck():
        release.wait(5)
        return "late"

    async def _go():
        start = time.monotonic()
        try:
            async for _ in bounded(
                stuck, deadline=start + 0.15, clock=time.monotonic, interval=0.05
            ):
                pass
        except RunTimeout:
            return time.monotonic() - start
        finally:
            release.set()
        raise AssertionError("expected RunTimeout")

    elapsed = asyncio.run(_go())
    assert 0.1 <= elapsed < 2.0


def test_bounded_uses_the_injected_heartbeat():
    seen = []

    def spy(fn, *, interval, seq_start=0):
        seen.append(interval)
        return run_with_heartbeat(fn, interval=interval, seq_start=seq_start)

    items = _collect(
        bounded(
            lambda: 1,
            deadline=time.monotonic() + 30,
            clock=time.monotonic,
            interval=7,
            heartbeat=spy,
        )
    )
    assert seen == [7]
    assert items[-1].value == 1


# ---------------------------------------------------------------------------
# The pipeline under the deadline (TC-213-17)
# ---------------------------------------------------------------------------


@pytest.fixture
def h(monkeypatch) -> Harness:
    return Harness(monkeypatch)


def _failed_with_run_timeout(h: Harness, result: dict) -> None:
    assert result["status"] == "failed"
    assert result["error_code"] == "RUN_TIMEOUT"
    assert h.reporter.terminal["status"] == "failed"
    assert h.reporter.terminal["error_code"] == "RUN_TIMEOUT"
    posts = h.posts()
    assert len(posts) == 1, "exactly the failure comment, no review comment"
    assert posts[0] == f"Code review failed (`RUN_TIMEOUT`). [run]({RUN_URL})\n"


def test_deadline_hit_during_converse_ends_run_timeout(h):
    deadline = START + 900 - 60

    def slow_call(_request):
        h.clock.now = deadline + 5  # the call outlives the deadline
        raise ReadTimeoutError(endpoint_url="https://bedrock-runtime.us-east-1.amazonaws.com")

    h.fake.push(slow_call)
    result = h.drive()

    _failed_with_run_timeout(h, result)
    assert h.fake.calls == 1
    # The call was sized from the time left, and never past min(600, remaining).
    remaining = deadline - START
    kwargs = h.bedrock_factory_calls[0]
    expected = call_timeouts(remaining)
    assert expected is not None
    assert kwargs["read_timeout_seconds"] == expected.read
    assert kwargs["read_timeout_seconds"] <= min(MAX_READ_TIMEOUT_SECONDS, remaining)
    assert h.reporter.step_keys() == ["load_pr", "context", "review"]


def test_converse_returning_after_the_deadline_is_run_timeout(h):
    def late(_request):
        h.clock.advance(900)
        return review()

    h.fake.push(late)
    result = h.drive()

    _failed_with_run_timeout(h, result)
    assert "validate" not in h.reporter.step_keys()
    assert h.reporter.artifacts() == []


def test_failure_comment_is_posted_inside_the_reserve(h):
    """Past the deadline, the failure comment still goes out (the 60 s reserve)."""

    def late(_request):
        h.clock.now = START + 900 - 30  # inside the reserve, past the deadline
        return review()

    h.fake.push(late)
    result = h.drive()
    _failed_with_run_timeout(h, result)


class _ClockTransport:
    """Advances the clock when a given path is requested, then delegates."""

    def __init__(self, inner, clock, path, seconds):
        self.inner, self.clock, self.path, self.seconds = inner, clock, path, seconds

    def request(self, method, url, **kw):
        if url.endswith(self.path):
            self.clock.advance(self.seconds)
        return self.inner.request(method, url, **kw)


@pytest.mark.parametrize(("timeout", "advance"), [(900, 841), (120, 61)])
def test_deadline_reached_during_the_context_fetch(h, monkeypatch, timeout, advance):
    transport = _ClockTransport(h.stub, h.clock, COMPARE_PATH, advance)
    deps = h.deps
    monkeypatch.setattr(
        h,
        "deps",
        lambda: _with_transport(deps(), transport),
    )
    result = h.drive({"pr_number": 42, "run_timeout_seconds": timeout})

    _failed_with_run_timeout(h, result)
    assert h.fake.calls == 0
    assert h.reporter.step_keys() == ["load_pr", "context"]


def test_time_short_of_the_deadline_is_not_a_timeout(h, monkeypatch):
    transport = _ClockTransport(h.stub, h.clock, COMPARE_PATH, 500)
    deps = h.deps
    monkeypatch.setattr(h, "deps", lambda: _with_transport(deps(), transport))
    h.fake.push(review())
    result = h.drive()
    assert result["status"] == "succeeded"


def _with_transport(deps, transport):
    import dataclasses
    import functools

    from github_client import GitHubClient

    return dataclasses.replace(
        deps, make_github=functools.partial(GitHubClient, transport=transport, sleep=lambda s: None)
    )


# ---------------------------------------------------------------------------
# The heartbeat (TC-213-18)
# ---------------------------------------------------------------------------


def test_heartbeat_wraps_the_fetch_and_converse_steps_only(h):
    h.fake.push(review())
    result = h.drive()
    assert result["status"] == "succeeded"
    assert h.heartbeat_steps == ["load_pr", "context", "review"]
    assert h.reporter.step_keys() == ["load_pr", "context", "review", "validate", "post"]


def test_heartbeat_chunks_reach_the_entrypoint_stream(h):
    h.heartbeat_interval = 0.01

    def slow(_request):
        time.sleep(0.1)
        return review()

    h.fake.push(slow)
    result = h.drive()
    assert result["status"] == "succeeded"
    assert h.heartbeat_chunks, "heartbeats must be yielded through invoke"
    assert not is_heartbeat_chunk(h.chunks[-1]), "the terminal chunk is last"
