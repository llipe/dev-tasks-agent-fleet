"""
S-206 completion-gate probes (qa-engineer): adversarial inputs for ``context.diff``.

Extends TC-206-03, -05, -08, -11, -13, -14, -20 and EC-05/06/08 with the
cases the story tests do not reach: path tricks and Unicode lookalikes,
budget paths that must not even build a worker client, header forging through
file names, lone-CR and CRLF texts, invalid UTF-8 on the base side, the NUL
scan on base and rename blobs, worker isolation in the content pool, a huge
single-line file, and renames whose names carry a backslash or a newline.

Two source defects these probes found (rename-away from a name-only path,
Unicode line separators in header names) are fixed; their tests now run
unmarked.
"""

from __future__ import annotations

import random
import threading
import time

import pytest

from context.diff import (
    NUL_SCAN_BYTES,
    NameOnlyFile,
    OverBudget,
    changed_lines,
    changed_ranges,
    check_size,
    classify,
    diff_context,
    expanded_diff,
    path_reason,
    unified_diff,
)
from github_client import GitHubClient, PullFiles
from tests.helpers.github_stub import StubResponse, StubTransport, json_response
from tests.unit.test_diff import BASE, HEAD, MB, ORG, REPO, N, P, Repo, _expand, _f, _pull

# -- classification: path tricks ------------------------------------------------


@pytest.mark.parametrize(
    ("path", "reason"),
    [
        # Matching is literal and case-sensitive, as spec §8.2 lists the names.
        ("Workstream/tasks-x.md", None),
        ("workstream/Tasks-x.md", None),
        ("workstream/tasks-x.MD", None),
        ("Dist/a.js", None),
        ("BUILD/a.py", None),
        ("a.MIN.JS", None),
        # Unicode lookalikes are different paths on GitHub, so they are reviewed.
        ("workstream/tasks‐x.md", None),  # U+2010 HYPHEN
        ("wоrkstream/tasks-x.md", None),  # Cyrillic o
        ("ｗorkstream/tasks-x.md", None),  # fullwidth w
        ("pnpm‑lock.yaml", None),  # U+2011 NON-BREAKING HYPHEN
        # Root-only workstream rule; nested copies are ordinary files.
        ("a/workstream/tasks-x.md", None),
        ("workstream/nested/tasks-x.md", None),
        ("workstream/tasks-.md", "excluded"),
        ("workstream/tasks-x.md\n", None),
        # Directory-style names.
        ("build/", "generated"),
        ("./pnpm-lock.yaml", "lockfile"),
        ("deep/" * 40 + "Cargo.lock", "lockfile"),
        ("x/dist/y/z.py", "generated"),
    ],
)
def test_path_tricks_classify_literally(path, reason):
    assert path_reason(path) == reason


@pytest.mark.parametrize(
    "path",
    [
        "./workstream/tasks-x.md",
        "/workstream/tasks-x.md",
        "workstream//tasks-x.md",
        "workstream/tasks-x.md/",
        "workstream/../workstream/tasks-x.md",
    ],
)
def test_non_canonical_spellings_of_an_excluded_path_are_never_fetched(path):
    """Classification misses these spellings, but the client guard refuses them.

    GitHub never lists such names; this pins the defense in depth so an
    excluded file cannot be read through a dot, empty, or trailing segment.
    """
    assert path_reason(path) is None
    repo = Repo()
    ctx = _expand(repo, [_f(path, "added", add=3, dele=0)])
    assert ctx.files == ()
    assert ctx.name_only == (
        NameOnlyFile(path, "added", "content_unavailable", "path cannot be fetched safely"),
    )
    assert repo.content_calls() == []


def test_rename_away_from_an_excluded_workstream_path_never_reads_the_excluded_content():
    repo = Repo(
        {("workstream/tasks-x.md", MB): "secret plan\n", ("docs/plan.md", HEAD): "public\n"}
    )
    ctx = _expand(repo, [_f("docs/plan.md", "renamed", prev="workstream/tasks-x.md")])
    assert not any("/contents/workstream/" in c.path for c in repo.content_calls())
    assert "secret plan" not in ctx.diff_text


