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
