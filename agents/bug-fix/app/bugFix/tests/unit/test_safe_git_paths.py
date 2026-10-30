"""L1 tests for ``safe_git._safe_rel`` (QA-189-03, S-189 fix round): the path
rule every tree entry passes before ``materialize`` writes it, and every path
``remove`` and ``TreeReader`` accept.
"""

from __future__ import annotations

import pytest

from safe_git import _safe_rel, is_dotgit_component


@pytest.mark.parametrize(
    "path",
    [
        "src/app.py",
        "README",
        ".gitignore",
        ".github/workflows/ci.yml",
        "a/.gitmodules",
        "git",
        ".gitx",
        "x.git",
        "git~2",
        ".claude/agents/developer.md",
    ],
)
def test_ordinary_paths_are_safe(path):
    assert _safe_rel(path)


@pytest.mark.parametrize(
    "path",
    [
        "",
        "/abs",
        "a//b",
        "./a",
        "a/../b",
        "..",
        "a\0b",
        ".git",
        ".git/config",
        "sub/.git/hooks/pre-commit",
        ".GIT/config",
        ".Git",
        "a/.gIt",
        ".git.",  # NTFS drops trailing dots
        ".git. .",
        ".git ",  # and trailing spaces
        "git~1",  # the NTFS 8.3 short name of .git
        "GIT~1/config",
        ".g‌it",  # HFS+ ignores zero-width characters
        "﻿.git",
        ".git‍",
    ],
)
def test_unsafe_paths_are_refused(path):
    assert not _safe_rel(path)


@pytest.mark.parametrize(
    ("component", "expected"),
    [(".git", True), (".GiT", True), ("git~1", True), (".git..", True), (".github", False)],
)
def test_is_dotgit_component(component, expected):
    assert is_dotgit_component(component) is expected