@pytest.mark.parametrize(
    ("prev", "new", "rule", "secret"),
    [
        ("workstream/tasks-x.md", "docs/plan.md", "excluded", "secret plan"),
        ("yarn.lock", "yarn.lock.old", "lockfile", "lock-secret@1.0.0"),
        ("dist/a.js", "src/a.js", "generated", "minified_secret()"),
    ],
)
def test_rename_away_from_a_name_only_path_diffs_the_head_as_added(prev, new, rule, secret):
    """The base at a name-only previous name is never fetched (FR-10 / AC-8).

    The new name is reviewed, so the head is diffed from ``/dev/null``: every
    head line is ``+`` and the changed range is the whole head file. The
    file is not made name-only, so a rename cannot hide new code from review.
    """
    repo = Repo({(prev, MB): f"{secret}\n", (new, HEAD): "one\ntwo\nthree\n"})
    ctx = _expand(repo, [_f(new, "renamed", add=3, dele=1, prev=prev)])
    assert [(c.path, c.params["ref"]) for c in repo.content_calls()] == [
        (f"{P}/contents/{new}", HEAD)
    ]
    assert secret not in ctx.diff_text
    (fd,) = ctx.files
    assert (fd.filename, fd.status, fd.previous_filename) == (new, "renamed", prev)
    assert fd.base_withheld == rule
    assert fd.diff == f"--- /dev/null\n+++ b/{new}\n@@ -0,0 +1,3 @@\n+one\n+two\n+three\n"
    assert fd.head_content == "one\ntwo\nthree\n"
    assert fd.changed_ranges == ((1, 3),)
    assert ctx.name_only == ()


def test_rename_away_keeps_the_reported_line_counts_in_the_budget():
    files = [_f("src/a.js", "renamed", add=7, dele=900, prev="dist/a.js")]
    assert changed_lines(classify(files)) == 907
    assert check_size(classify(files), max_diff_lines=906) == OverBudget(907, 1, 906)


def test_rename_away_with_a_binary_head_is_still_moved_to_name_only():
    repo = Repo({("src/a.bin", HEAD): b"\x00\x01"})
    ctx = _expand(repo, [_f("src/a.bin", "renamed", prev="dist/a.bin")])
    assert ctx.files == ()
    assert ctx.name_only == (NameOnlyFile("src/a.bin", "renamed", "binary"),)
    assert all("/contents/dist/" not in c.path for c in repo.content_calls())


def test_ordinary_rename_has_no_base_withheld_note():
    repo = Repo({("src/old.py", MB): "a\n", ("src/new.py", HEAD): "b\n"})
    ctx = _expand(repo, [_f("src/new.py", "renamed", prev="src/old.py")])
    assert ctx.files[0].base_withheld is None
    assert ctx.files[0].diff.startswith("--- a/src/old.py\n+++ b/src/new.py\n")


def test_rename_into_an_excluded_workstream_path_is_name_only_and_unfetched():
    repo = Repo()
    ctx = _expand(repo, [_f("workstream/tasks-x.md", "renamed", prev="docs/plan.md")])
    assert ctx.name_only == (NameOnlyFile("workstream/tasks-x.md", "renamed", "excluded"),)
    assert repo.stub.calls == []


# -- size check: over budget builds nothing ----------------------------------------


def _forbidden_factory() -> GitHubClient:
    raise AssertionError("client_factory must not be called on the budget path")


@pytest.mark.parametrize(
    ("files", "truncated"),
    [
        ((_f("a.py", add=2001, dele=0),), False),
        ((_f("a.py", add=1, dele=0),), True),
        ((_f("a.py", add=5000, dele=5000),), True),
        ((_f("a.py", add=2000, dele=0),), True),  # at the limit, but cut
    ],
)
def test_over_budget_never_builds_a_worker_client_nor_touches_the_transport(files, truncated):
    stub = StubTransport()  # no routes: any request raises AssertionError
    client = GitHubClient("tok", ORG, REPO, N, transport=stub, sleep=lambda _s: None)
    result = diff_context(
        client,
        _pull(),
        PullFiles(files, truncated=truncated),
        max_diff_lines=2000,
        client_factory=_forbidden_factory,
    )
    assert isinstance(result, OverBudget)
    assert result.truncated is truncated
    assert stub.calls == []


