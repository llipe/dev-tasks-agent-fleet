"""
PRD v1.4 D-63 — the Git tree read (spec §6.2; ADR-010 addendum, decision 4).

``GET /repos/{o}/{r}/git/trees/{sha}?recursive=1`` is the one read added to the
allowlist. It is bound to the invoked repository and to the PR's head SHA:
before ``bind_head_sha`` it is refused, and any other SHA is refused, both
before anything is sent. A truncated tree returns what GitHub sent.
"""

from __future__ import annotations

import pytest

from github_client import (
    ForbiddenCall,
    GitHubClient,
    GitHubMalformedResponse,
    GitHubNotFound,
    GitTree,
    TreeEntry,
)
from tests.helpers.github_stub import StubTransport, json_response

TOKEN = "ghs_SENTINEL0123456789abcdefTOKEN"
ORG, REPO, PR = "acme", "widgets", 42
HEAD = "9f2c4e1a7b3d5f60812a4c6e8b0d2f4a6c8e0b1d"
OTHER = "0123456789abcdef0123456789abcdef01234567"
TREE_PATH = f"/repos/{ORG}/{REPO}/git/trees/{HEAD}"
TREE_Q = (("recursive", "1"),)


def _client(stub: StubTransport, bind: str | None = HEAD) -> GitHubClient:
    client = GitHubClient(TOKEN, ORG, REPO, PR, transport=stub, sleep=lambda s: None)
    if bind is not None:
        client.bind_head_sha(bind)
    return client


def _tree(entries, truncated=False):
    return json_response({"sha": HEAD, "url": "x", "tree": entries, "truncated": truncated})


def test_tree_read_parses_entries():
    stub = StubTransport(
        {
            ("GET", TREE_PATH, TREE_Q): _tree(
                [
                    {"path": "docs", "mode": "040000", "type": "tree", "sha": "a"},
                    {"path": "docs/a.md", "mode": "100644", "type": "blob", "sha": "b", "size": 12},
                    {"path": "vendor/lib", "mode": "160000", "type": "commit", "sha": "c"},
                ]
            )
        }
    )
    tree = _client(stub).get_tree(HEAD)
    assert tree == GitTree(
        entries=(
            TreeEntry("docs", "tree", None),
            TreeEntry("docs/a.md", "blob", 12),
            TreeEntry("vendor/lib", "commit", None),
        ),
        truncated=False,
    )
    call = stub.calls[0]
    assert (call.method, call.path, call.params) == ("GET", TREE_PATH, {"recursive": 1})


def test_a_truncated_tree_returns_what_github_sent():
    stub = StubTransport(
        {("GET", TREE_PATH, TREE_Q): _tree([{"path": "a.md", "type": "blob"}], True)}
    )
    tree = _client(stub).get_tree(HEAD)
    assert tree.truncated is True
    assert tree.entries == (TreeEntry("a.md", "blob", None),)


@pytest.mark.parametrize("size", [-1, True, "12", 1.5])
def test_a_bad_size_is_unknown(size):
    stub = StubTransport(
        {("GET", TREE_PATH, TREE_Q): _tree([{"path": "a.md", "type": "blob", "size": size}])}
    )
    assert _client(stub).get_tree(HEAD).entries[0].size is None


@pytest.mark.parametrize(
    "body",
    [
        [],
        {"tree": "x"},
        {"tree": [{"type": "blob"}]},
        {"tree": [{"path": 1, "type": "blob"}]},
        {"tree": [{"path": "a", "type": None}]},
        {"tree": [], "truncated": "yes"},
    ],
)
def test_a_malformed_tree_is_a_malformed_response(body):
    stub = StubTransport({("GET", TREE_PATH, TREE_Q): json_response(body)})
    with pytest.raises(GitHubMalformedResponse):
        _client(stub).get_tree(HEAD)


def test_a_missing_tree_is_not_found():
    stub = StubTransport({("GET", TREE_PATH, TREE_Q): json_response({}, status=404)})
    with pytest.raises(GitHubNotFound):
        _client(stub).get_tree(HEAD)


def test_the_tree_read_is_refused_before_the_head_is_bound():
    stub = StubTransport()
    with pytest.raises(ForbiddenCall):
        _client(stub, bind=None).get_tree(HEAD)
    assert stub.calls == []


def test_another_sha_is_refused():
    stub = StubTransport()
    with pytest.raises(ForbiddenCall):
        _client(stub).get_tree(OTHER)
    assert stub.calls == []


@pytest.mark.parametrize("sha", ["main", HEAD[:7], HEAD.upper(), "../" + HEAD, HEAD + "/x", ""])
def test_bind_head_sha_requires_a_full_hex_sha(sha):
    client = GitHubClient(TOKEN, ORG, REPO, PR, transport=StubTransport())
    with pytest.raises(ForbiddenCall):
        client.bind_head_sha(sha)


def test_the_head_cannot_be_rebound():
    client = _client(StubTransport())
    with pytest.raises(ForbiddenCall):
        client.bind_head_sha(OTHER)


def test_the_tree_template_accepts_only_the_recursive_query():
    client = _client(StubTransport())
    with pytest.raises(ForbiddenCall):
        client._request("GET", TREE_PATH, params={"recursive": 1, "page": 2})
    with pytest.raises(ForbiddenCall):
        client._request("GET", f"/repos/{ORG}/{REPO}/git/trees/{OTHER}", params={"recursive": 1})
    with pytest.raises(ForbiddenCall):
        client._request("GET", f"/repos/{ORG}/{REPO}/git/trees/{HEAD}/x")
    with pytest.raises(ForbiddenCall):
        client._request("POST", TREE_PATH)


@pytest.mark.parametrize("sha", ["main", HEAD[:7], 7])
def test_get_tree_requires_a_full_hex_sha(sha):
    stub = StubTransport()
    with pytest.raises(ForbiddenCall):
        _client(stub).get_tree(sha)
    assert stub.calls == []
