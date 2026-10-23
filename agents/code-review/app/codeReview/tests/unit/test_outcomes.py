"""
S-213 AC5/AC7 — outcome mapping and the spec §13 error table (TC-213-09, TC-213-14).

Pure functions of ``pipeline``: verdict -> outcome (PRD FR-29), exception ->
``error_code`` (mapped on ``exc.code``, never on the class, and always one of
``render.ERROR_CODES`` so the run and the failure comment agree), and the
comment-or-not column of the §13 table, including D-36's ``COMMENT_POST_FAILED``
rule keyed on the exception type (S-205 D4, pinned here).
"""

from __future__ import annotations

import enum

import pytest

from bedrock_adapter import (
    BedrockAccessDenied,
    BedrockError,
    BedrockTimeout,
    CallBudgetExceeded,
    ModelOutputInvalid,
)
from budget import BudgetInvariantError
from credentials import CredentialError
from findings_schema import SchemaViolation
from github_client import (
    ForbiddenCall,
    GitHubApiError,
    GitHubNotFound,
    GitHubPermissionDenied,
)
from pipeline import (
    FAILURE_COMMENT,
    OUTCOME_NEEDS_REVIEW,
    OUTCOME_NO_FINDINGS,
    OUTCOME_NOT_APPLICABLE,
    STEPS,
    CommentPostFailed,
    RunTimeout,
    error_code_for,
    outcome_for_verdict,
    wants_failure_comment,
)
from prompt import NonceError, PromptError
from render import ERROR_CODES, canonical_code, render_failure
from tests.helpers.prng import tactic_seed

# ---------------------------------------------------------------------------
# Steps and outcomes (TC-213-09)
# ---------------------------------------------------------------------------


def test_steps_are_the_spec_8_1_keys_in_order():
    assert STEPS == ("load_pr", "context", "review", "validate", "post")


@pytest.mark.parametrize(
    ("verdict", "outcome"),
    [("clear", OUTCOME_NO_FINDINGS), ("blocking", OUTCOME_NEEDS_REVIEW)],
)
def test_verdict_maps_to_outcome(verdict, outcome):
    assert outcome_for_verdict(verdict) == outcome


def test_outcome_vocabulary_is_the_run_outcome_enum_subset():
    assert (OUTCOME_NO_FINDINGS, OUTCOME_NEEDS_REVIEW, OUTCOME_NOT_APPLICABLE) == (
        "no_findings",
        "needs_review",
        "not_applicable",
    )


@pytest.mark.parametrize("verdict", ["", "CLEAR", "blocked", None, 1])
def test_unknown_verdict_is_rejected(verdict):
    with pytest.raises(ValueError):
        outcome_for_verdict(verdict)


# ---------------------------------------------------------------------------
# Exception -> error_code (TC-213-14, carry-forwards S-205 D2, S-210 (4), S-211 (2))
# ---------------------------------------------------------------------------


