"""L1 race verdicts for the post-claim check (S-188 AC2, AC5; D-54, D-104; DF-33).

``claim.race_winner`` answers one question: is there an open trusted claim with
a lower comment id than this run's own claim, belonging to another run that is
not terminal in ``v_runs.effective_status``? If so it names that run, and this
run lost.

One open-claim rule (DF-33, confirmed by @llipe 2026-10-24): a claim for run R
is open while no trusted ``pr``, ``disposition`` or ``refusal`` marker for R
exists. A missing ``v_runs`` row counts as finished, with a warning (CT-34); an
unknown status fails closed with ``SUPABASE_UNAVAILABLE`` (D-67).

TC-188-05, TC-188-06, TC-188-07, TC-188-16.
"""

from __future__ import annotations

import pytest

from claim import race_winner
from markers import build
from refusal import NON_TERMINAL_STATUSES, TERMINAL_STATUSES, SupabaseUnavailable

APP_ID = 424242
RUN = "0b9a2f4e-1c3d-4e5f-8a6b-7c8d9e0f1a2b"
OTHER = "1c0b3e5f-2d4e-4f60-9b7c-8d9e0f1a2b3c"
THIRD = "2d1c4f60-3e5f-4071-8c8d-9e0f1a2b3c4d"
OWN_CID = 2**31 + 100


def _comment(cid: int, body: str, *, app_id=APP_ID, user_type="Bot") -> dict:
    return {
        "id": cid,
        "body": body,
        "user": {"type": user_type},
        "performed_via_github_app": None if app_id is None else {"id": app_id},
    }


def _own() -> dict:
    return _comment(OWN_CID, build("claim", RUN) + "\nworking")


class Statuses:
    """A ``v_runs`` reader double that records what it was asked."""

    def __init__(self, statuses: dict[str, str]) -> None:
        self.statuses = statuses
        self.asked: list[list[str]] = []

    def __call__(self, ids):
        self.asked.append(list(ids))
        return {i: self.statuses[i] for i in ids if i in self.statuses}


def _winner(comments, statuses, *, warnings=None, own_cid=OWN_CID):
    return race_winner(
        comments,
        APP_ID,
        RUN,
        own_cid,
        statuses if callable(statuses) else Statuses(statuses),
        warn=None if warnings is None else warnings.append,
    )


# ---------------------------------------------------------------------------
# TC-188-05: an earlier terminal claim is ignored; an earlier active one wins
# ---------------------------------------------------------------------------


class TestEarlierClaim:
    @pytest.mark.parametrize("status", sorted(NON_TERMINAL_STATUSES))
    def test_an_earlier_active_claim_means_this_run_lost(self, status):
        comments = [_comment(OWN_CID - 5, build("claim", OTHER)), _own()]
        assert _winner(comments, {OTHER: status}) == OTHER

    @pytest.mark.parametrize("status", sorted(TERMINAL_STATUSES))
    def test_an_earlier_terminal_claim_is_ignored(self, status):
        comments = [_comment(OWN_CID - 5, build("claim", OTHER)), _own()]
        assert _winner(comments, {OTHER: status}) is None

    def test_no_other_claim_means_this_run_won_without_a_read(self):
        reader = Statuses({})
        assert _winner([_own()], reader) is None
        assert reader.asked == []

    def test_the_first_active_earlier_claim_is_named(self):
        comments = [
            _comment(10, build("claim", THIRD)),
            _comment(20, build("claim", OTHER)),
            _own(),
        ]
        assert _winner(comments, {THIRD: "succeeded", OTHER: "running"}) == OTHER
        assert _winner(comments, {THIRD: "queued", OTHER: "running"}) == THIRD


# ---------------------------------------------------------------------------
# TC-188-16: race-verdict inputs (D-54, D-104; DF-33)
# ---------------------------------------------------------------------------


class TestVerdictInputs:
    @pytest.mark.parametrize(
        "closing",
        [build("pr", OTHER), build("disposition", OTHER), build("refusal", OTHER, "repo_gate")],
        ids=["pr", "disposition", "refusal"],
    )
    def test_a_claim_closed_by_a_trusted_marker_is_ignored(self, closing):
        # The closing marker may come after this run's claim: it still closes.
        comments = [
            _comment(OWN_CID - 5, build("claim", OTHER)),
            _own(),
            _comment(OWN_CID + 5, closing),
        ]
        reader = Statuses({OTHER: "running"})
        assert _winner(comments, reader) is None
        assert reader.asked == []

    def test_a_refusal_marker_is_never_counted_as_a_claim(self):
        comments = [_comment(OWN_CID - 5, build("refusal", OTHER, "active_run")), _own()]
        assert _winner(comments, {OTHER: "running"}) is None

    def test_this_runs_own_claim_is_excluded(self):
        comments = [_comment(OWN_CID - 5, build("claim", RUN)), _own()]
        assert _winner(comments, {RUN: "running"}) is None

    def test_a_multi_marker_closing_block_counts(self):
        block = "\n".join([build("disposition", OTHER), build("disposition", THIRD)])
        comments = [
            _comment(1, build("claim", OTHER)),
            _comment(2, build("claim", THIRD)),
            _comment(3, block + "\ntext"),
            _own(),
        ]
        assert _winner(comments, {OTHER: "running", THIRD: "running"}) is None


