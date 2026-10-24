"""L1 tests for ``markers.py`` (S-186 AC1, AC2; D-53, D-80, D-104).

Covers TC-186-01 to TC-186-07 and TC-186-17, plus the CT-08 comment-object
cases (an id above 2**31, a ``null`` or absent App).
"""

from __future__ import annotations

import uuid

import pytest

import markers
from markers import (
    KINDS,
    REFUSAL_REASONS,
    Marker,
    build,
    build_block,
    canonical_run_id,
    has_trusted,
    is_trusted,
    open_claims,
    parse_block,
    trusted_markers,
)

APP_ID = 123456
RUN_A = "0b9a2f4e-1c3d-4e5f-8a6b-7c8d9e0f1a2b"
RUN_B = "1c0b3e5f-2d4e-4f60-9b7c-8d9e0f1a2b3c"
RUN_C = "2d1c4f60-3e5f-4071-8c8d-9e0f1a2b3c4d"


def _comment(
    cid: int,
    body: str,
    *,
    app_id: object = APP_ID,
    user_type: object = "Bot",
    login: str = "agent-fleet[bot]",
    app_key: bool = True,
) -> dict:
    c: dict = {"id": cid, "body": body, "user": {"login": login, "type": user_type}}
    if app_key:
        c["performed_via_github_app"] = None if app_id is None else {"id": app_id}
    return c


def _marked(cid: int, kind: str, run_id: str, reason: str | None = None, **kw) -> dict:
    return _comment(cid, build(kind, run_id, reason) + "\nvisible text", **kw)


# ---------------------------------------------------------------------------
# TC-186-01: round trip
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_kinds_and_reasons_are_the_spec_sets(self):
        assert KINDS == ("claim", "disposition", "refusal", "pr")
        assert REFUSAL_REASONS == (
            "pull_request",
            "closed",
            "linked_pr",
            "active_run",
            "repo_gate",
            "invalid_params",
        )

    @pytest.mark.parametrize("kind", ["claim", "disposition", "pr"])
    def test_non_refusal_kinds_round_trip(self, kind):
        for _ in range(20):
            run_id = str(uuid.uuid4())
            line = build(kind, run_id)
            assert line == f"<!-- agent-fleet:bug-fix:{kind} run_id={run_id} -->"
            assert parse_block(line + "\ntext") == (Marker(kind, run_id),)

    @pytest.mark.parametrize("reason", REFUSAL_REASONS)
    def test_refusal_round_trips_with_each_reason(self, reason):
        run_id = str(uuid.uuid4())
        line = build("refusal", run_id, reason)
        assert line == f"<!-- agent-fleet:bug-fix:refusal run_id={run_id} reason={reason} -->"
        assert parse_block(line) == (Marker("refusal", run_id, reason),)

    def test_build_canonicalizes_an_uppercase_run_id(self):
        upper = RUN_A.upper()
        assert build("claim", upper) == build("claim", RUN_A)

    @pytest.mark.parametrize(
        ("kind", "run_id", "reason"),
        [
            ("lock", RUN_A, None),
            ("claim", "not-a-uuid", None),
            ("claim", RUN_A, "closed"),
            ("refusal", RUN_A, None),
            ("refusal", RUN_A, "bogus"),
            ("claim", "", None),
        ],
    )
    def test_build_rejects_invalid_input(self, kind, run_id, reason):
        with pytest.raises(ValueError):
            build(kind, run_id, reason)

    def test_canonical_run_id(self):
        assert canonical_run_id(RUN_A.upper()) == RUN_A
        assert canonical_run_id("{" + RUN_A + "}") == RUN_A
        with pytest.raises(ValueError):
            canonical_run_id("x")
        with pytest.raises(ValueError):
            canonical_run_id(42)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# TC-186-02: not parsed
# ---------------------------------------------------------------------------

GOOD = f"<!-- agent-fleet:bug-fix:claim run_id={RUN_A} -->"


