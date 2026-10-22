"""
S-206 AC2–AC4 — size check, expanded diff, head contents (spec §8.2, §8.3 step 1).

TC-206-03 (NUL part), TC-206-06..14, TC-206-20, plus the S-205 carry-forwards:
an unfetchable path (the guard's ``ForbiddenCall``) is "content unavailable",
never a run failure; ``compare`` 404 propagates as ``GitHubNotFound``; and each
worker thread of the content pool gets its own client (own transport).
"""

from __future__ import annotations

import threading
from urllib.parse import quote

import pytest

from context.diff import (
    MAX_WORKERS,
    NUL_SCAN_BYTES,
    Classification,
    DiffContext,
    NameOnlyFile,
    OverBudget,
    changed_lines,
    check_size,
    classify,
    diff_context,
    expanded_diff,
    unified_diff,
)
from github_client import (
    ForbiddenCall,
    GitHubApiError,
    GitHubClient,
    GitHubNotFound,
    PullFile,
    PullFiles,
    PullRequest,
)
from tests.helpers.github_stub import StubResponse, StubTransport, json_response

ORG, REPO, N = "acme", "widgets", 42
HEAD = "9" * 40
BASE = "3" * 40
MB = "7" * 40
P = f"/repos/{ORG}/{REPO}"


def _pull(head: str = HEAD, base: str = BASE) -> PullRequest:
    return PullRequest(N, "open", False, False, "t", "", head, "issue/41-x", base, "main")


def _f(
    name: str,
    status: str = "modified",
    add: int = 1,
    dele: int = 1,
    prev: str | None = None,
    patch: str | None = "@@",
) -> PullFile:
    return PullFile(name, status, add, dele, previous_filename=prev, patch=patch)


class Repo:
    """A StubTransport preloaded with compare and blob routes."""

    def __init__(self, blobs: dict[tuple[str, str], bytes | str] | None = None) -> None:
        self.stub = StubTransport()
        self.stub.add(
            ("GET", f"{P}/compare/{BASE}...{HEAD}"),
            json_response({"merge_base_commit": {"sha": MB}}),
        )
        for (path, ref), body in (blobs or {}).items():
            self.blob(path, ref, body)

    def blob(self, path: str, ref: str, body: bytes | str | StubResponse) -> None:
        resp = (
            body
            if isinstance(body, StubResponse)
            else StubResponse(200, body.encode() if isinstance(body, str) else body)
        )
        self.stub.add(("GET", f"{P}/contents/{_enc(path)}", (("ref", ref),)), resp)

    def client(self) -> GitHubClient:
        return GitHubClient("tok", ORG, REPO, N, transport=self.stub, sleep=lambda _s: None)

    def content_calls(self) -> list:
        return [c for c in self.stub.calls if "/contents/" in c.path]


def _enc(path: str) -> str:
    return "/".join(quote(s, safe="") for s in path.split("/"))


def _expand(repo: Repo, files: list[PullFile], **kw) -> DiffContext:
    return expanded_diff(repo.client(), _pull(), classify(files), client_factory=repo.client, **kw)


def _lines(n: int, fmt: str = "line {}\n") -> str:
    return "".join(fmt.format(i) for i in range(1, n + 1))


# -- AC2 size check (test_budget_*) -------------------------------------------


def test_budget_counts_reviewed_files_only():
    files = [
        _f("pnpm-lock.yaml", add=10_000, dele=0),
        _f("a.py", add=30, dele=10),
        _f("b.py", add=5, dele=0),
    ]
    cls = classify(files)
    assert changed_lines(cls) == 45
    assert check_size(cls, max_diff_lines=2000) is None


@pytest.mark.parametrize("limit", [2000, 100])
def test_budget_boundary_exactly_at_limit_proceeds_and_one_over_is_over_budget(limit):
    at = classify([_f("a.py", add=limit - 1, dele=1), _f("dist/x.js", add=99)])
    assert check_size(at, max_diff_lines=limit) is None
    over = classify(
        [_f("a.py", add=limit, dele=1), _f("b.py", add=0, dele=0), _f("dist/x.js", add=99)]
    )
    assert check_size(over, max_diff_lines=limit) == OverBudget(
        lines=limit + 1, files=2, max_diff_lines=limit
    )


