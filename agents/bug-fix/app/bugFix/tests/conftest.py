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


@pytest.fixture(autouse=True)
def _no_retry_waits(monkeypatch):
    """The shared GitHub client's retry waits never sleep in tests (S-185).

    A test that asserts the waits passes its own ``sleep`` to ``GitHubClient``;
    this only replaces the module default, so the suite stays fast while the
    retry policy runs for real.
    """
    try:
        import github_client
    except ImportError:  # pragma: no cover - before S-185's client exists
        return
    monkeypatch.setattr(github_client, "_sleep", lambda _seconds: None)