CASES = [
    (GitHubApiError("GET x failed (HTTP 500)", status=500), "context", "GITHUB_API_ERROR"),
    (GitHubPermissionDenied("denied", status=403), "context", "GITHUB_PERMISSION_DENIED"),
    (GitHubPermissionDenied("denied", status=401), "load_pr", "GITHUB_PERMISSION_DENIED"),
    # A 404 after load_pr (compare, files) is an API failure, never GITHUB_NOT_FOUND.
    (GitHubNotFound("gone", status=404), "context", "GITHUB_API_ERROR"),
    (CredentialError("GITHUB_PERMISSION_DENIED", "x"), "load_pr", "GITHUB_PERMISSION_DENIED"),
    (CredentialError("GITHUB_API_ERROR", "x"), "load_pr", "GITHUB_API_ERROR"),
    (CredentialError("GITHUB_UNREACHABLE", "x"), "load_pr", "GITHUB_API_ERROR"),
    (CredentialError("NO_INSTALLATION", "x"), "load_pr", "INTERNAL_ERROR"),
    (CredentialError("PEM_UNAVAILABLE", "x"), "load_pr", "INTERNAL_ERROR"),
    (CredentialError("SUPABASE_UNREACHABLE", "x"), "load_pr", "INTERNAL_ERROR"),
    (BedrockAccessDenied("denied"), "review", "BEDROCK_ACCESS_DENIED"),
    (BedrockError("throttled"), "review", "BEDROCK_ERROR"),
    (BedrockTimeout("late", run_timeout=True), "review", "RUN_TIMEOUT"),
    (BedrockTimeout("read timeout", run_timeout=False), "review", "BEDROCK_ERROR"),
    (ModelOutputInvalid("bad"), "review", "MODEL_OUTPUT_INVALID"),
    (CallBudgetExceeded("sixth"), "review", "INTERNAL_ERROR"),
    (BudgetInvariantError(10, 5), "context", "INTERNAL_ERROR"),
    (BudgetInvariantError(10, 5), "review", "INTERNAL_ERROR"),
    (PromptError("defect"), "context", "INTERNAL_ERROR"),
    (NonceError("collision"), "review", "INTERNAL_ERROR"),
    (ForbiddenCall("guard"), "context", "INTERNAL_ERROR"),
    (SchemaViolation("$", "type", "wrong"), "validate", "INTERNAL_ERROR"),
    (ValueError("bad"), "validate", "INTERNAL_ERROR"),
    (RunTimeout("deadline"), "context", "RUN_TIMEOUT"),
    (RunTimeout("deadline"), "validate", "RUN_TIMEOUT"),
    (CommentPostFailed(GitHubApiError("x", status=500)), "post", "COMMENT_POST_FAILED"),
    (CommentPostFailed(GitHubPermissionDenied("x", status=403)), "post", "COMMENT_POST_FAILED"),
    (KeyError("x"), "post", "INTERNAL_ERROR"),
    (RuntimeError("x"), None, "INTERNAL_ERROR"),
]


@pytest.mark.parametrize(("exc", "step", "code"), CASES, ids=lambda v: type(v).__name__)
def test_error_code_is_mapped_on_the_code_attribute(exc, step, code):
    assert error_code_for(exc, step=step) == code


def test_validate_step_errors_are_internal_even_with_a_code():
    """S-211 (2): anything ``validate_result`` raises is a wrapper defect."""
    assert error_code_for(BedrockError("odd"), step="validate") == "INTERNAL_ERROR"
    assert error_code_for(GitHubApiError("odd"), step="validate") == "INTERNAL_ERROR"


def test_mapping_ignores_the_class_and_reads_the_code():
    """A ``BedrockError`` whose code is ``RUN_TIMEOUT`` is a timeout (S-210 (4))."""

    class Odd(Exception):
        code = "BEDROCK_ACCESS_DENIED"

    err = BedrockError("x")
    err.code = "RUN_TIMEOUT"  # type: ignore[misc]
    assert error_code_for(err, step="review") == "RUN_TIMEOUT"
    assert error_code_for(Odd(), step="review") == "BEDROCK_ACCESS_DENIED"


class _Code(enum.StrEnum):
    BAD = "BEDROCK_ERROR"


@pytest.mark.parametrize(
    "code",
    [
        None,
        7,
        b"BEDROCK_ERROR",
        "bedrock_error",
        "SIGNAL_TERMINATION",
        "GITHUB_NOT_FOUND",
        _Code.BAD,
    ],
    ids=repr,
)
def test_unknown_or_odd_codes_are_canonical(code):
    class E(Exception):
        pass

    exc = E()
    exc.code = code  # type: ignore[attr-defined]
    got = error_code_for(exc, step="review")
    assert got in ERROR_CODES
    assert got == canonical_code(code) or code == "GITHUB_NOT_FOUND"


