"""L1 tests for ``refusal.py`` (S-185 AC2, AC3; TC-185-16, TC-185-17; D-92, D-104).

- The decision table, first match wins: ``pull_request``, ``closed``,
  ``linked_pr``, ``active_run`` (plus ``invalid_params``, decided before it).
- The fixed reply per code, as an exact snapshot.
- A refusal marker is never a claim.
"""

from __future__ import annotations

import pytest

from issues import IssueFacts, LinkedPr
from markers import REFUSAL_REASONS, build, parse_block
from params import SCHEMA_KEYS
from refusal import (
    INVALID_PARAMS_KEYS,
    NON_TERMINAL_STATUSES,
    REPLY_TEXT,
    REPO_GATE_ITEMS,
    TERMINAL_STATUSES,
    Refusal,
    build_reply,
    decide,
    open_claim_runs,
    reply_line,
)

RUN = "0b9a2f4e-1c3d-4e5f-8a6b-7c8d9e0f1a2b"
OTHER = "1c0b3e5f-2d4e-4f60-9b7c-8d9e0f1a2b3c"
THIRD = "2d1c4f60-3e5f-4071-8c8d-9e0f1a2b3c4d"
APP_ID = 424242
LINK = "https://panel.example/runs/" + RUN


def _facts(*, state="open", pr=False, number=42) -> IssueFacts:
    return IssueFacts(number=number, state=state, is_pull_request=pr)


def _never(*_a):
    raise AssertionError("a later check ran after an earlier match")


# ---------------------------------------------------------------------------
# TC-185-16: decision table, first match wins
# ---------------------------------------------------------------------------


class TestDecisionTable:
    @pytest.mark.parametrize("state", ["open", "closed"])
    def test_a_pull_request_open_or_closed_is_pull_request(self, state):
        got = decide(_facts(state=state, pr=True), _never, _never)
        assert got == Refusal("pull_request")

    def test_a_closed_issue_with_a_linked_pr_is_closed(self):
        assert decide(_facts(state="closed"), _never, _never) == Refusal("closed")

    def test_an_open_issue_with_a_linked_pr_and_an_active_run_is_linked_pr(self):
        got = decide(_facts(), lambda: LinkedPr(17), _never)
        assert got == Refusal("linked_pr", pr_number=17)

    def test_a_cross_repo_linked_pr_keeps_its_repository(self):
        got = decide(_facts(), lambda: LinkedPr(5, "other-org/lib"), _never)
        assert got == Refusal("linked_pr", pr_number=5, pr_repo="other-org/lib")

    def test_an_open_issue_with_only_an_active_run_is_active_run(self):
        assert decide(_facts(), lambda: None, lambda: True) == Refusal("active_run")

    def test_an_open_issue_with_none_of_them_proceeds(self):
        assert decide(_facts(), lambda: None, lambda: False) is None

    @pytest.mark.parametrize("state", ["", "OPEN", "locked", "all"])
    def test_any_state_but_open_is_closed(self, state):
        assert decide(_facts(state=state), _never, _never) == Refusal("closed")

    def test_checks_run_in_order(self):
        order: list[str] = []

        def linked():
            order.append("linked_pr")
            return None

        def active():
            order.append("active_run")
            return False

        decide(_facts(), linked, active)
        assert order == ["linked_pr", "active_run"]

    def test_the_input_type_carries_no_labels(self):
        assert set(IssueFacts.__dataclass_fields__) == {"number", "state", "is_pull_request"}

    def test_a_fault_in_a_check_propagates_and_is_never_read_as_no_match(self):
        class Boom(Exception):
            pass

        def linked():
            raise Boom

        with pytest.raises(Boom):
            decide(_facts(), linked, _never)


# ---------------------------------------------------------------------------
# TC-185-17: reply snapshot per code
# ---------------------------------------------------------------------------