def test_name_only_lines_never_push_a_pr_over_budget():
    files = PullFiles(
        (
            _f("a.py", add=2000, dele=0),
            _f("pnpm-lock.yaml", add=50_000, dele=50_000),
            _f("dist/app.js", add=9_999),
            _f("workstream/tasks-x.md", add=9_999),
            _f("logo.png", "added", add=0, dele=0, patch=None),
        ),
        truncated=False,
    )
    repo = Repo({("a.py", MB): "a\n", ("a.py", HEAD): "b\n"})
    result = diff_context(
        repo.client(), _pull(), files, max_diff_lines=2000, client_factory=repo.client
    )
    assert not isinstance(result, OverBudget)
    assert result.changed_lines == 2000


# -- header lines cannot be forged by a file name ------------------------------------


@pytest.mark.parametrize("ch", ["\n", "\r", "\r\n", "\x1b", "\x7f", "\t", "\x0b", "\x0c", "\x1c"])
def test_c0_control_characters_in_a_name_are_escaped_in_both_headers(ch):
    name = f"src/x{ch}+++ b/evil.py"
    out = unified_diff(name, name, "a\n", "b\n", "modified")
    lines = out.splitlines()
    assert len(lines) == len(out.split("\n")) - 1 == 5
    assert lines[0].startswith("--- a/src/x") and lines[0].endswith("+++ b/evil.py")
    assert lines[1].startswith("+++ b/src/x") and lines[1].endswith("+++ b/evil.py")
    assert ch not in lines[0] and ch not in lines[1]


def test_rename_with_a_newline_in_previous_filename_escapes_the_from_header():
    repo = Repo({("old\nname.py", MB): "a\n", ("new.py", HEAD): "b\n"})
    ctx = _expand(repo, [_f("new.py", "renamed", prev="old\nname.py")])
    assert ctx.files[0].diff.splitlines()[:2] == ["--- a/old\\nname.py", "+++ b/new.py"]


@pytest.mark.parametrize("ch", ["\x80", "\x85", "\x9b", "\x9f", " ", " "])
def test_unicode_line_separators_in_a_name_cannot_forge_a_header_line(ch):
    name = f"x{ch}+++ b/evil"
    out = unified_diff(name, name, "a\n", "b\n", "modified")
    assert len(out.splitlines()) == 5
    escaped = ch.encode("unicode_escape").decode("ascii")
    assert out.splitlines()[:2] == [f"--- a/x{escaped}+++ b/evil", f"+++ b/x{escaped}+++ b/evil"]


# -- line endings --------------------------------------------------------------------


def test_lone_cr_file_is_one_line_as_git_counts_it():
    base, head = "a\rb\rc\n", "a\rb\rC\n"
    out = unified_diff("m.txt", "m.txt", base, head, "modified")
    assert out == "--- a/m.txt\n+++ b/m.txt\n@@ -1 +1 @@\n-a\rb\rc\n+a\rb\rC\n"
    assert changed_ranges(base, head) == ((1, 1),)


def test_lone_cr_at_eof_without_newline_gets_the_marker():
    out = unified_diff("m.txt", "m.txt", "a\r", "b\r", "modified")
    assert out.endswith("+b\r\n\\ No newline at end of file\n")
    assert out.count("\\ No newline at end of file") == 2


def test_crlf_to_lf_conversion_changes_every_line():
    base = "".join(f"l{i}\r\n" for i in range(1, 6))
    head = base.replace("\r\n", "\n")
    assert changed_ranges(base, head) == ((1, 5),)
    out = unified_diff("m.txt", "m.txt", base, head, "modified")
    assert out.count("\n-l") == 5 and out.count("\n+l") == 5


def test_mixed_line_endings_survive_the_blob_round_trip():
    repo = Repo({("m.txt", MB): b"a\r\nb\nc\r", ("m.txt", HEAD): b"a\r\nB\nc\r"})
    ctx = _expand(repo, [_f("m.txt")])
    assert ctx.head_contents == {"m.txt": "a\r\nB\nc\r"}
    assert ctx.changed_ranges == {"m.txt": ((2, 2),)}
    assert " a\r\n-b\n+B\n c\r\n\\ No newline at end of file\n" in ctx.files[0].diff


