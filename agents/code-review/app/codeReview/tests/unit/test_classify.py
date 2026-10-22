"""
S-206 AC1 — file classification (spec §8.2, PRD FR-5, FR-10).

TC-206-01..05 and TC-206-16. ``classify`` sorts the PR's changed files into
"reviewed" and "listed by name only" using the path and the files-response
metadata alone; it never fetches content.
"""

from __future__ import annotations

import pytest

from context.diff import (
    LOCKFILE_NAMES,
    Classification,
    NameOnlyFile,
    check_size,
    classify,
    path_reason,
)
from github_client import PullFile


def _file(
    name: str, *, status: str = "modified", add: int = 1, dele: int = 0, patch: str | None = "@@"
) -> PullFile:
    return PullFile(filename=name, status=status, additions=add, deletions=dele, patch=patch)


def _reason(name: str, **kw) -> str | None:
    result = classify([_file(name, **kw)])
    if result.reviewed:
        return None
    return result.name_only[0].reason


# -- TC-206-01 lockfiles ----------------------------------------------------

SPEC_LOCKFILES = [
    "pnpm-lock.yaml",
    "package-lock.json",
    "yarn.lock",
    "poetry.lock",
    "uv.lock",
    "Pipfile.lock",
    "Cargo.lock",
    "go.sum",
    "Gemfile.lock",
    "composer.lock",
]


def test_lockfile_set_is_exactly_the_spec_list():
    assert set(SPEC_LOCKFILES) == LOCKFILE_NAMES


@pytest.mark.parametrize("name", SPEC_LOCKFILES)
@pytest.mark.parametrize("prefix", ["", "apps/web/", "a/b/c/"])
def test_lockfile_at_root_and_nested_is_name_only(name, prefix):
    assert _reason(prefix + name) == "lockfile"


# -- TC-206-02 generated paths ---------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "dist/x.js",
        "build/y.py",
        "packages/ui/dist/index.js",
        "a.min.js",
        "static/b.min.css",
        "c.js.map",
        "__snapshots__/t.snap",
    ],
)
def test_generated_paths_are_name_only(path):
    assert _reason(path) == "generated"


# -- TC-206-03 binary ------------------------------------------------------


def test_files_entry_without_patch_and_no_line_counts_is_binary():
    assert _reason("assets/logo.png", status="added", add=0, dele=0, patch=None) == "binary"


def test_patchless_file_with_line_counts_stays_reviewed_so_its_lines_are_budgeted():
    """GitHub omits ``patch`` for very large text diffs too.

    Treating such a file as binary would hide its lines from the size check and
    review the PR without it (a partial review, D-11). It stays reviewed; the
    NUL check on its fetched content still catches a real binary.
    """
    result = classify([_file("data/huge.sql", add=40_000, dele=0, patch=None)])
    assert [f.filename for f in result.reviewed] == ["data/huge.sql"]


def test_pure_rename_without_patch_stays_reviewed():
    f = PullFile("src/b.py", "renamed", 0, 0, previous_filename="src/a.py", patch=None)
    assert classify([f]).reviewed == (f,)


# -- TC-206-04 excluded workstream paths ------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "workstream/tasks-x.md",
        "workstream/planner-state-x.md",
        "workstream/decisions-x.md",
        "workstream/research-x.md",
    ],
)
def test_excluded_workstream_paths_are_name_only(path):
    assert _reason(path) == "excluded"


@pytest.mark.parametrize(
    "path", ["workstream/specification-x.md", "workstream/fidelity-report-S-1.md"]
)
def test_spec_and_fidelity_reports_are_reviewed(path):
    assert _reason(path) is None


# -- TC-206-05 near-misses ---------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "lockfile.md",
        "pnpm-lock.yaml.txt",
        "Cargo.lock.bak",
        "distribution/x.py",
        "rebuild/x.py",
        "workstream/tasks.md",
        "docs/workstream/tasks-x.md",
        "README.min.md",
        "dist",  # a file named dist, not a directory
        "my-dist/x.js",
        "workstream/sub/tasks-x.md",
        "workstream/tasks-x.markdown",
        "PNPM-LOCK.YAML",
    ],
)
def test_near_misses_are_reviewed(path):
    assert _reason(path) is None


# -- result shape ------------------------------------------------------------


def test_classification_keeps_files_list_order_in_both_groups():
    files = [
        _file("src/a.py"),
        _file("pnpm-lock.yaml"),
        _file("src/b.py"),
        _file("workstream/tasks-1.md"),
        _file("dist/c.js"),
    ]
    result = classify(files)
    assert isinstance(result, Classification)
    assert [f.filename for f in result.reviewed] == ["src/a.py", "src/b.py"]
    assert result.name_only == (
        NameOnlyFile("pnpm-lock.yaml", "modified", "lockfile"),
        NameOnlyFile("workstream/tasks-1.md", "modified", "excluded"),
        NameOnlyFile("dist/c.js", "modified", "generated"),
    )


def test_path_reason_precedence_is_excluded_then_lockfile_then_generated():
    assert path_reason("workstream/tasks-x.md") == "excluded"
    assert path_reason("dist/pnpm-lock.yaml") == "lockfile"
    assert path_reason("dist/a.js") == "generated"
    assert path_reason("src/a.py") is None


def test_classify_accepts_an_empty_list():
    assert classify([]) == Classification((), ())


# -- TC-206-16 300+ files ------------------------------------------------------


def test_300_plus_files_classify_and_budget_from_metadata_alone():
    """No transport is involved: classify and check_size take metadata only."""
    files = [_file(f"src/m{i}.py", add=1) for i in range(320)] + [
        _file(f"vendor/{i}/yarn.lock", add=500) for i in range(20)
    ]
    result = classify(files)
    assert len(result.reviewed) == 320
    assert len(result.name_only) == 20
    assert check_size(result, max_diff_lines=2000) is None
    over = check_size(result, max_diff_lines=300)
    assert over is not None and (over.lines, over.files) == (320, 320)
