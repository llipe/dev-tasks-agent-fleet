"""
PRD v1.4 FR-5 and FR-35 — file tiers, tiered full-file drops, docs-only PRs (D-61, D-62).

Full files are dropped documentation first, then tests, then source; within a
tier, the selection call's ranking orders the files, else largest is dropped
first. A PR whose every changed file is documentation or an image is not
reviewed; any other file, a shell script included, is.
"""

from __future__ import annotations

import pytest

from budget import BLOCK_FILE, FillGroups, Piece, fill, full_file_order
from context.diff import (
    TIER_DOC,
    TIER_SOURCE,
    TIER_TEST,
    file_tier,
    is_doc_path,
    is_docs_only,
)


@pytest.mark.parametrize(
    ("path", "tier"),
    [
        ("modules/offer/src/offer.facade.ts", TIER_SOURCE),
        ("packages/contracts/src/offer.ts", TIER_SOURCE),
        ("scripts/rollback.sh", TIER_SOURCE),
        ("README.md", TIER_DOC),
        ("workstream/audit-gc08.md", TIER_DOC),
        ("docs/architecture/diagram.py", TIER_DOC),
        ("docs/guide.MDX", TIER_DOC),
        ("notes.txt", TIER_DOC),
        ("manual.adoc", TIER_DOC),
        ("api.rst", TIER_DOC),
        ("CHANGES.markdown", TIER_DOC),
        ("src/docs/helper.ts", TIER_SOURCE),
        ("tests/unit/test_x.py", TIER_TEST),
        ("test/helper.js", TIER_TEST),
        ("src/__tests__/a.tsx", TIER_TEST),
        ("src/offer.test.ts", TIER_TEST),
        ("src/offer.spec.ts", TIER_TEST),
        ("pkg/test_utils.py", TIER_TEST),
        ("pkg/server_test.go", TIER_TEST),
        ("src/latest.ts", TIER_SOURCE),
        ("src/contest.py", TIER_SOURCE),
        ("src/testing.py", TIER_SOURCE),
        ("tests/fixtures/data.md", TIER_DOC),
    ],
)
def test_file_tier(path, tier):
    assert file_tier(path) == tier


@pytest.mark.parametrize(
    ("path", "doc"),
    [
        ("a.md", True),
        ("a.MD", True),
        ("a.mdx", True),
        ("a.markdown", True),
        ("a.rst", True),
        ("a.txt", True),
        ("a.adoc", True),
        ("a.md.sh", False),
        ("md", False),
        ("a.py", False),
    ],
)
def test_is_doc_path(path, doc):
    assert is_doc_path(path) is doc


@pytest.mark.parametrize(
    ("paths", "expected"),
    [
        (["docs/a.md", "README.md"], True),
        (
            ["docs/a.md", "docs/img/diagram.png", "x.SVG", "a.jpg", "b.jpeg", "c.gif", "d.webp"],
            True,
        ),
        (["docs/a.md", "infra/changes/x/rollback.sh"], False),
        (["docs/a.md", "src/app.py"], False),
        (["pnpm-lock.yaml"], False),
        (["docs/conf.py"], False),
        ([], False),
    ],
)
def test_is_docs_only(paths, expected):
    assert is_docs_only(paths) is expected


# ---------------------------------------------------------------------------
# Tiered order (budget step g)
# ---------------------------------------------------------------------------


def _file(path: str, size: int, index: int) -> Piece:
    return Piece(BLOCK_FILE, path, "x" * size + "\n", overhead=40, truncatable=False, index=index)


FILES = (
    _file("docs/guide.md", 100, 0),
    _file("src/big.ts", 3000, 1),
    _file("tests/test_big.py", 2000, 2),
    _file("src/small.ts", 200, 3),
    _file("README.md", 50, 4),
    _file("src/mid.ts", 1000, 5),
)


def test_order_is_source_then_tests_then_docs_smallest_first_within_a_tier():
    order = [p.ref for p in full_file_order(FILES)]
    assert order == [
        "src/small.ts",
        "src/mid.ts",
        "src/big.ts",
        "tests/test_big.py",
        "README.md",
        "docs/guide.md",
    ]


def test_ranked_files_come_first_within_their_tier():
    order = [p.ref for p in full_file_order(FILES, ("docs/guide.md", "src/big.ts", "missing.ts"))]
    assert order == [
        "src/big.ts",
        "src/small.ts",
        "src/mid.ts",
        "tests/test_big.py",
        "docs/guide.md",
        "README.md",
    ]


def _groups(files, priority=()):
    return FillGroups(files=files, file_priority=priority)


def _tokens(pieces) -> int:
    # What fill charges per whole piece: ceil((overhead + chars) / 3.5).
    from budget import estimate_len

    return sum(estimate_len(p.overhead + len(p.content)) for p in pieces)


def test_docs_are_dropped_before_source_even_when_smaller():
    # Room for the source and the test but not the docs: the docs go first,
    # although they are the smallest files (riel#889 dropped source first).
    keep = [FILES[3], FILES[5], FILES[1], FILES[2]]
    room = _tokens(keep) + 5
    result = fill(_groups(FILES), max_context_tokens=room + 1000, mandatory_tokens=1000)
    included = [p.piece.ref for p in result.placed]
    assert included == ["src/small.ts", "src/mid.ts", "src/big.ts", "tests/test_big.py"]
    assert [p.ref for p in result.dropped_files] == ["README.md", "docs/guide.md"]


def test_tests_are_dropped_before_source():
    keep = [FILES[3], FILES[5], FILES[1]]
    room = _tokens(keep) + 5
    result = fill(_groups(FILES), max_context_tokens=room + 1000, mandatory_tokens=1000)
    assert [p.piece.ref for p in result.placed] == ["src/small.ts", "src/mid.ts", "src/big.ts"]
    assert result.dropped_files[0].ref == "tests/test_big.py"


def test_without_a_ranking_the_largest_source_file_is_dropped_first():
    keep = [FILES[3], FILES[5]]
    room = _tokens(keep) + 5
    result = fill(_groups(FILES), max_context_tokens=room + 1000, mandatory_tokens=1000)
    assert [p.piece.ref for p in result.placed] == ["src/small.ts", "src/mid.ts"]
    assert result.dropped_files[0].ref == "src/big.ts"


def test_the_ranking_keeps_the_core_file_over_smaller_ones():
    keep = [FILES[1]]
    room = _tokens(keep) + 5
    result = fill(
        _groups(FILES, ("src/big.ts",)), max_context_tokens=room + 1000, mandatory_tokens=1000
    )
    assert [p.piece.ref for p in result.placed] == ["src/big.ts"]


def test_a_smaller_file_after_a_dropped_one_still_gets_its_room():
    # The big source file does not fit; the docs after it do. A file is never
    # dropped to make room for a later one, and room is never left unused.
    keep = [FILES[3], FILES[5], FILES[4]]
    room = _tokens(keep) + 5
    result = fill(_groups(FILES), max_context_tokens=room + 1000, mandatory_tokens=1000)
    assert [p.piece.ref for p in result.placed] == ["src/small.ts", "src/mid.ts", "README.md"]
    assert [p.ref for p in result.dropped_files] == [
        "src/big.ts",
        "tests/test_big.py",
        "docs/guide.md",
    ]
