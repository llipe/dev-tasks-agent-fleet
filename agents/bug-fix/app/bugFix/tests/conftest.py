"""
Shared pytest configuration.

Auto-applies layer markers based on the test's directory, mirroring the
sibling agents, so ``pytest -m unit`` and ``pytest -m component`` work without
each test declaring its marker.
"""

from __future__ import annotations

import os

import pytest


def pytest_collection_modifyitems(config, items):
    """Tag tests under ``tests/unit/`` as ``unit`` and ``tests/component/`` as ``component``."""
    for item in items:
        path = str(item.fspath)
        if f"{os.sep}tests{os.sep}unit{os.sep}" in path:
            item.add_marker(pytest.mark.unit)
        elif f"{os.sep}tests{os.sep}component{os.sep}" in path:
            item.add_marker(pytest.mark.component)


class FakeClock:
    """A monotonic clock that only a ``sleep`` advances."""

    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start
        self.waits: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.waits.append(seconds)
        self.now += seconds


@pytest.fixture(autouse=True)
def _no_retry_waits(monkeypatch):
    """The shared GitHub client's retry waits never sleep in tests (S-185).

    The module defaults become one :class:`FakeClock`: a wait advances it
    instead of sleeping, so the wait budget (QA 5) runs for real and the suite
    stays fast. A test that asserts the waits passes its own ``sleep`` and
    ``clock`` to ``GitHubClient``.
    """
    try:
        import github_client
    except ImportError:  # pragma: no cover - before S-185's client exists
        return
    clock = FakeClock()
    monkeypatch.setattr(github_client, "_sleep", clock.sleep)
    monkeypatch.setattr(github_client, "_monotonic", clock)