def test_budget_over_limit_fetches_no_content_and_no_merge_base():
    repo = Repo()
    files = PullFiles((_f("a.py", add=2001, dele=0), _f("b.py")), truncated=False)
    result = diff_context(
        repo.client(), _pull(), files, max_diff_lines=2000, client_factory=repo.client
    )
    assert result == OverBudget(lines=2003, files=2, max_diff_lines=2000)
    assert repo.stub.calls == []


def test_budget_truncated_listing_is_over_budget_even_under_the_line_limit():
    """3,000-file cap reached: the counted lines are a lower bound (D-11)."""
    repo = Repo()
    files = PullFiles(tuple(_f(f"f{i}.txt", add=0, dele=0) for i in range(3000)), truncated=True)
    result = diff_context(
        repo.client(), _pull(), files, max_diff_lines=2000, client_factory=repo.client
    )
    assert result == OverBudget(lines=0, files=3000, max_diff_lines=2000, truncated=True)
    assert repo.stub.calls == []


def test_budget_lockfile_only_pr_is_not_over_budget_and_has_an_empty_diff():
    """TC-206-09 / DF-16: 0 reviewed lines, reviewed (empty diff), listed by name."""
    repo = Repo()
    files = PullFiles(
        (_f("pnpm-lock.yaml", add=900, dele=800), _f("apps/x/yarn.lock")), truncated=False
    )
    result = diff_context(
        repo.client(), _pull(), files, max_diff_lines=2000, client_factory=repo.client
    )
    assert isinstance(result, DiffContext)
    assert result.files == ()
    assert result.diff_text == ""
    assert result.changed_lines == 0
    assert [n.filename for n in result.name_only] == ["pnpm-lock.yaml", "apps/x/yarn.lock"]
    assert result.merge_base_sha is None
    assert repo.stub.calls == []  # nothing to diff, nothing fetched


# -- AC3 expanded diff ----------------------------------------------------------


def test_modified_file_has_50_lines_of_context_and_a_b_headers():
    base = _lines(200)
    head = base.replace("line 100\n", "LINE 100\n")
    out = unified_diff("src/m.py", "src/m.py", base, head, "modified")
    lines = out.splitlines()
    assert lines[:3] == ["--- a/src/m.py", "+++ b/src/m.py", "@@ -50,101 +50,101 @@"]
    assert lines[3] == " line 50" and lines[-1] == " line 150"
    assert "-line 100" in lines and "+LINE 100" in lines


def test_context_is_clamped_at_the_start_of_the_file():
    base = _lines(200)
    head = base.replace("line 10\n", "LINE 10\n")
    out = unified_diff("m.py", "m.py", base, head, "modified")
    assert out.splitlines()[2] == "@@ -1,60 +1,60 @@"


def test_added_file_fetches_head_only_and_is_all_plus():
    repo = Repo({("new.py", HEAD): "a\nb\n"})
    ctx = _expand(repo, [_f("new.py", "added", add=2, dele=0)])
    assert [c.params["ref"] for c in repo.content_calls()] == [HEAD]
    assert ctx.files[0].diff == "--- /dev/null\n+++ b/new.py\n@@ -0,0 +1,2 @@\n+a\n+b\n"


def test_removed_file_fetches_base_only_and_is_all_minus_with_no_head_content():
    repo = Repo({("old.py", MB): "a\nb\n"})
    ctx = _expand(repo, [_f("old.py", "removed", add=0, dele=2)])
    assert [c.params["ref"] for c in repo.content_calls()] == [MB]
    fd = ctx.files[0]
    assert fd.diff == "--- a/old.py\n+++ /dev/null\n@@ -1,2 +0,0 @@\n-a\n-b\n"
    assert fd.head_content is None
    assert fd.changed_ranges == ()
    assert "old.py" not in ctx.head_contents


