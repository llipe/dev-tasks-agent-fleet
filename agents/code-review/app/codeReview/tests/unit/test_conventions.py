"""
S-208 AC5 — repository conventions (TC-208-12, TC-208-13; PRD FR-11, spec §8.3 step 5).

Head ``AGENTS.md``, else ``CLAUDE.md``; plus the ``# `` title and ``Status`` line
of each ``docs/adr/*.md`` (directory listing, the first 50 by name); the whole
bundle capped at 10% of ``max_context_tokens``. Everything is read at
``head_sha``; a 404 means "no such file", a 403 skips with a ``warn``.
"""

from __future__ import annotations

import time

import pytest

from context.conventions import ADR_DIR, CONVENTION_FILES, MAX_ADR_FIELD_CHARS, MAX_ADRS
from context.repo_conventions import (
    AdrSummary,
    ConventionsContext,
    adr_summary,
    conventions_cap,
    render_conventions,
    repo_conventions,
)
from context.tokens import TRUNCATION_MARKER, estimate
from github_client import GitHubApiError, GitHubClient, GitHubPermissionDenied
from tests.helpers.github_stub import (
    FIXTURES,
    StubTransport,
    json_response,
    load_fixture,
    text_response,
)

HEAD = "9f2c4e1a7b3d5f60812a4c6e8b0d2f4a6c8e0b1d"
CONTENTS = "/repos/acme/widgets/contents/"
NOT_FOUND = json_response({"message": "Not Found"}, 404)
BIG = 200_000


def _client(stub: StubTransport) -> GitHubClient:
    return GitHubClient("ghs_test", "acme", "widgets", 42, transport=stub, sleep=lambda _s: None)


def _entry(name: str, kind: str = "file", path: str | None = None) -> dict:
    return {
        "name": name,
        "path": path or f"docs/adr/{name}",
        "type": kind,
        "size": 1,
        "sha": "0" * 40,
    }


def _stub(files: dict[str, str], adr_entries: list[dict] | None = None) -> StubTransport:
    routes: dict[tuple, object] = {
        ("GET", CONTENTS + path): text_response(text) for path, text in files.items()
    }
    if adr_entries is not None:
        routes[("GET", CONTENTS + "docs/adr")] = json_response(adr_entries)
    return StubTransport(routes, default=NOT_FOUND)


def _run(stub: StubTransport, *, budget: int = BIG, warn=None) -> ConventionsContext:
    return repo_conventions(_client(stub), HEAD, max_context_tokens=budget, warn=warn)


def _sample(name: str) -> str:
    return (FIXTURES / "sample-pr" / name).read_bytes().decode("utf-8")


def _requested(stub: StubTransport) -> list[str]:
    return [c.path.removeprefix(CONTENTS) for c in stub.calls]


# -- TC-208-12: sources -------------------------------------------------------


def test_constants():
    assert CONVENTION_FILES == ("AGENTS.md", "CLAUDE.md")
    assert ADR_DIR == "docs/adr"
    assert MAX_ADRS == 50
    assert conventions_cap(200_000) == 20_000
    assert conventions_cap(9) == 0


def test_agents_md_is_used_and_claude_md_is_not_requested():
    stub = _stub({"AGENTS.md": "# AGENTS\n\nUse pnpm.\n", "CLAUDE.md": "# CLAUDE\n"})
    ctx = _run(stub)
    assert ctx.source == "AGENTS.md"
    assert "Use pnpm." in ctx.text and "# CLAUDE" not in ctx.text
    assert "CLAUDE.md" not in _requested(stub)
    assert all(c.params == {"ref": HEAD} for c in stub.calls)


def test_claude_md_is_used_when_agents_md_is_absent():
    stub = _stub({"CLAUDE.md": "# CLAUDE\n\nRun make validate.\n"})
    ctx = _run(stub)
    assert ctx.source == "CLAUDE.md"
    assert "Run make validate." in ctx.text
    assert _requested(stub)[:2] == ["AGENTS.md", "CLAUDE.md"]