SNAPSHOTS = {
    "pull_request": (
        Refusal("pull_request"),
        "Bug-fix didn't start: #42 is a pull request. Comment `/bug-fix` on an issue instead.",
    ),
    "closed": (
        Refusal("closed"),
        "Bug-fix didn't start: #42 is closed. Reopen it, then comment `/bug-fix` again.",
    ),
    "linked_pr": (
        Refusal("linked_pr", pr_number=17),
        "Bug-fix didn't start: pull request #17 is already open for #42. "
        "Close it or finish it before asking for another fix.",
    ),
    "active_run": (
        Refusal("active_run"),
        "Bug-fix didn't start: another bug-fix run is already working on #42. "
        "Wait for it to finish, then comment `/bug-fix` again if it's still needed.",
    ),
    "repo_gate": (
        Refusal("repo_gate", detail=".claude/agents/developer.md"),
        "Bug-fix didn't start: this repository is missing `.claude/agents/developer.md`, "
        "which bug-fix needs before it can work here.",
    ),
    "invalid_params": (
        Refusal("invalid_params", detail="max_turns"),
        "Bug-fix didn't start: the run parameter `max_turns` is missing or invalid.",
    ),
}


class TestReplySnapshot:
    def test_every_code_has_a_snapshot(self):
        assert set(SNAPSHOTS) == set(REFUSAL_REASONS) == set(REPLY_TEXT)

    @pytest.mark.parametrize("code", sorted(SNAPSHOTS))
    def test_exact_body(self, code):
        refusal, line = SNAPSHOTS[code]
        body = build_reply(RUN, refusal, 42, run_link=LINK)
        assert body == (
            f"<!-- agent-fleet:bug-fix:refusal run_id={RUN} reason={code} -->\n{line}\nRun: {LINK}"
        )
        assert reply_line(refusal, 42) == line

    @pytest.mark.parametrize("code", sorted(SNAPSHOTS))
    def test_line_one_parses_back_to_the_refusal(self, code):
        body = build_reply(RUN, SNAPSHOTS[code][0], 42, run_link=LINK)
        (marker,) = parse_block(body)
        assert (marker.kind, marker.run_id, marker.reason) == ("refusal", RUN, code)

    def test_without_a_run_link_the_run_id_is_named(self):
        body = build_reply(RUN, Refusal("closed"), 42)
        assert body.splitlines()[-1] == f"Run: `{RUN}`"

    @pytest.mark.parametrize(
        "link",
        ["http://panel.example/runs/x", "javascript:alert(1)", "https://x y", "", "@octocat"],
    )
    def test_an_unsafe_run_link_falls_back_to_the_run_id(self, link):
        assert build_reply(RUN, Refusal("closed"), 42, run_link=link).endswith(f"`{RUN}`")

    def test_an_uppercase_run_id_is_canonicalized(self):
        body = build_reply(RUN.upper(), Refusal("closed"), 42)
        assert parse_block(body)[0].run_id == RUN

    def test_no_body_starts_with_the_trigger(self):
        for refusal, _ in SNAPSHOTS.values():
            assert not build_reply(RUN, refusal, 42).startswith("/bug-fix")

    def test_the_reply_carries_no_reaction_or_model_text(self):
        body = build_reply(RUN, Refusal("closed"), 42, run_link=LINK)
        assert len(body.splitlines()) == 3


class TestReplyInputsAreClosedSets:
    def test_invalid_params_keys_are_the_schema_keys_plus_params(self):
        assert set(INVALID_PARAMS_KEYS) == set(SCHEMA_KEYS) | {"params"}

    @pytest.mark.parametrize("key", ["@octocat", "Fixes #1", "max_turns\n/bug-fix", "x" * 101])
    def test_an_unknown_invalid_params_key_is_refused(self, key):
        with pytest.raises(ValueError):
            build_reply(RUN, Refusal("invalid_params", detail=key), 42)

    @pytest.mark.parametrize("item", ["README.md", "`x`", "../../etc/passwd", None])
    def test_an_unknown_repo_gate_item_is_refused(self, item):
        with pytest.raises(ValueError):
            build_reply(RUN, Refusal("repo_gate", detail=item), 42)

    @pytest.mark.parametrize("item", REPO_GATE_ITEMS)
    def test_every_repo_gate_item_renders(self, item):
        """Each item renders its fixed phrase (DF-189-05)."""
        from refusal import REPO_GATE_PHRASES

        reply = build_reply(RUN, Refusal("repo_gate", detail=item), 42)
        assert REPO_GATE_PHRASES[item] in reply

    @pytest.mark.parametrize("pr", [None, 0, -1, True, "17", 1.5])
    def test_linked_pr_needs_a_positive_int(self, pr):
        with pytest.raises(ValueError):
            build_reply(RUN, Refusal("linked_pr", pr_number=pr), 42)

    @pytest.mark.parametrize("issue", [0, -1, True, "42"])
    def test_the_issue_number_must_be_a_positive_int(self, issue):
        with pytest.raises(ValueError):
            build_reply(RUN, Refusal("closed"), issue)

    def test_an_unknown_code_is_refused(self):
        with pytest.raises(ValueError):
            build_reply(RUN, Refusal("labels"), 42)

    @pytest.mark.parametrize("code", ["pull_request", "closed", "active_run"])
    def test_codes_without_detail_refuse_one(self, code):
        with pytest.raises(ValueError):
            build_reply(RUN, Refusal(code, detail="x"), 42)