class TestNotParsed:
    @pytest.mark.parametrize(
        "body",
        [
            f"hello\n{GOOD}",  # after a non-marker line
            f" {GOOD}",  # leading space
            f"﻿{GOOD}",  # BOM
            f"​{GOOD}",  # zero-width space
            f"```\n{GOOD}\n```",  # inside a code fence
            GOOD.replace(RUN_A, RUN_A.upper()),  # uppercase UUID
            GOOD.replace(RUN_A, RUN_A[:-1]),  # 35 characters
            GOOD.replace(RUN_A, RUN_A + "0"),  # 37 characters
            GOOD.replace(RUN_A, "-" * 36),  # 36 hyphens
            GOOD.replace(" -->", ""),  # missing -->
            GOOD.replace(":claim ", ":lock "),  # unknown kind
            f"<!-- agent-fleet:bug-fix:refusal run_id={RUN_A} -->",  # no reason
            f"<!-- agent-fleet:bug-fix:refusal run_id={RUN_A} reason=bogus -->",
            f"<!-- agent-fleet:bug-fix:claim run_id={RUN_A} reason=closed -->",
            GOOD.replace("-", "‐"),  # Unicode hyphen look-alike
            GOOD.upper(),
            "",
        ],
    )
    def test_rejected(self, body):
        assert parse_block(body) == ()

    def test_trailing_text_after_close_on_line_one_is_not_parsed(self):
        # TC-186-03, pinned: the marker line must match exactly.
        assert parse_block(GOOD + " trailing") == ()
        assert parse_block(GOOD + " ") == ()

    @pytest.mark.parametrize("body", [None, 7, b"bytes"])
    def test_non_string_body(self, body):
        assert parse_block(body) == ()  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# TC-186-03 and TC-186-17: CRLF and the leading block
# ---------------------------------------------------------------------------


class TestLeadingBlock:
    def test_crlf_first_line_parses(self):
        assert parse_block(GOOD + "\r\nvisible") == (Marker("claim", RUN_A),)

    def test_two_marker_block_parses_as_both(self):
        body = build_block(
            [Marker("disposition", RUN_A), Marker("disposition", RUN_B)]
        ) + "\ndiagnosis"
        assert parse_block(body) == (
            Marker("disposition", RUN_A),
            Marker("disposition", RUN_B),
        )

    def test_crlf_block_parses(self):
        body = build("disposition", RUN_A) + "\r\n" + build("disposition", RUN_B) + "\r\ntext"
        assert len(parse_block(body)) == 2

    def test_marker_after_blank_line_is_outside_block(self):
        body = build("disposition", RUN_A) + "\n\n" + build("claim", RUN_B)
        assert parse_block(body) == (Marker("disposition", RUN_A),)

    def test_block_stops_at_first_non_marker_line(self):
        body = "\n".join([build("claim", RUN_A), "text", build("claim", RUN_B)])
        assert parse_block(body) == (Marker("claim", RUN_A),)

    def test_build_block_requires_at_least_one_marker(self):
        with pytest.raises(ValueError):
            build_block([])


# ---------------------------------------------------------------------------
# TC-186-04 and TC-186-05: trust
# ---------------------------------------------------------------------------


class TestTrust:
    def test_app_and_bot_is_trusted(self):
        assert is_trusted(_marked(1, "claim", RUN_A), APP_ID)

    def test_login_change_does_not_affect_trust(self):
        # TC-186-03: trust keys on the App id, never on the login.
        assert is_trusted(_marked(1, "claim", RUN_A, login="renamed-app[bot]"), APP_ID)

    @pytest.mark.parametrize("kind", KINDS)
    @pytest.mark.parametrize(
        "forgery",
        [
            {"app_id": None, "user_type": "User", "login": "mallory"},  # human, exact marker
            {"app_id": 999, "user_type": "Bot"},  # another App
            {"app_id": None},  # performed_via_github_app: null
            {"app_key": False},  # absent
            {"user_type": "User"},
            {"user_type": "Organization"},
            {"app_id": str(APP_ID)},  # "123" against the int 123
            {"app_id": True},
            {"app_id": float(APP_ID)},
        ],
    )
    def test_forgeries_are_untrusted(self, kind, forgery):
        reason = "closed" if kind == "refusal" else None
        comment = _marked(1, kind, RUN_A, reason, **forgery)
        assert not is_trusted(comment, APP_ID)
        assert trusted_markers([comment], APP_ID) == []

    @pytest.mark.parametrize(
        "comment",
        [
            {"id": 1, "body": GOOD},  # no user
            {"id": 1, "body": GOOD, "user": None, "performed_via_github_app": {"id": APP_ID}},
            {"id": 1, "body": GOOD, "user": {"type": "Bot"}, "performed_via_github_app": []},
            "not a mapping",
        ],
    )
    def test_malformed_comment_objects_are_untrusted(self, comment):
        assert not is_trusted(comment, APP_ID)

    def test_app_id_must_be_an_int(self):
        with pytest.raises(TypeError):
            is_trusted(_marked(1, "claim", RUN_A), str(APP_ID))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# TC-186-06 and TC-186-07: open claims