def test_both_absent_and_no_adrs_is_no_conventions_block():
    stub = _stub({})
    ctx = _run(stub)
    assert ctx.source is None and ctx.adrs == ()
    assert ctx.text == "" and not ctx.truncated and ctx.tokens == 0
    assert _requested(stub) == ["AGENTS.md", "CLAUDE.md", "docs/adr"]


def test_an_empty_agents_md_is_present():
    """Pinned: presence decides, so an empty ``AGENTS.md`` does not fall back."""
    stub = _stub({"AGENTS.md": "", "CLAUDE.md": "# CLAUDE\n"})
    ctx = _run(stub)
    assert ctx.source == "AGENTS.md"
    assert "CLAUDE.md" not in _requested(stub)


def test_sample_pr_fixture_bundle():
    stub = load_fixture("sample-pr")
    ctx = _run(stub)
    assert ctx.source == "AGENTS.md"
    assert ctx.adrs == (
        AdrSummary("docs/adr/ADR-001-use-python.md", "ADR-001: Use Python", "Status: Accepted"),
        AdrSummary("docs/adr/ADR-002-sizes.md", "ADR-002: Size limits", "Status: Proposed"),
    )
    assert ctx.text == (
        "ADRs in docs/adr (title and Status line):\n"
        "- `docs/adr/ADR-001-use-python.md`: ADR-001: Use Python — Status: Accepted\n"
        "- `docs/adr/ADR-002-sizes.md`: ADR-002: Size limits — Status: Proposed\n"
        "\n"
        "AGENTS.md at head:\n" + _sample("agents_md_head.md")
    )
    assert "docs/adr/drafts" not in _requested(stub)  # a subdirectory is not an ADR


def test_non_md_entries_and_directories_are_ignored():
    entries = [
        _entry("ADR-001-a.md"),
        _entry("README.txt"),
        _entry("diagram.png"),
        _entry("ADR-002-b.MD"),
        _entry("drafts.md", kind="dir"),
        _entry("link.md", kind="symlink"),
    ]
    stub = _stub({"docs/adr/ADR-001-a.md": "# A\n"}, entries)
    ctx = _run(stub)
    assert [a.path for a in ctx.adrs] == ["docs/adr/ADR-001-a.md"]
    assert [p for p in _requested(stub) if p.startswith("docs/adr/")] == ["docs/adr/ADR-001-a.md"]


@pytest.mark.parametrize(
    "name",
    ["../secret.md", "a b.md", "x/y.md", "%2e%2e.md", "café.md", ".md", "a.md\n", ""],
)
def test_hostile_adr_names_are_never_requested(name):
    stub = _stub({}, [_entry(name, path="docs/adr/ok.md")])
    ctx = _run(stub)
    assert ctx.adrs == ()
    assert _requested(stub) == ["AGENTS.md", "CLAUDE.md", "docs/adr"]


def test_the_request_path_is_built_from_the_name_not_the_listed_path():
    stub = _stub({"docs/adr/a.md": "# A\n"}, [_entry("a.md", path="../../etc/passwd")])
    ctx = _run(stub)
    assert [a.path for a in ctx.adrs] == ["docs/adr/a.md"]
    assert _requested(stub)[-1] == "docs/adr/a.md"


# -- TC-208-12: title and Status ----------------------------------------------