# ---------------------------------------------------------------------------
# A refusal marker is never a claim (D-104); trust and lifecycle (D-53)
# ---------------------------------------------------------------------------


def _comment(cid: int, body: str, *, app_id=APP_ID, user_type="Bot") -> dict:
    return {
        "id": cid,
        "body": body,
        "user": {"type": user_type},
        "performed_via_github_app": None if app_id is None else {"id": app_id},
    }


class TestOpenClaimRuns:
    def test_a_trusted_open_claim_counts(self):
        comments = [_comment(1, build("claim", OTHER) + "\ntext")]
        assert open_claim_runs(comments, APP_ID, own_run_id=RUN) == [OTHER]

    def test_a_refusal_marker_is_never_a_claim(self):
        comments = [_comment(1, build("refusal", OTHER, "active_run") + "\ntext")]
        assert open_claim_runs(comments, APP_ID, own_run_id=RUN) == []

    def test_a_trusted_refusal_for_the_same_run_closes_its_claim(self):
        comments = [
            _comment(1, build("claim", OTHER)),
            _comment(2, build("refusal", OTHER, "repo_gate")),
        ]
        assert open_claim_runs(comments, APP_ID, own_run_id=RUN) == []

    @pytest.mark.parametrize("kind", ["pr", "disposition"])
    def test_a_pr_or_disposition_closes_the_claim(self, kind):
        comments = [_comment(1, build("claim", OTHER)), _comment(2, build(kind, OTHER))]
        assert open_claim_runs(comments, APP_ID, own_run_id=RUN) == []

    @pytest.mark.parametrize(
        "forged",
        [
            {"app_id": None},
            {"app_id": 1},
            {"user_type": "User"},
        ],
    )
    def test_an_untrusted_claim_is_ignored(self, forged):
        comments = [_comment(1, build("claim", OTHER), **forged)]
        assert open_claim_runs(comments, APP_ID, own_run_id=RUN) == []

    def test_a_forged_closing_marker_does_not_close_a_trusted_claim(self):
        comments = [
            _comment(1, build("claim", OTHER)),
            _comment(2, build("disposition", OTHER), user_type="User"),
            _comment(3, build("refusal", OTHER, "closed"), app_id=7),
        ]
        assert open_claim_runs(comments, APP_ID, own_run_id=RUN) == [OTHER]

    def test_this_runs_own_claim_is_excluded(self):
        comments = [_comment(1, build("claim", RUN)), _comment(2, build("claim", OTHER))]
        assert open_claim_runs(comments, APP_ID, own_run_id=RUN) == [OTHER]

    def test_run_ids_are_unique_and_in_comment_order(self):
        comments = [
            _comment(5, build("claim", THIRD)),
            _comment(2, build("claim", OTHER)),
            _comment(9, build("claim", OTHER)),
        ]
        assert open_claim_runs(comments, APP_ID) == [OTHER, THIRD]


def test_status_sets_cover_the_run_status_enum():
    enum = {"queued", "running", "succeeded", "failed", "timed_out", "failed_to_start", "canceled"}
    assert {"queued", "running"} == NON_TERMINAL_STATUSES
    assert enum == NON_TERMINAL_STATUSES | TERMINAL_STATUSES
    assert not NON_TERMINAL_STATUSES & TERMINAL_STATUSES


def test_refusal_is_a_value_object():
    r = Refusal("linked_pr", pr_number=3)
    with pytest.raises(AttributeError):
        r.reason = "closed"  # type: ignore[misc]