# ---------------------------------------------------------------------------
# TC-188-06: a forged earlier claim can't block the agent (D-53)
# ---------------------------------------------------------------------------


class TestForgedClaims:
    @pytest.mark.parametrize(
        "forged",
        [{"app_id": None, "user_type": "User"}, {"app_id": 7}, {"user_type": "User"}],
        ids=["human", "other-app", "user-type"],
    )
    def test_an_untrusted_earlier_claim_is_ignored(self, forged):
        comments = [_comment(OWN_CID - 5, build("claim", OTHER), **forged), _own()]
        reader = Statuses({OTHER: "running"})
        assert _winner(comments, reader) is None
        assert reader.asked == []

    def test_a_forged_closer_does_not_close_an_active_earlier_claim(self):
        comments = [
            _comment(OWN_CID - 5, build("claim", OTHER)),
            _comment(OWN_CID - 4, build("disposition", OTHER), app_id=None, user_type="User"),
            _comment(OWN_CID - 3, build("refusal", OTHER, "closed"), app_id=7),
            _own(),
        ]
        assert _winner(comments, {OTHER: "running"}) == OTHER

    def test_a_marker_quoted_below_the_leading_block_is_not_a_claim(self):
        body = "a human quoting:\n" + build("claim", OTHER)
        comments = [_comment(OWN_CID - 5, body), _own()]
        assert _winner(comments, {OTHER: "running"}) is None


# ---------------------------------------------------------------------------
# TC-188-07: the comment id decides, including the same second
# ---------------------------------------------------------------------------


class TestOrdering:
    def test_a_later_active_claim_means_this_run_won(self):
        comments = [_own(), _comment(OWN_CID + 1, build("claim", OTHER))]
        reader = Statuses({OTHER: "running"})
        assert _winner(comments, reader) is None
        assert reader.asked == []

    def test_same_second_comments_are_ordered_by_id_not_list_order(self):
        # Two claims created in the same second: GitHub's timestamps tie, so
        # only the integer id orders them. The list order is irrelevant.
        stamp = "2026-10-24T12:00:00Z"
        mine = _own() | {"created_at": stamp}
        theirs = _comment(OWN_CID + 1, build("claim", OTHER)) | {"created_at": stamp}
        assert _winner([theirs, mine], {OTHER: "running"}) is None
        # And from the other run's side, this run's claim (lower id) wins.
        other_view = race_winner(
            [theirs, mine], APP_ID, OTHER, OWN_CID + 1, Statuses({RUN: "running"})
        )
        assert other_view == RUN

    def test_ids_above_2_31_compare_numerically(self):
        big = 2**33
        comments = [
            _comment(big + 9, build("claim", RUN)),
            _comment(big + 10, build("claim", OTHER)),
        ]
        assert _winner(comments, {OTHER: "running"}, own_cid=big + 9) is None
        assert _winner(comments, {OTHER: "running"}, own_cid=big + 11) == OTHER

    def test_only_claims_before_this_one_are_read(self):
        comments = [
            _comment(OWN_CID - 1, build("claim", OTHER)),
            _own(),
            _comment(OWN_CID + 1, build("claim", THIRD)),
        ]
        reader = Statuses({OTHER: "succeeded", THIRD: "running"})
        assert _winner(comments, reader) is None
        assert reader.asked == [[OTHER]]

    @pytest.mark.parametrize("own_cid", [0, -1, None, True, "5"])
    def test_an_invalid_own_comment_id_is_refused(self, own_cid):
        with pytest.raises(ValueError):
            _winner([_own()], {}, own_cid=own_cid)


# ---------------------------------------------------------------------------
# CT-34: missing rows and unknown statuses
# ---------------------------------------------------------------------------


class TestStatusFaults:
    def test_a_missing_row_counts_as_finished_with_a_warning(self):
        warnings: list[str] = []
        comments = [_comment(OWN_CID - 5, build("claim", OTHER)), _own()]
        assert _winner(comments, {}, warnings=warnings) is None
        assert len(warnings) == 1 and OTHER in warnings[0]

    def test_an_unknown_status_fails_closed_with_a_warning(self):
        warnings: list[str] = []
        comments = [_comment(OWN_CID - 5, build("claim", OTHER)), _own()]
        with pytest.raises(SupabaseUnavailable):
            _winner(comments, {OTHER: "paused"}, warnings=warnings)
        assert len(warnings) == 1

    def test_an_unknown_status_fails_closed_next_to_an_active_claim(self):
        comments = [
            _comment(1, build("claim", OTHER)),
            _comment(2, build("claim", THIRD)),
            _own(),
        ]
        with pytest.raises(SupabaseUnavailable):
            _winner(comments, {OTHER: "running", THIRD: "weird"})

    def test_a_reader_failure_propagates(self):
        def boom(_ids):
            raise SupabaseUnavailable("v_runs read returned 503")

        comments = [_comment(OWN_CID - 5, build("claim", OTHER)), _own()]
        with pytest.raises(SupabaseUnavailable):
            _winner(comments, boom)