def test_error_code_is_always_a_spec_13_code_property():
    """RT (seed 415001): random exception shapes always map into ``ERROR_CODES``."""
    import random

    rng = random.Random(tactic_seed(415, 1))
    pool = [*ERROR_CODES, "GITHUB_NOT_FOUND", "GITHUB_UNREACHABLE", "X", "", "RUN_TIMEOUT "]
    for _ in range(2_000):

        class E(Exception):
            pass

        exc = E()
        if rng.random() < 0.8:
            exc.code = rng.choice(pool)  # type: ignore[attr-defined]
        step = rng.choice([*STEPS, None])
        got = error_code_for(exc, step=step)
        assert got in ERROR_CODES
        if step == "validate":
            assert got == "INTERNAL_ERROR"
        elif getattr(exc, "code", None) in ERROR_CODES:
            assert got == exc.code  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Comment or not (spec §13; D-13, D-36; TC-213-14)
# ---------------------------------------------------------------------------


def test_failure_comment_table_matches_spec_13():
    assert FAILURE_COMMENT == {
        "INVALID_PARAMS": "no",
        "GITHUB_PERMISSION_DENIED": "attempted",
        "GITHUB_API_ERROR": "attempted",
        "BEDROCK_ACCESS_DENIED": "yes",
        "BEDROCK_ERROR": "yes",
        "MODEL_OUTPUT_INVALID": "yes",
        "RUN_TIMEOUT": "yes",
        "COMMENT_POST_FAILED": "once_unless_denied",
        "INTERNAL_ERROR": "yes",
    }
    assert set(FAILURE_COMMENT) == set(ERROR_CODES)


@pytest.mark.parametrize("code", [c for c in ERROR_CODES if c not in {"INVALID_PARAMS"}])
def test_failure_comment_is_wanted_for_every_code_but_invalid_params(code):
    cause = GitHubApiError("x", status=500) if code == "COMMENT_POST_FAILED" else None
    exc = CommentPostFailed(cause) if cause is not None else RuntimeError("x")
    assert wants_failure_comment(code, exc) is True


def test_invalid_params_never_comments():
    """§13: the PR is unknown or unvalidated."""
    assert wants_failure_comment("INVALID_PARAMS", None) is False


@pytest.mark.parametrize("status", [401, 403])
def test_comment_post_failed_with_permission_denied_does_not_comment(status):
    exc = CommentPostFailed(GitHubPermissionDenied("denied", status=status))
    assert wants_failure_comment("COMMENT_POST_FAILED", exc) is False


@pytest.mark.parametrize(
    "cause",
    [
        GitHubApiError("rate limited (HTTP 403)", status=403),  # secondary rate limit: pinned
        GitHubApiError("rate limited (HTTP 429)", status=429),
        GitHubApiError("failed (HTTP 500)", status=500),
        GitHubApiError("ConnectionError after 1 attempt(s)"),
        GitHubApiError("failed (HTTP 422)", status=422),
        GitHubApiError("malformed response: body is not JSON"),
    ],
    ids=lambda e: str(e),
)
def test_comment_post_failed_otherwise_comments_once(cause):
    """S-205 D4: keyed on the exception type, so a rate-limited 403 still comments."""
    assert wants_failure_comment("COMMENT_POST_FAILED", CommentPostFailed(cause)) is True


def test_comment_post_failed_keeps_its_cause():
    cause = GitHubPermissionDenied("denied", status=403)
    exc = CommentPostFailed(cause)
    assert exc.cause is cause
    assert exc.code == "COMMENT_POST_FAILED"
    assert "403" in str(exc)


def test_failure_comment_text_is_the_render_failure_line():
    for code in ERROR_CODES:
        body = render_failure(
            code, run_id="3f2b8c1e-5d4a-4f6b-9a7c-2e1d0b9a8c7f", panel_base_url="https://p.example"
        )
        assert body.startswith(f"Code review failed (`{code}`). [run](https://p.example/runs/")
        assert body.endswith("\n") and body.count("\n") == 1