@pytest.mark.parametrize(
    ("text", "title", "status"),
    [
        ("# ADR-001: Use Python\n\nStatus: Accepted\n", "ADR-001: Use Python", "Status: Accepted"),
        ("# T\n\n**Status:** Accepted\n", "T", "**Status:** Accepted"),
        ("# T\n\n- Status: Superseded by ADR-9\n", "T", "- Status: Superseded by ADR-9"),
        ("# T\n\n## Status\n\nAccepted\n\n## Context\n", "T", "Status: Accepted"),
        (
            "# T\n\n### Status ###\n\n\nProposed (2026-10-01)\n",
            "T",
            "Status: Proposed (2026-10-01)",
        ),
        ("# T\n\n## Status\n\n## Context\n", "T", None),
        ("# T\n\n## Status\n", "T", None),
        ("# T\n\nNo status here.\n", "T", None),
        ("# T\n\nstatus: lowercase\n", "T", None),
        ("# T\n\nThe Status quo: unchanged.\n", "T", None),
        ("## Not a title\n\nStatus: Accepted\n", None, "Status: Accepted"),
        ("#NoSpace\n# Real title\r\nStatus: Accepted\r\n", "Real title", "Status: Accepted"),
        ("Status: Draft\r# Title\r", "Title", "Status: Draft"),
        ("", None, None),
    ],
)
def test_adr_summary_title_and_status(text, title, status):
    assert adr_summary("docs/adr/x.md", text) == AdrSummary("docs/adr/x.md", title, status)


def test_adr_title_and_status_are_cut():
    text = "# " + "t" * 10_000 + "\nStatus: " + "s" * 10_000 + "\n"
    summary = adr_summary("docs/adr/x.md", text)
    assert summary.title is not None and summary.status is not None
    assert len(summary.title) == MAX_ADR_FIELD_CHARS
    assert len(summary.status) == MAX_ADR_FIELD_CHARS


def test_adr_without_status_renders_title_only():
    text = render_conventions(None, None, (AdrSummary("docs/adr/a.md", "A", None),))
    assert text == "ADRs in docs/adr (title and Status line):\n- `docs/adr/a.md`: A\n"


def test_adr_without_title_renders_a_placeholder():
    text = render_conventions(None, None, (AdrSummary("docs/adr/a.md", None, "Status: X"),))
    assert "- `docs/adr/a.md`: (no title) — Status: X\n" in text


def test_conventions_file_without_adrs_renders_the_file_only():
    assert render_conventions("CLAUDE.md", "body\n", ()) == "CLAUDE.md at head:\nbody\n"


def test_conventions_file_without_a_final_newline_gets_one():
    assert render_conventions("AGENTS.md", "body", ()) == "AGENTS.md at head:\nbody\n"


# -- TC-208-13: 60 ADRs, 404, cap ----------------------------------------------


def test_sixty_adrs_keep_the_first_fifty_by_name():
    names = [f"ADR-{i:03d}-x.md" for i in range(60, 0, -1)]  # listed in reverse
    files = {f"docs/adr/{n}": f"# {n}\n" for n in names}
    stub = _stub(files, [_entry(n) for n in names])
    ctx = _run(stub)
    expected = sorted(names)[:MAX_ADRS]
    assert [a.path for a in ctx.adrs] == [f"docs/adr/{n}" for n in expected]
    assert ctx.adrs_ignored == 10
    assert [p for p in _requested(stub) if p.startswith("docs/adr/")] == [
        f"docs/adr/{n}" for n in expected
    ]


def test_adr_directory_404_is_no_adr_list():
    stub = _stub({"AGENTS.md": "x\n"})
    ctx = _run(stub)
    assert ctx.adrs == () and ctx.adrs_ignored == 0
    assert ctx.text == "AGENTS.md at head:\nx\n"


def test_adr_directory_that_is_a_file_is_no_adr_list():
    stub = _stub({})
    stub.add(("GET", CONTENTS + "docs/adr"), json_response({"type": "file", "name": "adr"}))
    assert _run(stub).adrs == ()


def test_an_adr_file_404_after_listing_is_skipped():
    stub = _stub({"docs/adr/b.md": "# B\n"}, [_entry("a.md"), _entry("b.md")])
    ctx = _run(stub)
    assert [a.path for a in ctx.adrs] == ["docs/adr/b.md"]


