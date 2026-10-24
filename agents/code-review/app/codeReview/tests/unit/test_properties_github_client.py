"""
Property tactic for the S-205 write allowlist (new; seed 407001, 2,000 iterations).

Not one of the named RT-01..RT-12 tactics: an extra seeded check on top of the
example-based TC-205-04/06/13 cases, using the shared ``tests/helpers/prng.py``.

Properties:

- **Guard totality.** For any (method, path) built from GitHub-shaped segments,
  dot segments, encodings, and smuggling characters, ``_request`` either raises
  ``ForbiddenCall`` with zero transport calls, or sends exactly one request
  whose method is ``GET`` or ``POST`` and whose path stays under
  ``/repos/acme/widgets/``. A ``POST`` that reaches the transport is always the
  comment on PR 42.
- **Encoding round trip.** For any repository-like path without empty or dot
  segments, ``get_content_raw`` sends a path under ``.../contents/`` whose
  per-segment percent-decoding equals the input.
"""

from __future__ import annotations

from urllib.parse import unquote

import pytest

from github_client import ForbiddenCall, GitHubClient
from tests.helpers.github_stub import StubTransport, text_response
from tests.helpers.prng import Tactic, tactic_seed

PREFIX = "/repos/acme/widgets"
BASEHEAD = "9f2c4e1a7b3d5f60812a4c6e8b0d2f4a6c8e0b1d...3a5c7e9b1d3f5a7c9e1b3d5f7a9c1e3b5d7f9a1c"
SEGMENTS = [
    "repos", "acme", "widgets", "other", "pulls", "issues", "comments", "files",
    "contents", "compare", "merge", "reviews", "labels", "42", "41", "0", "-1",
    "..", ".", "%2e%2e", "%2E", "%2F", "", "a b", "a#b", "a?b", "ñ", "x%zz",
    BASEHEAD,
    "src", "app.py", "README.md", "graphql", "git", "refs",
]  # fmt: skip
SKELETONS = [
    ["pulls", "42"],
    ["pulls", "42", "files"],
    ["compare", BASEHEAD],
    ["contents", "src", "app.py"],
    ["issues", "41"],
    ["issues", "42", "comments"],
]
METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "get", "post", "HEAD"]
PATH_CHARS = "abcXYZ019 _-.~#?%&=+;:@!$'()*,ñé中\t"


def _client(stub: StubTransport) -> GitHubClient:
    return GitHubClient(
        "ghs_prop", "acme", "widgets", 42, transport=stub, sleep=lambda _s: None, clock=lambda: 0
    )


def test_guard_totality_property():
    tactic = Tactic.from_env(tactic_seed(407, 1), 2000)
    rng = tactic.rng()
    sent = 0
    for i in range(tactic.iterations):
        method = rng.choice(METHODS)
        if rng.random() < 0.5:
            # A valid skeleton, then up to two random segment mutations.
            segs = ["repos", "acme", "widgets", *rng.choice(SKELETONS)]
            for _ in range(rng.randint(0, 2)):
                if rng.random() < 0.5:
                    segs[rng.randrange(len(segs))] = rng.choice(SEGMENTS)
                elif rng.random() < 0.5:
                    segs.insert(rng.randrange(len(segs) + 1), rng.choice(SEGMENTS))
        else:
            segs = [rng.choice(SEGMENTS) for _ in range(rng.randint(0, 7))]
            if rng.random() < 0.6:
                segs = ["repos", "acme", "widgets", *segs]
        path = "/" + "/".join(segs)
        if rng.random() < 0.1:
            path = rng.choice(["https://evil.example", "http://api.github.com", "//x"]) + path
        if not tactic.selected(i):
            continue
        ctx = tactic.context(i, (method, path))
        stub = StubTransport(default=text_response("{}"))
        client = _client(stub)
        try:
            client._request(method, path)
        except ForbiddenCall:
            assert stub.calls == [], ctx
            continue
        except Exception:  # a JSON or API error after sending is fine here
            pass
        assert len(stub.calls) == 1, ctx
        call = stub.calls[0]
        sent += 1
        assert call.method in {"GET", "POST"}, ctx
        assert call.path.startswith(PREFIX + "/"), ctx
        assert call.url.startswith("https://api.github.com/repos/acme/widgets/"), ctx
        if call.method == "POST":
            assert call.path == f"{PREFIX}/issues/42/comments", ctx
    if not tactic.replaying:
        assert sent > 10, f"generator never produced an allowed call (seed={tactic.seed})"


def _repo_path(rng) -> str:
    parts = []
    for _ in range(rng.randint(1, 5)):
        seg = "".join(rng.choice(PATH_CHARS) for _ in range(rng.randint(1, 8)))
        if seg in {".", ".."}:
            seg += "x"
        parts.append(seg)
    return "/".join(parts)


def test_encoding_round_trip_property():
    tactic = Tactic.from_env(tactic_seed(407, 2), 2000)
    rng = tactic.rng()
    for i in range(tactic.iterations):
        path = _repo_path(rng)
        if not tactic.selected(i):
            continue
        ctx = tactic.context(i, path)
        stub = StubTransport(default=text_response("ok"))
        client = _client(stub)
        assert client.get_content_raw(path, "main") == "ok", ctx
        (call,) = stub.calls
        assert call.path.startswith(f"{PREFIX}/contents/"), ctx
        encoded = call.path[len(f"{PREFIX}/contents/") :]
        assert "/".join(unquote(s) for s in encoded.split("/")) == path, ctx
        assert all(c not in encoded for c in " #?\t"), ctx


@pytest.mark.parametrize("seed_k", [1, 2])
def test_tactic_seeds_follow_the_plan_formula(seed_k):
    assert tactic_seed(407, seed_k) == 407000 + seed_k
