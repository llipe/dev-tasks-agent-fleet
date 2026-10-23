"""
Wave A cross-story joins (PRD-level qa-engineer gate, Layer 2).

Each story's own gate tested its module. These tests drive the real
``main.invoke`` (``tests/helpers/pipeline_run.py``) across the joins no single
story owned:

context readers -> budget -> prompt -> adapter -> validate -> render -> pipeline

1. Every Converse request is at most B (``max_context_tokens``), recounted here
   independently of ``bedrock_adapter.request_tokens``, on the worst 5-call
   sequence and on a repair after a huge invalid output.
2. The ``ContextData`` of the accepted call (a context-length retry or a repair
   rebuild, both without full files) is the one validate, render, the artifact
   and the metrics see; not the first build's.
3. ``escape_path``: the form the model saw in the prompt is the form validate
   matches and the form the comment shows.
4. One comment per run and ``comment_size`` <= 60,000 with a hostile review on
   the pipeline, not only in ``render`` alone.
5. No secret anywhere, including model text that only becomes the secret after
   the renderer removes invisible characters.

Real defects are pinned with ``pytest.mark.xfail(strict=True)`` and a
reproducer in the docstring: a fix turns the XPASS red, and the marker is
removed with the fix.
"""

from __future__ import annotations

import json
import math
import unicodedata
from typing import Any

import pytest

from pipeline import context_tokens
from render import MAX_COMMENT_CHARS, comment_size
from tests.fixtures.bedrock import (
    context_length_rejected,
    reasoning_rejected,
    text_response,
    tool_choice_rejected,
    tool_use_response,
)
from tests.helpers.pipeline_run import (
    HEAD,
    SUPABASE_KEY,
    TOKEN,
    V1_CONFIRMED,
    Harness,
    blocking,
    file_entry,
    marker,
    review,
    suggestion,
)

B_MIN = 20_000  # the schema minimum for max_context_tokens


@pytest.fixture
def h(monkeypatch) -> Harness:
    return Harness(monkeypatch)


def _independent_tokens(request: dict[str, Any]) -> int:
    """``ceil(len / 3.5)`` over every model-input string of a request, recounted here.

    Not ``request_tokens``: this walks every string under ``system`` and
    ``messages`` (any key, not just ``text``) and charges ``toolConfig`` as
    its JSON, so a block the adapter forgot to count is still charged.
    """

    def strings(value: Any) -> list[str]:
        if isinstance(value, str):
            return [value]
        if isinstance(value, dict):
            return [s for v in value.values() for s in strings(v)]
        if isinstance(value, list | tuple):
            return [s for v in value for s in strings(v)]
        return []

    total = 0
    for key in ("system", "messages"):
        for s in strings(request.get(key, [])):
            if s in ("user", "assistant"):  # role names, not model text
                continue
            total += math.ceil(len(s) * 2 / 7)
    if "toolConfig" in request:
        total += math.ceil(len(json.dumps(request["toolConfig"])) * 2 / 7)
    return total