class TestReplyLineGuards:
    def test_an_unknown_code_is_refused_by_the_line_too(self):
        with pytest.raises(ValueError):
            reply_line(Refusal("labels"), 42)

    @pytest.mark.parametrize("code", ["pull_request", "closed", "active_run"])
    def test_a_pr_number_on_another_code_is_refused(self, code):
        with pytest.raises(ValueError):
            reply_line(Refusal(code, pr_number=3), 42)

    @pytest.mark.parametrize("issue", [0, -2, True])
    def test_a_bad_issue_number_is_refused_even_when_unused(self, issue):
        with pytest.raises(ValueError):
            reply_line(Refusal("invalid_params", detail="max_turns"), issue)

    def test_invalid_params_and_repo_gate_need_no_issue(self):
        assert "`issue_number`" in reply_line(
            Refusal("invalid_params", detail="issue_number"), None
        )
        assert "`lint`" in reply_line(Refusal("repo_gate", detail="lint"), None)


def test_the_v_runs_reader_makes_no_call_for_no_ids():
    from refusal import RunStatusReader

    class NoCalls:
        def get(self, *a, **k):
            raise AssertionError("no read expected")

    assert RunStatusReader("https://sb", "k", session=NoCalls()).effective_statuses([]) == {}


# ---------------------------------------------------------------------------
# QA 2: an unknown v_runs.effective_status fails closed
# ---------------------------------------------------------------------------


class TestHasActiveRunStatuses:
    def _run(self, statuses, warnings=None):
        from refusal import has_active_run

        comments = [_comment(1, build("claim", OTHER))]
        return has_active_run(
            comments,
            APP_ID,
            RUN,
            lambda ids: {i: statuses[i] for i in ids if i in statuses},
            warn=None if warnings is None else warnings.append,
        )

    @pytest.mark.parametrize("status", sorted(NON_TERMINAL_STATUSES))
    def test_a_known_active_status_is_active(self, status):
        assert self._run({OTHER: status}) is True

    @pytest.mark.parametrize("status", sorted(TERMINAL_STATUSES))
    def test_a_known_terminal_status_is_not(self, status):
        assert self._run({OTHER: status}) is False

    def test_a_missing_row_counts_as_finished_with_a_warning(self):
        warnings: list[str] = []
        assert self._run({}, warnings) is False
        assert len(warnings) == 1 and "no v_runs row" in warnings[0]

    @pytest.mark.parametrize("status", ["paused", "", "RUNNING", "Queued", "running ", "stale"])
    def test_an_unknown_status_is_supabase_unavailable_with_a_warning(self, status):
        from refusal import SupabaseUnavailable

        warnings: list[str] = []
        with pytest.raises(SupabaseUnavailable) as exc:
            self._run({OTHER: status}, warnings)
        assert exc.value.code == "SUPABASE_UNAVAILABLE"
        assert len(warnings) == 1 and "unknown effective_status" in warnings[0]
        assert OTHER in warnings[0]

    def test_without_a_warn_callback_the_warning_is_logged(self, caplog):
        import logging

        from refusal import SupabaseUnavailable

        with (
            caplog.at_level(logging.WARNING, logger="bug_fix.refusal"),
            pytest.raises(SupabaseUnavailable),
        ):
            self._run({OTHER: "paused"})
        assert any("unknown effective_status" in r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------------------
# DF-185-07: a cross-repository linked PR is named owner/repo#M
# ---------------------------------------------------------------------------


class TestCrossRepoReply:
    def test_a_cross_repo_pr_is_named_with_its_repository(self):
        line = reply_line(Refusal("linked_pr", pr_number=5, pr_repo="other-org/lib.js"), 42)
        assert line == (
            "Bug-fix didn't start: pull request other-org/lib.js#5 is already open for #42. "
            "Close it or finish it before asking for another fix."
        )

    def test_a_same_repo_pr_stays_bare(self):
        assert "pull request #5 is" in reply_line(Refusal("linked_pr", pr_number=5), 42)

    @pytest.mark.parametrize(
        "repo",
        [
            "other",
            "a/b/c",
            "../x",
            "o/..",
            "o/r#1",
            "@x/y",
            "a/ b",
            "",
            "o/r\n/bug-fix",
            5,
            "[x](y)/z",
        ],
    )
    def test_a_repository_outside_the_name_grammar_is_refused(self, repo):
        with pytest.raises(ValueError):
            reply_line(Refusal("linked_pr", pr_number=5, pr_repo=repo), 42)

    @pytest.mark.parametrize("code", ["pull_request", "closed", "active_run"])
    def test_a_repository_on_another_code_is_refused(self, code):
        with pytest.raises(ValueError):
            reply_line(Refusal(code, pr_repo="o/r"), 42)