# -- invalid UTF-8 -----------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        b"ok\n\xff\xfe\n",  # invalid start bytes
        b"ok\n\xc3",  # truncated multibyte at EOF
        b"ok\n\xc0\xaf\n",  # overlong '/'
        b"ok\n\xed\xa0\x80\n",  # encoded surrogate
        b"\xef\xbb\xbfok\n",  # BOM, valid
    ],
    ids=["invalid-start", "truncated", "overlong", "surrogate", "bom"],
)
def test_invalid_utf8_on_either_side_decodes_with_replacement_deterministically(raw):
    decoded = raw.decode("utf-8", errors="replace")
    repo = Repo({("m.txt", MB): raw, ("m.txt", HEAD): b"ok\nnew\n", ("gone.txt", MB): raw})
    files = [_f("m.txt"), _f("gone.txt", "removed")]
    first, second = _expand(repo, files), _expand(repo, files)
    assert first == second
    assert first.files[0].head_content == "ok\nnew\n"
    for line in decoded.split("\n")[1:]:
        if line:
            assert f"-{line}" in first.files[1].diff
    assert ("�" in first.diff_text) is ("�" in decoded)


# -- NUL scan on every fetched side ---------------------------------------------------


def test_nul_at_the_last_scanned_byte_of_a_renamed_base_is_binary():
    base = b"x" * (NUL_SCAN_BYTES - 1) + b"\x00"
    repo = Repo({("old.dat", MB): base, ("new.dat", HEAD): b"text\n"})
    ctx = _expand(repo, [_f("new.dat", "renamed", prev="old.dat")])
    assert ctx.files == ()
    assert ctx.name_only == (NameOnlyFile("new.dat", "renamed", "binary"),)


def test_nul_just_past_the_scan_window_of_a_removed_base_is_reviewed():
    base = b"x" * NUL_SCAN_BYTES + b"\x00\n"
    repo = Repo({("old.dat", MB): base})
    ctx = _expand(repo, [_f("old.dat", "removed")])
    assert [f.filename for f in ctx.files] == ["old.dat"]
    assert ctx.name_only == ()


def test_pure_rename_of_a_binary_without_patch_is_caught_by_the_nul_scan():
    repo = Repo({("a.png", MB): b"\x89PNG\r\n\x1a\n\x00\x00", ("b.png", HEAD): b"\x89PNG\x00"})
    ctx = _expand(repo, [_f("b.png", "renamed", add=0, dele=0, prev="a.png", patch=None)])
    assert ctx.files == ()
    assert ctx.name_only == (NameOnlyFile("b.png", "renamed", "binary"),)


# -- content pool: isolation ---------------------------------------------------------


def test_the_caller_client_reads_only_the_merge_base_and_workers_read_blobs():
    main_stub = StubTransport()
    main_stub.add(
        ("GET", f"{P}/compare/{BASE}...{HEAD}"), json_response({"merge_base_commit": {"sha": MB}})
    )
    main = GitHubClient("tok", ORG, REPO, N, transport=main_stub, sleep=lambda _s: None)
    repo = Repo({(f"f{i}.py", HEAD): f"{i}\n" for i in range(10)})
    ctx = expanded_diff(
        main,
        _pull(),
        classify([_f(f"f{i}.py", "added") for i in range(10)]),
        client_factory=repo.client,
    )
    assert len(ctx.files) == 10
    assert [c.path for c in main_stub.calls] == [f"{P}/compare/{BASE}...{HEAD}"]
    assert not any("/compare/" in c.path for c in repo.stub.calls)


def test_a_refused_path_does_not_poison_the_worker_client_for_later_files():
    repo = Repo({("ok.py", HEAD): "fine\n"})
    made: list[GitHubClient] = []

    def factory() -> GitHubClient:
        made.append(repo.client())
        return made[-1]

    ctx = expanded_diff(
        repo.client(),
        _pull(),
        classify([_f("bad\\x.py", "added"), _f("ok.py", "added")]),
        client_factory=factory,
        max_workers=1,
    )
    assert len(made) == 1  # one thread, one client, reused after the refusal
    assert [f.filename for f in ctx.files] == ["ok.py"]
    assert ctx.name_only[0].reason == "content_unavailable"


def test_an_unexpected_worker_exception_fails_the_run_and_is_never_a_content_result():
    """Only ``ForbiddenCall`` and a 404 become "content unavailable"."""
    repo = Repo({(f"f{i}.py", HEAD): f"{i}\n" for i in range(8)})

    class Boom(Exception):
        pass

    def factory() -> GitHubClient:
        client = repo.client()
        original = client.get_content_bytes

        def fetch(path, ref):
            if path == "f3.py":
                raise Boom(path)
            return original(path, ref)

        client.get_content_bytes = fetch  # type: ignore[method-assign]
        return client

    with pytest.raises(Boom, match="f3.py"):
        expanded_diff(
            repo.client(),
            _pull(),
            classify([_f(f"f{i}.py", "added") for i in range(8)]),
            client_factory=factory,
        )