def test_renamed_with_edits_fetches_base_at_previous_filename():
    repo = Repo(
        {("src/old.py", MB): "NAME = 'old'\nV = 1\n", ("src/new.py", HEAD): "NAME = 'new'\nV = 1\n"}
    )
    ctx = _expand(repo, [_f("src/new.py", "renamed", prev="src/old.py")])
    assert [(c.path.rsplit("/contents/", 1)[1], c.params["ref"]) for c in repo.content_calls()] == [
        ("src/old.py", MB),
        ("src/new.py", HEAD),
    ]
    diff = ctx.files[0].diff
    assert diff.startswith("--- a/src/old.py\n+++ b/src/new.py\n")
    assert "-NAME = 'old'\n+NAME = 'new'\n" in diff


def test_renamed_without_edits_has_empty_body_and_is_still_listed():
    repo = Repo({("a.py", MB): "x\n", ("b.py", HEAD): "x\n"})
    ctx = _expand(repo, [_f("b.py", "renamed", add=0, dele=0, prev="a.py", patch=None)])
    assert [(f.filename, f.previous_filename, f.diff) for f in ctx.files] == [("b.py", "a.py", "")]
    assert ctx.head_contents == {"b.py": "x\n"}


def test_base_blob_is_fetched_at_the_merge_base_not_the_pull_base():
    repo = Repo({("m.py", MB): "a\n", ("m.py", HEAD): "b\n"})
    ctx = _expand(repo, [_f("m.py")])
    refs = {c.params["ref"] for c in repo.content_calls()}
    assert refs == {MB, HEAD}
    assert BASE not in refs
    assert ctx.merge_base_sha == MB
    compare_calls = [c for c in repo.stub.calls if "/compare/" in c.path]
    assert [c.path for c in compare_calls] == [f"{P}/compare/{BASE}...{HEAD}"]


@pytest.mark.parametrize(
    ("base", "head", "expected"),
    [
        ("", "", ""),
        ("", "x\n", "--- a/e.py\n+++ b/e.py\n@@ -0,0 +1 @@\n+x\n"),
        ("x\n", "", "--- a/e.py\n+++ b/e.py\n@@ -1 +0,0 @@\n-x\n"),
        (
            "a\nb",
            "a\nc",
            "--- a/e.py\n+++ b/e.py\n@@ -1,2 +1,2 @@\n a\n-b\n\\ No newline at end of file\n+c\n\\ No newline at end of file\n",
        ),
        ("a\n", "a", "--- a/e.py\n+++ b/e.py\n@@ -1 +1 @@\n-a\n+a\n\\ No newline at end of file\n"),
        ("a\r\nb\r\n", "a\r\nc\r\n", "--- a/e.py\n+++ b/e.py\n@@ -1,2 +1,2 @@\n a\r\n-b\r\n+c\r\n"),
    ],
    ids=[
        "both-empty",
        "empty-to-one",
        "one-to-empty",
        "no-eof-newline",
        "eof-newline-removed",
        "crlf",
    ],
)
def test_edge_texts_do_not_crash_and_are_exact(base, head, expected):
    assert unified_diff("e.py", "e.py", base, head, "modified") == expected
    assert unified_diff("e.py", "e.py", base, head, "modified") == expected  # deterministic


def test_line_split_is_on_newline_only():
    """U+2028, form feed, or a lone CR inside a line do not start a new line."""
    base = "a b\x0cc\rd\n"
    head = "a b\x0cc\rD\n"
    out = unified_diff("u.txt", "u.txt", base, head, "modified")
    assert out.splitlines(keepends=False)[2] == "@@ -1 +1 @@"


def test_two_changes_120_lines_apart_are_two_hunks_and_60_apart_are_one():
    base = _lines(400)
    far = base.replace("line 100\n", "X\n").replace("line 220\n", "Y\n")
    near = base.replace("line 100\n", "X\n").replace("line 160\n", "Y\n")
    assert unified_diff("f", "f", base, far, "modified").count("\n@@ ") == 2
    assert unified_diff("f", "f", base, near, "modified").count("\n@@ ") == 1


def test_header_paths_escape_control_characters():
    """A file name with a newline cannot forge extra diff lines."""
    out = unified_diff("a\n+++ b/evil", "a\n+++ b/evil", "x\n", "y\n", "modified")
    assert out.splitlines()[:2] == ["--- a/a\\n+++ b/evil", "+++ b/a\\n+++ b/evil"]


