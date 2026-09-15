"""
Shared pytest configuration.

Auto-applies layer markers based on the test's directory, mirroring the
sibling agent's (dependency-update) convention, so the canonical
``pytest -m unit`` / ``pytest -m component`` selectors work without each test
declaring the marker by hand.
"""

from __future__ import annotations

import os

import pytest


def pytest_collection_modifyitems(config, items):
    """Auto-apply layer markers based on the test's directory.

    Tests under ``tests/unit/`` get the ``unit`` marker and those under
    ``tests/component/`` get ``component``.
    """
    for item in items:
        path = str(item.fspath)
        if f"{os.sep}tests{os.sep}unit{os.sep}" in path:
            item.add_marker(pytest.mark.unit)
        elif f"{os.sep}tests{os.sep}component{os.sep}" in path:
            item.add_marker(pytest.mark.component)