def _big_module(chars: int) -> str:
    line = "value = compute(alpha, beta, gamma)  # filler line for the budget\n"
    return line * (chars // len(line))


def _with_big_file(h: Harness, chars: int) -> None:
    """Add a reviewed file whose diff pushes the first prompt toward B."""
    h.set_files(
        [
            file_entry("src/app.py", additions=3, deletions=1),
            file_entry("src/big.py", additions=chars // 66, deletions=0, status="added"),
        ]
    )
    h.set_content("src/big.py", HEAD, _big_module(chars))


def _fallback_json(findings: list[dict[str, Any]], checks: list[dict[str, Any]]) -> str:
    return json.dumps({"findings": findings, "verifier_checks": checks})


def _only_post(h: Harness) -> str:
    posts = h.posts()
    assert len(posts) == 1, f"one comment per run, got {len(posts)}"
    return posts[0]


def _artifact(h: Harness) -> dict[str, Any]:
    artifacts = h.reporter.artifacts()
    assert len(artifacts) == 1
    return artifacts[0]["metadata"] if "metadata" in artifacts[0] else artifacts[0]


# ---------------------------------------------------------------------------
# 1-2. Every call <= B; the accepted call's ContextData flows downstream
# ---------------------------------------------------------------------------


def test_worst_five_call_sequence_fits_b_and_the_repair_context_flows_downstream(h):
    """Forced -> reasoning retry -> fallback -> context-length retry -> repair (spec §6.3).

    Every request is recounted <= B. The repair rebuild has no full files, so
    the run's metrics, artifact and comment must describe that build, and
    validate must read the repair build's candidates (V1 confirmed -> blocking).
    """
    _with_big_file(h, 40_000)
    h.fake.push(
        reasoning_rejected(),
        tool_choice_rejected(),
        context_length_rejected(),
        text_response("not json at all " * 50),
        text_response(_fallback_json([], [V1_CONFIRMED])),
    )
    result = h.drive({"pr_number": 42, "max_context_tokens": B_MIN})

    assert h.fake.calls == 5
    first = h.prompts[0]
    assert first.context.full_files_included, "the first build must include a full file"
    for i, request in enumerate(h.fake.requests, 1):
        assert _independent_tokens(request) <= B_MIN, f"call {i} is over B"

    accepted = h.prompts[-1]
    assert not accepted.context.full_files_included
    assert result["status"] == "succeeded"
    assert result["verdict"] == "blocking"

    metrics = h.reporter.terminal["metrics"]
    assert metrics["bedrock_calls"] == 5
    assert metrics["repair_calls"] == 1
    assert metrics["context_tokens"] == context_tokens(accepted.context)
    assert metrics["context_tokens"]["full_files"] == 0
    assert metrics["estimated_first_call_tokens"] == first.tokens

    meta = _artifact(h)
    assert meta["context"]["full_files_included"] == 0
    assert meta["verifier"][0]["status"] == "confirmed"

    body = _only_post(h)
    assert marker(body) is not None
    assert comment_size(body) <= MAX_COMMENT_CHARS


def test_a_huge_invalid_output_is_cut_so_the_repair_request_fits_b(h):
    """The repair block carries the previous output, cut to what is left of B (D-47)."""
    _with_big_file(h, 30_000)
    huge = "x" * 900_000
    h.fake.push(
        tool_use_response({"findings": huge, "verifier_checks": []}),
        review([blocking()]),
    )
    result = h.drive({"pr_number": 42, "max_context_tokens": B_MIN})

    assert h.fake.calls == 2
    for i, request in enumerate(h.fake.requests, 1):
        assert _independent_tokens(request) <= B_MIN, f"call {i} is over B"
    assert result["verdict"] == "blocking"
    _only_post(h)


def test_a_context_length_retry_context_is_what_validate_and_render_see(h):
    """R4 retry: no full files in the accepted build; the comment and metrics agree."""
    h.fake.push(context_length_rejected(), review([blocking()]))
    result = h.drive()

    assert h.fake.calls == 2
    assert h.prompts[0].context.full_files_included
    accepted = h.prompts[-1]
    assert not accepted.context.full_files_included
    assert h.reporter.terminal["metrics"]["context_tokens"] == context_tokens(accepted.context)
    meta = _artifact(h)
    assert meta["context"]["full_files_included"] == 0
    assert meta["context"]["full_files_dropped"] == len(accepted.context.full_files_dropped)
    assert result["verdict"] == "blocking"
    _only_post(h)


# ---------------------------------------------------------------------------
# 3. escape_path: prompt form == validate's match form == the comment's form
# ---------------------------------------------------------------------------

_ODD = "src/we\u2028ird\tname.py"  # a line separator and a tab; GitHub allows both
_ODD_ESCAPED = "src/we\\u2028ird\\tname.py"


def _odd_file(h: Harness) -> None:
    h.set_files([file_entry(_ODD, additions=2, deletions=0, status="added")])
    h.set_content(_ODD, HEAD, "first = 1\nsecond = 2\n")


@pytest.mark.parametrize("cited", [_ODD_ESCAPED, _ODD, f"`./{_ODD_ESCAPED}`"])
def test_the_escaped_path_the_model_saw_matches_and_renders_the_same(h, cited):
    _odd_file(h)
    h.fake.push(review([blocking(file=cited, line_start=1, line_end=1)]))
    result = h.drive()

    prompt_text = "".join(b["text"] for m in h.prompts[0].messages() for b in m["content"])
    assert _ODD_ESCAPED in prompt_text, "the prompt shows the escaped path"
    assert _ODD not in prompt_text, "no raw line separator in the prompt"
    assert result["verdict"] == "blocking", "the cited form matched the reviewed path"

    body = _only_post(h)
    assert f"`{_ODD_ESCAPED}:1`" in body, "the comment shows the form the model saw"
    assert "\u2028" not in body and "\t" not in body
    meta = _artifact(h)
    assert meta["findings"][0]["file"] == _ODD, "the artifact keeps the canonical raw path"


# ---------------------------------------------------------------------------
# 3b. OverBudget on both paths: check_size (lines) and build_prompt (tokens)
# ---------------------------------------------------------------------------


def _over_budget_run(h: Harness, path: str) -> tuple[dict[str, Any], str, dict[str, Any]]:
    if path == "lines":
        h.set_files(
            [file_entry("src/app.py", additions=150, deletions=0), file_entry("uv.lock", 9, 9)]
        )
        params = {"pr_number": 42, "max_diff_lines": 100}
    else:
        big = "".join(f"value_{i} = {i}  # {'x' * 40}\n" for i in range(2_500))
        h.set_files(
            [file_entry("src/app.py", additions=3, deletions=1), file_entry("uv.lock", 9, 9)]
        )
        h.set_content("src/app.py", HEAD, big)
        params = {"pr_number": 42, "max_context_tokens": B_MIN}
    result = h.drive(params)
    return result, _only_post(h), h.reporter.terminal["metrics"]


@pytest.mark.parametrize("path", ["lines", "tokens"])
def test_both_over_budget_paths_end_alike_and_agree_with_the_metrics(h, path):
    """Same terminal state, no Converse, no artifact; the comment's counts are the run's."""
    result, body, metrics = _over_budget_run(h, path)

    assert (result["status"], result["outcome"]) == ("succeeded", "not_applicable")
    assert result["error_code"] is None and result["verdict"] is None
    assert h.fake.calls == 0 and h.prompts == []
    assert h.reporter.artifacts() == []
    assert metrics["bedrock_calls"] == 0
    assert metrics["comment_chars"] == comment_size(body)
    assert metrics["comment_truncated"] is False
    lines = metrics["changed_lines"]
    assert f"changes {lines} line" in body, "the comment counts what the run counted"
    assert "`uv.lock` (lockfile)" in body, "name-only files are listed on both paths"
    assert body.endswith("\n") and marker(body) is None


# ---------------------------------------------------------------------------
# 4. One comment, <= 60,000 by comment_size, on a hostile review
# ---------------------------------------------------------------------------


def test_a_hostile_review_is_one_comment_within_60k_utf16_units(h):
    """The largest schema-valid review (40 findings at every maxLength), all astral.

    About 104k code points, over 200k UTF-16 units before neutralization: the
    staged truncation must bring the posted body to <= 60,000 ``comment_size``.
    """
    from findings_schema import MAX_FINDINGS

    astral = "\U0001f600"  # one code point, 2 UTF-16 units

    def text(n: int, tail: str = "") -> str:
        return astral * (n - len(tail)) + tail

    def full(make: Any, i: int) -> dict[str, Any]:
        return make(
            title=text(200),
            failure_scenario=text(1500, "@x #1 <!-- --> </details>"),
            consequence=text(500, "[l](http://e)"),
            rank=i + 1,  # the schema minimum is 1
        )

    findings = [full(blocking, i) for i in range(30)]
    findings += [full(suggestion, i) for i in range(MAX_FINDINGS - 30)]
    h.fake.push(review(findings))
    h.drive({"pr_number": 42, "max_suggestions": 20})

    body = _only_post(h)
    assert comment_size(body) <= MAX_COMMENT_CHARS
    assert body.count("<!--") == 1
    metrics = h.reporter.terminal["metrics"]
    assert metrics["comment_truncated"] is True
    assert metrics["comment_chars"] == comment_size(body)


# ---------------------------------------------------------------------------
# 5. No secret anywhere, in any form the outputs can reassemble
# ---------------------------------------------------------------------------

_INVISIBLE = "\u200b"


def _visible(text: str) -> str:
    """``text`` without format characters (Cf), as a reader or a copy-paste sees it."""
    return "".join(c for c in text if unicodedata.category(c) != "Cf")


def _split(secret: str) -> str:
    return _INVISIBLE.join(secret)


def _drive_split_secret_review(h: Harness) -> str:
    h.fake.push(
        review(
            [
                blocking(
                    title=f"uses {_split(TOKEN)}",
                    failure_scenario=f"leaks {_split(SUPABASE_KEY)}",
                )
            ]
        )
    )
    h.drive()
    return _only_post(h)


def test_a_secret_split_by_invisible_characters_never_reaches_the_comment(h):
    """``neutralize`` removes U+200B, so the post-render scrub must catch the joined form."""
    body = _drive_split_secret_review(h)
    flat = _visible(body).replace("\\", "")
    for secret in (TOKEN, SUPABASE_KEY):
        assert secret.replace("\\", "") not in flat


@pytest.mark.xfail(
    strict=True,
    reason="QA-PRD-01: comment_chars is measured before the post-render scrub, not on the "
    "posted body (spec §5.3: comment_size of the posted body)",
)
def test_comment_chars_is_the_size_of_the_posted_body_after_the_scrub(h):
    """Reproducer: a model title ``"uses " + "\\u200b".join(TOKEN)``.

    The raw scrub misses it, ``neutralize`` drops the U+200B so the rendered
    body holds ``neutralize(TOKEN)``, ``_scrub_body`` replaces that with
    ``***``, and ``Pipeline._post_review`` still records ``rendered.chars``
    (the pre-scrub size). The note path measures after the scrub.
    """
    body = _drive_split_secret_review(h)
    assert h.reporter.terminal["metrics"]["comment_chars"] == comment_size(body)


@pytest.mark.xfail(
    strict=True,
    reason="QA-PRD-02: the audit_report artifact (run_artifacts) keeps a secret split by "
    "invisible characters; only the comment gets the post-render scrub",
)
def test_a_split_secret_never_reaches_any_reporter_write(h):
    """Reproducer: the same model title. ``scrub_value`` matches the raw secret only,
    so ``findings[0].title`` in ``audit_report`` holds every character of the
    token, separated by U+200B, and the panel shows it as the token."""
    _drive_split_secret_review(h)
    # The dump is ASCII JSON (``\\u200b`` escapes); decode it, then drop format characters.
    flat = _visible(h.reporter.dump().encode().decode("unicode_escape"))
    for secret in (TOKEN, SUPABASE_KEY):
        assert secret not in flat