# -- AC4 head contents -----------------------------------------------------------


def test_head_contents_for_reviewed_non_removed_files_only_and_invalid_utf8_is_replaced():
    repo = Repo(
        {
            ("a.py", MB): "x\n",
            ("a.py", HEAD): b"caf\xe9 \xff\n",
            ("gone.py", MB): "y\n",
            ("new.py", HEAD): "z\n",
        }
    )
    files = [_f("a.py"), _f("gone.py", "removed"), _f("new.py", "added"), _f("yarn.lock")]
    ctx = _expand(repo, files)
    assert ctx.head_contents == {"a.py": "caf� �\n", "new.py": "z\n"}
    assert "+caf� �\n" in ctx.files[0].diff
    assert not any("yarn.lock" in c.path for c in repo.stub.calls)


def test_diff_text_concatenates_file_diffs_in_files_list_order():
    repo = Repo({("b.py", HEAD): "b\n", ("a.py", HEAD): "a\n"})
    ctx = _expand(repo, [_f("b.py", "added"), _f("a.py", "added")])
    assert [f.filename for f in ctx.files] == ["b.py", "a.py"]
    assert ctx.diff_text == ctx.files[0].diff + ctx.files[1].diff
    assert ctx.changed_ranges == {"b.py": ((1, 1),), "a.py": ((1, 1),)}


# -- TC-206-03 binary by NUL in the first 8 KB -----------------------------------


def test_nul_in_first_8kb_of_fetched_content_moves_the_file_to_name_only_binary():
    assert NUL_SCAN_BYTES == 8192
    early = b"x" * (NUL_SCAN_BYTES - 1) + b"\x00rest\n"  # NUL is byte 8,192
    late = b"x" * NUL_SCAN_BYTES + b"\x00rest\n"  # NUL is byte 8,193
    repo = Repo(
        {("early.dat", HEAD): early, ("late.dat", HEAD): late, ("old.bin", MB): b"\x00\x01"}
    )
    files = [_f("early.dat", "added"), _f("late.dat", "added"), _f("old.bin", "removed")]
    ctx = _expand(repo, files)
    assert [f.filename for f in ctx.files] == ["late.dat"]
    assert ctx.name_only == (
        NameOnlyFile("early.dat", "added", "binary"),
        NameOnlyFile("old.bin", "removed", "binary"),
    )
    assert "early.dat" not in ctx.head_contents
    assert ctx.changed_lines == 6  # counted before the NUL check (DF-22)


def test_nul_in_the_base_blob_also_marks_binary():
    repo = Repo({("m.dat", MB): b"\x00", ("m.dat", HEAD): b"text\n"})
    ctx = _expand(repo, [_f("m.dat")])
    assert ctx.files == ()
    assert ctx.name_only == (NameOnlyFile("m.dat", "modified", "binary"),)


# -- carry-forward 1: unfetchable paths -------------------------------------------


def test_backslash_filename_is_content_unavailable_not_a_run_failure():
    """The S-205 guard raises ``ForbiddenCall`` for a decoded ``\\``; it still fails closed."""
    repo = Repo({("ok.py", HEAD): "fine\n"})
    files = [_f("dir/a\\b.py", "added"), _f("ok.py", "added")]
    with pytest.raises(ForbiddenCall):
        repo.client().get_content_raw("dir/a\\b.py", HEAD)  # the guard is unchanged
    repo.stub.calls.clear()

    ctx = _expand(repo, files)
    assert [f.filename for f in ctx.files] == ["ok.py"]
    (na,) = ctx.name_only
    assert (na.filename, na.reason) == ("dir/a\\b.py", "content_unavailable")
    assert na.detail == "path cannot be fetched safely"
    assert not any("%5C" in c.path or "\\" in c.path for c in repo.stub.calls)


def test_backslash_previous_filename_is_content_unavailable():
    repo = Repo({("new.py", HEAD): "x\n"})
    ctx = _expand(repo, [_f("new.py", "renamed", prev="old\\name.py")])
    assert ctx.files == ()
    assert ctx.name_only[0].reason == "content_unavailable"