def test_each_file_gets_its_own_blobs_under_random_completion_order():
    """Seeded jitter: base and head never cross files, whatever finishes first."""
    names = [f"m{i}.py" for i in range(24)]
    blobs: dict[tuple[str, str], bytes | str] = {}
    for n in names:
        blobs[(n, MB)] = f"base of {n}\n"
        blobs[(n, HEAD)] = f"head of {n}\n"
    repo = Repo(blobs)
    rng = random.Random(408_206)
    delays = {(n, side): rng.random() / 200 for n in names for side in (MB, HEAD)}
    lock = threading.Lock()

    def factory() -> GitHubClient:
        client = repo.client()
        original = client.get_content_bytes

        def fetch(path, ref):
            with lock:
                delay = delays[(path, ref)]
            time.sleep(delay)
            return original(path, ref)

        client.get_content_bytes = fetch  # type: ignore[method-assign]
        return client

    ctx = expanded_diff(
        repo.client(), _pull(), classify([_f(n) for n in names]), client_factory=factory
    )
    assert [f.filename for f in ctx.files] == names
    for f in ctx.files:
        assert f.diff.endswith(f"-base of {f.filename}\n+head of {f.filename}\n")
        assert f.head_content == f"head of {f.filename}\n"


# -- huge single-line file -----------------------------------------------------------


def test_huge_single_line_file_is_one_line_one_hunk():
    base = b"x" * 3_000_000
    head = base + b"y"
    repo = Repo({("min.txt", MB): base, ("min.txt", HEAD): head})
    ctx = _expand(repo, [_f("min.txt")])
    (fd,) = ctx.files
    assert fd.diff.count("\n@@ ") == 1 and "\n@@ -1 +1 @@\n" in fd.diff
    assert fd.diff.count("\\ No newline at end of file") == 2
    assert fd.changed_ranges == ((1, 1),)
    assert len(fd.head_content or "") == 3_000_001


def test_nul_beyond_the_scan_window_of_a_long_single_line_stays_in_the_text():
    """Spec §8.2 scans the first 8 KB only; a later NUL is kept verbatim."""
    head = b"y" * (NUL_SCAN_BYTES * 4) + b"\x00tail\n"
    repo = Repo({("one.txt", HEAD): head})
    ctx = _expand(repo, [_f("one.txt", "added")])
    assert ctx.head_contents["one.txt"].endswith("\x00tail\n")


# -- renames: names with a backslash, copied status ------------------------------------


def test_backslash_in_the_new_name_of_a_rename_is_content_unavailable_and_unsent():
    repo = Repo({("old.py", MB): "a\n"})
    ctx = _expand(repo, [_f("dir\\new.py", "renamed", prev="old.py")])
    assert ctx.files == ()
    assert ctx.name_only == (
        NameOnlyFile(
            "dir\\new.py", "renamed", "content_unavailable", "path cannot be fetched safely"
        ),
    )
    assert all("\\" not in c.path and "%5C" not in c.path for c in repo.stub.calls)


def test_backslash_in_both_names_sends_no_content_request():
    repo = Repo()
    ctx = _expand(repo, [_f("n\\b.py", "renamed", prev="o\\a.py")])
    assert ctx.name_only[0].reason == "content_unavailable"
    assert repo.content_calls() == []


def test_copied_file_reads_its_base_at_previous_filename():
    repo = Repo({("src/a.py", MB): "x\n", ("src/b.py", HEAD): "x\ny\n"})
    ctx = _expand(repo, [_f("src/b.py", "copied", add=1, dele=0, prev="src/a.py")])
    assert ctx.files[0].diff.startswith("--- a/src/a.py\n+++ b/src/b.py\n")
    assert ctx.changed_ranges == {"src/b.py": ((2, 2),)}


def test_a_404_on_the_head_of_a_rename_is_content_unavailable():
    repo = Repo({("old.py", MB): "a\n"})
    repo.blob("new.py", HEAD, StubResponse(404, b"{}"))
    ctx = _expand(repo, [_f("new.py", "renamed", prev="old.py")])
    assert ctx.files == ()
    assert ctx.name_only[0].detail == "not found at the reviewed commit"
