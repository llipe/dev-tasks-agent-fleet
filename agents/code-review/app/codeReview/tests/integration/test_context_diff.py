"""
S-206 L2 — expanded diff on the recorded ``sample-pr`` fixture (TC-206-17..19).

The sample PR changes five files: three reviewed (``src/app.py`` modified,
``docs/notes with space.md`` added, ``src/new_name.py`` renamed from
``src/old_name.py``) and two listed by name only (``pnpm-lock.yaml``, and
``assets/logo.png`` with no ``patch``). The client reads the PR, its files,
and the merge base through the real ``GitHubClient`` over ``StubTransport``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from context.diff import DiffContext, NameOnlyFile, diff_context
from github_client import GitHubClient
from tests.helpers.github_stub import FIXTURES, fixture_json, json_response, load_fixture

SAMPLE = "sample-pr"
GOLDEN = FIXTURES / SAMPLE / "expanded_diff.golden"
HEAD = "9f2c4e1a7b3d5f60812a4c6e8b0d2f4a6c8e0b1d"
MB = "7e1d3c5b9a8f6e4d2c0b1a3f5e7d9c8b6a4f2e0d"
BASE = "3a5c7e9b1d3f5a7c9e1b3d5f7a9c1e3b5d7f9a1c"
SHA = re.compile(r"[0-9a-f]{40}")


def _run(stub) -> DiffContext:
    def factory() -> GitHubClient:
        return GitHubClient(
            "ghs_fixture", "acme", "widgets", 42, transport=stub, sleep=lambda _s: None
        )

    client = factory()
    pull = client.get_pull()
    result = diff_context(
        client, pull, client.list_pull_files(), max_diff_lines=2000, client_factory=factory
    )
    assert isinstance(result, DiffContext)
    return result


def test_sample_pr_expanded_diff_matches_the_golden_output():
    ctx = _run(load_fixture(SAMPLE))
    assert ctx.diff_text == GOLDEN.read_text()
    assert ctx.merge_base_sha == MB and ctx.merge_base_sha != BASE
    assert ctx.head_sha == HEAD
    assert ctx.changed_lines == 8
    assert [(f.filename, f.status, f.previous_filename) for f in ctx.files] == [
        ("src/app.py", "modified", None),
        ("docs/notes with space.md", "added", None),
        ("src/new_name.py", "renamed", "src/old_name.py"),
    ]
    assert ctx.name_only == (
        NameOnlyFile("pnpm-lock.yaml", "modified", "lockfile"),
        NameOnlyFile("assets/logo.png", "added", "binary"),
    )


def test_sample_pr_head_contents_and_changed_ranges():
    ctx = _run(load_fixture(SAMPLE))
    base = FIXTURES / SAMPLE
    assert ctx.head_contents == {
        "src/app.py": (base / "app_py_head.txt").read_text(),
        "docs/notes with space.md": (base / "notes_head.md").read_text(),
        "src/new_name.py": (base / "new_name_head.txt").read_text(),
    }
    assert ctx.changed_ranges == {
        "src/app.py": ((2, 4),),
        "docs/notes with space.md": ((1, 2),),
        "src/new_name.py": ((1, 1),),
    }


def test_every_contents_request_is_pinned_to_a_commit_sha():
    stub = load_fixture(SAMPLE)
    _run(stub)
    contents = [c for c in stub.calls if "/contents/" in c.path]
    assert len(contents) == 5  # app.py x2, notes (head), old_name (base), new_name (head)
    for call in contents:
        assert set(call.params) == {"ref"}
        assert SHA.fullmatch(call.params["ref"]), call.params
        assert call.params["ref"] in {HEAD, MB}
    assert not any(c.path.endswith(("pnpm-lock.yaml", "logo.png")) for c in stub.calls)


def test_excluded_workstream_file_content_is_never_fetched():
    """FR-10 / AC-8: an added tasks file is listed by name, never read."""
    stub = load_fixture(SAMPLE)
    files = fixture_json(SAMPLE, "pull_files_page1.json")
    files.append(
        {
            "filename": "workstream/tasks-prd-widgets.md",
            "status": "added",
            "additions": 40,
            "deletions": 0,
            "patch": "@@ -0,0 +1,40 @@\n+- [ ] secret plan\n",
        }
    )
    stub.add(
        ("GET", "/repos/acme/widgets/pulls/42/files", (("page", "1"), ("per_page", "100"))),
        json_response(files),
    )
    ctx = _run(stub)
    assert ctx.name_only[-1] == NameOnlyFile("workstream/tasks-prd-widgets.md", "added", "excluded")
    assert not any("/contents/workstream" in c.path for c in stub.calls)
    assert "secret plan" not in ctx.diff_text
    assert "secret plan" not in json.dumps(ctx.head_contents)
    assert ctx.changed_lines == 8  # excluded lines are not counted


def test_golden_file_is_checked_in():
    assert Path(GOLDEN).is_file()