def test_bundle_over_ten_percent_is_truncated_to_the_cap():
    agents = "".join(f"Rule {i}: always do the thing number {i}.\n" for i in range(5_000))
    stub = _stub({"AGENTS.md": agents}, [_entry("a.md")])
    stub.add(("GET", CONTENTS + "docs/adr/a.md"), text_response("# A\nStatus: Accepted\n"))
    budget = 50_000
    ctx = _run(stub, budget=budget)
    assert ctx.truncated
    assert ctx.tokens > budget // 10
    assert estimate(ctx.text) <= budget // 10
    assert ctx.text.endswith(TRUNCATION_MARKER + "\n")
    assert ctx.text.startswith("ADRs in docs/adr")  # the ADR index comes first, survives


def test_bundle_within_the_cap_is_whole():
    stub = _stub({"AGENTS.md": "x\n"})
    ctx = _run(stub, budget=100)
    assert not ctx.truncated and ctx.tokens == estimate(ctx.text)


# -- statuses ---------------------------------------------------------------------


def _warns() -> tuple[list, object]:
    seen: list[tuple[str, dict]] = []
    return seen, lambda m, **d: seen.append((m, d))


def test_agents_md_403_warns_and_falls_back_to_claude_md():
    stub = _stub({"CLAUDE.md": "c\n"})
    stub.add(("GET", CONTENTS + "AGENTS.md"), json_response({}, 403))
    seen, warn = _warns()
    ctx = _run(stub, warn=warn)
    assert ctx.source == "CLAUDE.md" and ctx.unavailable
    assert seen == [("conventions file unavailable", {"path": "AGENTS.md", "reason": "permission"})]


def test_adr_listing_403_warns_and_lists_nothing():
    stub = _stub({"AGENTS.md": "x\n"})
    stub.add(("GET", CONTENTS + "docs/adr"), json_response({}, 403))
    seen, warn = _warns()
    ctx = _run(stub, warn=warn)
    assert ctx.adrs == () and ctx.unavailable and ctx.source == "AGENTS.md"
    assert seen == [("conventions file unavailable", {"path": "docs/adr", "reason": "permission"})]


def test_adr_file_403_warns_and_skips_that_adr():
    stub = _stub({"docs/adr/b.md": "# B\n"}, [_entry("a.md"), _entry("b.md")])
    stub.add(("GET", CONTENTS + "docs/adr/a.md"), json_response({}, 403))
    seen, warn = _warns()
    ctx = _run(stub, warn=warn)
    assert [a.path for a in ctx.adrs] == ["docs/adr/b.md"] and ctx.unavailable
    assert seen == [
        ("conventions file unavailable", {"path": "docs/adr/a.md", "reason": "permission"})
    ]


def test_no_warning_on_the_normal_paths():
    seen, warn = _warns()
    _run(load_fixture("sample-pr"), warn=warn)
    _run(_stub({}), warn=warn)
    assert seen == []


@pytest.mark.parametrize("path", ["AGENTS.md", "CLAUDE.md", "docs/adr", "docs/adr/a.md"])
def test_401_propagates(path):
    stub = _stub({}, [_entry("a.md")])
    stub.add(("GET", CONTENTS + path), json_response({}, 401))
    with pytest.raises(GitHubPermissionDenied):
        _run(stub)


def test_5xx_propagates():
    stub = _stub({})
    stub.add(("GET", CONTENTS + "AGENTS.md"), json_response({}, 503))
    with pytest.raises(GitHubApiError):
        _run(stub)


def test_hostile_adr_text_is_summarized_quickly():
    text = "#" * 100_000 + "\n" + " " * 100_000 + "Status" + " " * 100_000 + "x\n"
    text += "## Status" + " " * 100_000 + "#" * 100_000 + " x\n"
    start = time.perf_counter()
    adr_summary("docs/adr/x.md", text * 3)
    assert time.perf_counter() - start < 2.0


def test_403_without_a_warn_callback_still_skips():
    stub = _stub({"CLAUDE.md": "c\n"})
    stub.add(("GET", CONTENTS + "AGENTS.md"), json_response({}, 403))
    ctx = _run(stub)
    assert ctx.source == "CLAUDE.md" and ctx.unavailable
