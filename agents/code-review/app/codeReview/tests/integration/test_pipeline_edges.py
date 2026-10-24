"""
S-213 edge cases beyond the test plan rows (Layer 2, same harness).

- A blocking phase that outlives the deadline in real time is abandoned at the
  deadline: ``RUN_TIMEOUT``, the failure comment on a fresh client, and the
  abandoned worker's late ``warn`` events dropped (D-32: the deadline bounds
  each step, not only the step boundaries).
- A comment over the size limit is truncated by the renderer, and the run
  records ``comment_truncated`` and a ``warn`` event naming the stages (§13).
- Late reclassification: a reviewed file whose content turns out binary leaves
  nothing to review (DF-16 path, after the fetch).
- The final scrub catches a secret in a path, which the renderer shows inside a
  code span rather than escaped.
- ``main.invoke`` still ends the run if the pipeline itself raises.
"""

from __future__ import annotations

import time

import pytest

import main
from render import MAX_COMMENT_CHARS
from tests.helpers.pipeline_run import (
    COMPARE_PATH,
    HEAD,
    MERGE_BASE,
    PULL_PATH,
    RUN_URL,
    START,
    TOKEN,
    Harness,
    blocking,
    file_entry,
    review,
)


@pytest.fixture
def h(monkeypatch) -> Harness:
    return Harness(monkeypatch)


class _StuckTransport:
    """``GET pull`` leaves 0.2 s before the deadline; ``compare`` then blocks for ``hold``."""

    def __init__(self, inner, clock, deadline, hold):
        self.inner, self.clock, self.deadline, self.hold = inner, clock, deadline, hold

    def request(self, method, url, **kw):
        if url.endswith(PULL_PATH):
            self.clock.now = self.deadline - 0.2
        if url.endswith(COMPARE_PATH):
            time.sleep(self.hold)
        return self.inner.request(method, url, **kw)


def test_a_stuck_phase_is_abandoned_at_the_deadline(h, monkeypatch):
    import dataclasses
    import functools

    from github_client import GitHubClient

    transport = _StuckTransport(h.stub, h.clock, START + 900 - 60, hold=1.0)
    deps = h.deps
    monkeypatch.setattr(
        h,
        "deps",
        lambda: dataclasses.replace(
            deps(),
            make_github=functools.partial(GitHubClient, transport=transport, sleep=lambda s: None),
        ),
    )
    result = h.drive()

    assert result["error_code"] == "RUN_TIMEOUT"
    assert h.posts() == [f"Code review failed (`RUN_TIMEOUT`). [run]({RUN_URL})\n"]
    assert h.fake.calls == 0
    assert h.reporter.step_keys() == ["load_pr", "context"]
    # Abandoned at the deadline, not at the phase's end: the failure comment went
    # out while the stuck compare was still blocked (it is recorded after the sleep).
    order = [(c.method, c.path) for c in h.stub.calls]
    post = next(i for i, (m, _p) in enumerate(order) if m == "POST")
    compare = order.index(("GET", COMPARE_PATH))
    assert post < compare
    # The worker kept going after it was abandoned (it reads #40, a PR, and would
    # warn), but its events are dropped: the run is already failed.
    assert not [e for e in h.reporter.events() if e["message"] == "linked issue skipped"]


def test_a_truncated_comment_is_recorded_and_warned(h):
    findings = [
        blocking(
            rank=k + 1,
            title=f"T{k} " + "t" * 190,
            failure_scenario="s" * 1500,
            consequence="c" * 500,
        )
        for k in range(40)
    ]
    h.fake.push(review(findings))
    h.drive()

    body = h.posts()[0]
    assert len(body) <= MAX_COMMENT_CHARS
    metrics = h.reporter.terminal["metrics"]
    assert metrics["comment_truncated"] is True
    assert metrics["comment_chars"] == len(body)
    warns = [e for e in h.reporter.events() if e["message"] == "review comment truncated"]
    assert len(warns) == 1
    assert warns[0]["data"]["stages"]
    assert h.reporter.artifacts()[0]["metadata"]["findings"][39]["id"] == "B40"


def test_late_binary_content_leaves_nothing_to_review(h):
    h.set_files([file_entry("src/app.py", additions=1, deletions=1)])
    h.set_content("src/app.py", HEAD, "PNG\x00\x00binary")
    h.set_content("src/app.py", MERGE_BASE, "PNG\x00binary")
    result = h.drive()

    assert (result["status"], result["outcome"]) == ("succeeded", "not_applicable")
    assert h.fake.calls == 0
    body = h.posts()[0]
    assert body.startswith("Nothing to review")
    assert "`src/app.py` (no text diff)" in body
    assert h.reporter.step_keys() == ["load_pr", "context", "post"]


def test_a_secret_in_a_path_is_scrubbed_from_the_note(h):
    h.set_files([file_entry(f"vendor/{TOKEN}/uv.lock", 1, 1)])
    h.drive()
    body = h.posts()[0]
    assert TOKEN not in body
    assert "INSTALLATIONtoken" not in body
    assert "***" in body


def test_invoke_ends_the_run_if_the_pipeline_raises(h, monkeypatch):
    class Broken:
        def __init__(self, *a, **k):
            pass

        async def run(self):
            raise RuntimeError("pipeline defect")
            yield  # pragma: no cover - makes this an async generator

    monkeypatch.setattr(main, "Pipeline", Broken)
    result = h.drive()
    assert result["error_code"] == "INTERNAL_ERROR"
    assert h.reporter.terminal["status"] == "failed"
    assert h.reporter.terminal["error_code"] == "INTERNAL_ERROR"