# ---------------------------------------------------------------------------


class TestOpenClaims:
    def test_disposition_closes_its_own_claim(self):
        comments = [
            _marked(1, "claim", RUN_A),
            _marked(2, "disposition", RUN_A),
            _marked(3, "claim", RUN_B),
        ]
        assert open_claims(comments, APP_ID) == [(3, RUN_B)]

    def test_pr_closes_its_own_claim(self):
        comments = [_marked(1, "claim", RUN_A), _marked(2, "pr", RUN_A)]
        assert open_claims(comments, APP_ID) == []

    def test_refusal_never_opens_or_closes_a_claim(self):
        comments = [_marked(1, "claim", RUN_A), _marked(2, "refusal", RUN_B, "active_run")]
        assert open_claims(comments, APP_ID) == [(1, RUN_A)]
        comments = [_marked(1, "claim", RUN_A), _marked(2, "refusal", RUN_A, "closed")]
        assert open_claims(comments, APP_ID) == [(1, RUN_A)]

    def test_order_comes_from_comment_id_not_list_order(self):
        comments = [_marked(1000, "claim", RUN_B), _marked(999, "claim", RUN_A)]
        assert open_claims(comments, APP_ID) == [(999, RUN_A), (1000, RUN_B)]

    def test_ids_above_2_31_compare_numerically(self):
        big = 2**31 + 5
        comments = [_marked(big + 10, "claim", RUN_B), _marked(big, "claim", RUN_A)]
        assert open_claims(comments, APP_ID) == [(big, RUN_A), (big + 10, RUN_B)]

    def test_untrusted_closer_does_not_close_a_trusted_claim(self):
        comments = [
            _marked(1, "claim", RUN_A),
            _marked(2, "disposition", RUN_A, app_id=None, user_type="User"),
            _marked(3, "pr", RUN_A, app_id=999),
        ]
        assert open_claims(comments, APP_ID) == [(1, RUN_A)]

    def test_another_runs_pr_does_not_close_this_claim(self):
        comments = [_marked(1, "claim", RUN_B), _marked(2, "pr", RUN_A)]
        assert open_claims(comments, APP_ID) == [(1, RUN_B)]

    def test_multi_run_disposition_closes_every_listed_claim(self):
        block = build_block([Marker("disposition", RUN_A), Marker("disposition", RUN_B)])
        comments = [
            _marked(1, "claim", RUN_A),
            _marked(2, "claim", RUN_B),
            _marked(3, "claim", RUN_C),
            _comment(4, block + "\ntext"),
        ]
        assert open_claims(comments, APP_ID) == [(3, RUN_C)]

    @pytest.mark.parametrize("cid", [None, "5", True, 0, -1, 1.5])
    def test_comment_without_a_valid_id_is_skipped(self, cid):
        comment = _marked(1, "claim", RUN_A)
        comment["id"] = cid
        assert open_claims([comment], APP_ID) == []

    def test_has_trusted(self):
        comments = [
            _marked(1, "disposition", RUN_A),
            _marked(2, "disposition", RUN_B, app_id=999),
        ]
        assert has_trusted(comments, APP_ID, "disposition", RUN_A)
        assert has_trusted(comments, APP_ID, "disposition", RUN_A.upper())
        assert not has_trusted(comments, APP_ID, "disposition", RUN_B)
        assert not has_trusted(comments, APP_ID, "claim", RUN_A)

    def test_trusted_markers_lists_comment_id_and_marker(self):
        comments = [_marked(7, "pr", RUN_A), _comment(8, "plain text")]
        assert trusted_markers(comments, APP_ID) == [(7, Marker("pr", RUN_A))]


def test_module_exports_prefix():
    assert markers.PREFIX == "agent-fleet:bug-fix"