def test_a_404_blob_is_content_unavailable():
    repo = Repo({("m.py", MB): "a\n"})
    repo.blob("m.py", HEAD, StubResponse(404, b'{"message":"Not Found"}'))
    ctx = _expand(repo, [_f("m.py")])
    assert ctx.files == ()
    assert ctx.name_only == (
        NameOnlyFile("m.py", "modified", "content_unavailable", "not found at the reviewed commit"),
    )


# -- carry-forward 4: error propagation -------------------------------------------


def test_compare_404_propagates_as_github_not_found():
    repo = Repo({("m.py", HEAD): "a\n"})
    repo.stub.add(("GET", f"{P}/compare/{BASE}...{HEAD}"), StubResponse(404, b"{}"))
    with pytest.raises(GitHubNotFound):
        _expand(repo, [_f("m.py")])
    assert repo.content_calls() == []


def test_malformed_merge_base_sha_is_an_api_error():
    repo = Repo()
    repo.stub.add(
        ("GET", f"{P}/compare/{BASE}...{HEAD}"),
        json_response({"merge_base_commit": {"sha": "main"}}),
    )
    with pytest.raises(GitHubApiError, match="merge base"):
        _expand(repo, [_f("m.py")])
    assert repo.content_calls() == []


def test_blob_server_error_propagates_as_api_error():
    repo = Repo({("m.py", MB): "a\n"})
    repo.blob("m.py", HEAD, StubResponse(502, b""))
    with pytest.raises(GitHubApiError):
        _expand(repo, [_f("m.py")])


# -- carry-forward 2 / TC-206-20: thread pool ------------------------------------


def test_each_worker_thread_gets_its_own_client():
    repo = Repo({(f"f{i}.py", HEAD): f"{i}\n" for i in range(20)})
    made: list[tuple[int, GitHubClient]] = []
    used: dict[int, set[int]] = {}
    lock = threading.Lock()

    def factory() -> GitHubClient:
        client = repo.client()
        original = client.get_content_bytes

        def tracked(path, ref):
            with lock:
                used.setdefault(id(client), set()).add(threading.get_ident())
            return original(path, ref)

        client.get_content_bytes = tracked  # type: ignore[method-assign]
        with lock:
            made.append((threading.get_ident(), client))
        return client

    main = repo.client()
    ctx = expanded_diff(
        main,
        _pull(),
        classify([_f(f"f{i}.py", "added") for i in range(20)]),
        client_factory=factory,
    )
    assert len(ctx.files) == 20
    assert 1 <= len(made) <= MAX_WORKERS == 8
    assert len({tid for tid, _ in made}) == len(made)  # one client per thread
    assert all(len(threads) == 1 for threads in used.values())  # never shared
    assert threading.get_ident() not in {tid for tid, _ in made}


def test_output_order_follows_files_list_even_when_fetches_complete_in_reverse():
    names = [f"f{i}.py" for i in range(4)]
    done = {name: threading.Event() for name in names}
    completion: list[str] = []

    class ReverseTransport(StubTransport):
        def request(self, method, url, **kw):
            if "/compare/" in url:
                return json_response({"merge_base_commit": {"sha": MB}})
            name = url.rsplit("/", 1)[-1]
            later = names.index(name) + 1
            if later < len(names):
                assert done[names[later]].wait(5), "fetches did not run concurrently"
            resp = StubResponse(200, f"{name}\n".encode())
            completion.append(name)
            done[name].set()
            return resp

    stub = ReverseTransport()

    def factory() -> GitHubClient:
        return GitHubClient("tok", ORG, REPO, N, transport=stub)

    cls = classify([_f(n, "added") for n in names])
    ctx = expanded_diff(factory(), _pull(), cls, client_factory=factory)
    assert completion == list(reversed(names))
    assert [f.filename for f in ctx.files] == names
    assert list(ctx.head_contents) == names


@pytest.mark.parametrize("workers", [0, 9, -1])
def test_max_workers_is_bounded_to_the_spec_value(workers):
    repo = Repo()
    with pytest.raises(ValueError):
        expanded_diff(
            repo.client(),
            _pull(),
            Classification((), ()),
            client_factory=repo.client,
            max_workers=workers,
        )
