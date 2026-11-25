"""
S-216 (#480) — the review call on Claude Sonnet 5.5 through the Anthropic API.

TC-216-01..45, 51..53 and CT-13 against ``tests/fixtures/anthropic_fake.py``
(no network). AC mapping (test plan §14.2): AC1 ``test_request_shape_*`` and
``test_parse_*``; AC2 ``test_sent_schema_*`` and ``test_repair_*``; AC3
``test_count_*``; AC4 ``test_context_length_*``; AC5 ``test_errors_*``,
``test_refusal_*`` and ``test_client_*``; AC6 ``test_answered_by_*``; AC7
``test_call_budget_*``; AC8 ``test_usage_*``; AC10 ``test_result_shape_*``.
The real SDK's behavior (retries, headers, SSE) is CT-15 in
``test_model_adapter_sdk.py``; hostile inputs are ``test_model_adapter_hostile.py``.
"""

from __future__ import annotations

import ast
import copy
import dataclasses
import json
import re
from pathlib import Path
from typing import Any

import pytest

import model_adapter
from budget import BudgetInvariantError
from findings_schema import SUBMIT_REVIEW_SCHEMA, sent_schema
from model_adapter import (
    FALLBACK_BETA,
    MAX_CALLS,
    MAX_TOKENS,
    OUTPUT_STRUCTURED,
    PRICE_TABLE,
    REPAIR_KIND,
    WARN_CONTEXT_AFTER_RETRY,
    WARN_CONTEXT_NO_FILES,
    WARN_CONTEXT_REPAIR,
    WARN_CONTEXT_RETRY,
    WARN_COUNT_FAILED,
    WARN_NO_PRICE,
    WARN_REPAIR,
    WARN_REPAIR_NO_ROOM,
    CallBudgetExceeded,
    CallMetrics,
    ModelAccessDenied,
    ModelAdapterError,
    ModelApiError,
    ModelOutputInvalid,
    ModelRateLimited,
    ModelRefused,
    ModelTimeout,
    ReviewResult,
    call_timeouts,
    request_tokens,
)
from prompt import LABEL_FILE
from tests.fixtures.anthropic_fake import (
    MODEL,
    FakeAnthropic,
    MidStream,
    api_status_error,
    auth_error,
    bad_request,
    connection_error,
    finding,
    loose_message,
    message,
    overloaded,
    permission_denied,
    prompt_too_long,
    rate_limited,
    review_message,
    server_error,
    timeout_error,
    valid_review,
)
from tests.helpers.model_run import (
    BUDGET,
    Clock,
    Recorder,
    first_prompt,
    review_inputs,
    run,
)
from tests.helpers.prompt_inputs import parse_blocks

PKG = Path(__file__).resolve().parents[2]
SENTINEL = "SENTINEL-DO-NOT-LOG"
STREAM_KEYS = {"model", "max_tokens", "system", "messages", "output_config", "betas", "fallbacks"}
COUNT_KEYS = {"model", "system", "messages", "output_config"}


def _ok() -> Any:
    return review_message(valid_review())


def _output_config(effort: str = "high") -> dict[str, Any]:
    return {
        "effort": effort,
        "format": {"type": "json_schema", "schema": sent_schema(SUBMIT_REVIEW_SCHEMA)},
    }


def _repair_parts(req: dict[str, Any]) -> tuple[str, str]:
    content = req["messages"][0]["content"]
    assert len(req["messages"]) == 1 and req["messages"][0]["role"] == "user"
    assert len(content) == 2
    assert all(b["type"] == "text" for b in content)
    return content[0]["text"], content[1]["text"]


def _walk(value: Any):
    if isinstance(value, dict):
        for k, v in value.items():
            yield k
            yield from _walk(v)
    elif isinstance(value, list):
        for v in value:
            yield from _walk(v)


# ---------------------------------------------------------------------------
# AC1 request shape (TC-216-01..04, CT-13)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("effort", ["low", "medium", "high"])
def test_request_shape_first_call(effort):
    ins = review_inputs()
    p = first_prompt(ins)
    fake = FakeAnthropic([_ok()])
    run(fake, ins, prompt=p, effort=effort)
    (req,) = fake.stream_requests
    assert req["model"] == MODEL == "claude-sonnet-5-5"
    assert req["max_tokens"] == MAX_TOKENS == 64_000
    assert type(req["max_tokens"]) is int
    assert req["system"] == p.system
    assert req["messages"] == [{"role": "user", "content": [{"type": "text", "text": p.user}]}]
    assert req["output_config"] == _output_config(effort)
    assert req["betas"] == ["server-side-fallback-2026-07-01"] == [FALLBACK_BETA]
    assert req["fallbacks"] == "default"


def test_request_shape_exact_key_set_and_no_tools_thinking_or_cache():
    fake = FakeAnthropic([prompt_too_long(), review_message({"findings": "bad"}), _ok()])
    run(fake)
    assert fake.calls == 3
    for req in fake.stream_requests:
        assert set(req) == STREAM_KEYS
        keys = set(_walk(req))
        for forbidden in (
            "tools",
            "tool_choice",
            "thinking",
            "toolConfig",
            "additionalModelRequestFields",
            "metadata",
            "stop_sequences",
            "cache_control",
        ):
            assert forbidden not in keys


def test_request_shape_retry_and_repair_keep_the_options():
    """TC-216-03: only ``system``/``messages`` differ; one user turn, no assistant turn."""
    fake = FakeAnthropic([prompt_too_long(), review_message({"findings": "bad"}), _ok()])
    run(fake)
    first = fake.stream_requests[0]
    for req in fake.stream_requests[1:]:
        for key in ("model", "max_tokens", "output_config", "betas", "fallbacks"):
            assert req[key] == first[key]
    for req in fake.stream_requests:
        assert len(req["messages"]) == 1
        assert req["messages"][0]["role"] == "user"
        assert all(b["type"] == "text" for b in req["messages"][0]["content"])


def _adapter_source() -> str:
    return (PKG / "model_adapter.py").read_text()


def _code_without_docstrings(source: str) -> str:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if (
            isinstance(body, list)
            and body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            body[0] = ast.Pass()
    return ast.unparse(tree)


# The selection call keeps its Bedrock forced-tool request until S-217 (#481)
# moves it to the Anthropic client; these files are that residual.
SELECTION_RESIDUAL = {"context/selection.py", "legacy_bedrock.py"}


def test_request_shape_static_scan_of_the_package_is_tool_free():
    """TC-216-04: no tool fields anywhere in model code; the stream is a context manager."""
    offenders = []
    for path in PKG.rglob("*.py"):
        rel = path.relative_to(PKG)
        if rel.parts[0] in {"tests", ".venv"} or rel.as_posix() in SELECTION_RESIDUAL:
            continue
        code = _code_without_docstrings(path.read_text())
        for needle in ("tool_choice", "thinking=", "toolResult", "messages.create("):
            if needle in code:
                offenders.append((str(rel), needle))
        if '"tools"' in code or "'tools'" in code:
            offenders.append((str(rel), "tools"))
    assert offenders == []
    source = _adapter_source()
    assert "with client.beta.messages.stream(" in source
    assert ".get_final_message()" in source


def test_request_shape_stream_is_exited_on_success_and_every_error_path():
    fake = FakeAnthropic([_ok()])
    run(fake)
    assert fake.exits == [None]
    fake = FakeAnthropic([MidStream(server_error())])
    with pytest.raises(ModelApiError):
        run(fake)
    assert fake.exits == [type(server_error())]
    fake = FakeAnthropic([rate_limited()])
    with pytest.raises(ModelRateLimited):
        run(fake)
    assert fake.exits[0] is not None and fake.exits[0] != "open"


# ---------------------------------------------------------------------------
# AC1 blocks and stop reasons (TC-216-05..07)
# ---------------------------------------------------------------------------


def test_parse_thinking_block_is_ignored_and_the_text_parsed():
    blocks = [
        {"type": "thinking", "thinking": SENTINEL, "signature": "sig"},
        {"type": "text", "text": json.dumps(valid_review())},
    ]
    result = run(FakeAnthropic([message(blocks=blocks)]))
    assert result.findings == valid_review() and result.repair_calls == 0


def test_parse_text_blocks_are_concatenated_then_parsed_strictly():
    text = json.dumps(valid_review())
    half = len(text) // 2
    blocks = [
        {"type": "redacted_thinking", "data": "x"},
        {"type": "text", "text": text[:half]},
        {"type": "text", "text": text[half:]},
    ]
    result = run(FakeAnthropic([message(blocks=blocks)]))
    assert result.findings == valid_review()


def test_parse_no_text_block_is_invalid_output():
    blocks = [{"type": "thinking", "thinking": "x", "signature": "s"}]
    fake = FakeAnthropic([message(blocks=blocks), _ok()])
    assert run(fake).repair_calls == 1


def test_parse_other_block_types_are_ignored_never_executed():
    """DF-39: a ``server_tool_use`` or ``tool_use`` block is ignored."""
    blocks = [
        {"type": "server_tool_use", "id": "srvtoolu_1", "name": "web_search", "input": {}},
        {"type": "text", "text": json.dumps(valid_review())},
    ]
    result = run(FakeAnthropic([message(blocks=blocks)]))
    assert result.findings == valid_review()
    only_tool = [{"type": "tool_use", "id": "toolu_1", "name": "submit_review", "input": {}}]
    fake = FakeAnthropic([message(blocks=only_tool), _ok()])
    assert run(fake).repair_calls == 1


def test_parse_end_turn_with_one_json_object_is_accepted():
    result = run(FakeAnthropic([_ok()]))
    assert result.repair_calls == 0 and result.calls == 1


_REVIEW = json.dumps(valid_review())


@pytest.mark.parametrize(
    "first",
    [
        message(_REVIEW[:40], stop_reason="max_tokens"),
        message(_REVIEW, stop_reason="max_tokens"),
        message(""),
        message(_REVIEW + _REVIEW),
        message(f"```json\n{_REVIEW}\n```"),
        message(f"Here is the review: {_REVIEW}"),
        message('{"findings": NaN, "verifier_checks": []}'),
        message(" " * 1_000_001 + _REVIEW),
        message(_REVIEW, stop_reason="stop_sequence"),
        message(_REVIEW, stop_reason="pause_turn"),
        loose_message(_REVIEW, stop_reason="weird_new_reason"),
        loose_message(_REVIEW, stop_reason=None),
    ],
    ids=[
        "max-tokens-truncated",
        "max-tokens-complete",
        "empty-text",
        "two-json-values",
        "code-fence",
        "leading-prose",
        "nan",
        "over-1m-chars",
        "stop-sequence",
        "pause-turn",
        "unknown-stop",
        "no-stop",
    ],
)
def test_parse_each_invalid_reply_gets_exactly_one_repair(first):
    rec = Recorder()
    fake = FakeAnthropic([first, _ok()])
    result = run(fake, recorder=rec)
    assert fake.calls == 2 and result.repair_calls == 1
    assert WARN_REPAIR in rec.messages


def test_parse_output_mode_and_effort_applied_on_every_result():
    result = run(FakeAnthropic([_ok()]))
    assert result.output_mode == OUTPUT_STRUCTURED == "structured_output"
    assert result.reasoning_effort_applied is True
    result = run(FakeAnthropic([message("nope"), _ok()]))
    assert result.output_mode == OUTPUT_STRUCTURED
    assert result.reasoning_effort_applied is True


# ---------------------------------------------------------------------------
# AC2 sent schema (TC-216-08, 09, 13; CT-16 in test_contracts.py)
# ---------------------------------------------------------------------------

SENT_SCHEMA_PINNED = {
    "type": "object",
    "additionalProperties": False,
    "required": ["findings", "verifier_checks"],
    "properties": {
        "findings": {
            "type": "array",
            "maxItems": 40,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "severity",
                    "category",
                    "file",
                    "line_start",
                    "line_end",
                    "title",
                    "failure_scenario",
                    "consequence",
                    "rank",
                ],
                "properties": {
                    "severity": {"enum": ["blocking", "suggestion"]},
                    "category": {"enum": ["correctness", "edge_case", "maintainability", "intent"]},
                    "file": {"type": "string"},
                    "line_start": {"type": "integer"},
                    "line_end": {"type": "integer"},
                    "title": {"type": "string"},
                    "failure_scenario": {"type": "string"},
                    "consequence": {"type": "string"},
                    "rank": {"type": "integer"},
                },
            },
        },
        "verifier_checks": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["candidate_id", "status", "reason"],
                "properties": {
                    "candidate_id": {"type": "string"},
                    "status": {"enum": ["confirmed", "not_reproduced"]},
                    "reason": {"type": "string"},
                },
            },
        },
    },
}


def test_sent_schema_pinned():
    assert sent_schema(SUBMIT_REVIEW_SCHEMA) == SENT_SCHEMA_PINNED


def test_sent_schema_keeps_structure_does_not_mutate_and_is_idempotent():
    before = copy.deepcopy(SUBMIT_REVIEW_SCHEMA)
    out = sent_schema(SUBMIT_REVIEW_SCHEMA)
    assert before == SUBMIT_REVIEW_SCHEMA
    assert out is not SUBMIT_REVIEW_SCHEMA
    out["properties"]["findings"]["items"]["required"].append("x")
    assert before == SUBMIT_REVIEW_SCHEMA
    again = sent_schema(SUBMIT_REVIEW_SCHEMA)
    assert sent_schema(again) == again
    items = again["properties"]["findings"]["items"]
    assert items["additionalProperties"] is False
    assert items["required"] == SUBMIT_REVIEW_SCHEMA["properties"]["findings"]["items"]["required"]
    keys = set(_walk(again))
    assert keys.isdisjoint({"minimum", "maxLength", "pattern"})


def test_sent_schema_request_tokens_count_the_copy_sent():
    """TC-216-13 (D-81): the estimate is over the sent schema, not the full one."""
    from context.tokens import estimate

    p = first_prompt(review_inputs())
    fake = FakeAnthropic([_ok()])
    run(fake, prompt=p)
    (req,) = fake.stream_requests
    expected = (
        estimate(p.system)
        + estimate(p.user)
        + estimate(json.dumps(_output_config(), separators=(",", ":")))
    )
    assert request_tokens(req) == expected
    full = dict(_output_config(), format={"type": "json_schema", "schema": SUBMIT_REVIEW_SCHEMA})
    assert request_tokens(req) < (
        estimate(p.system) + estimate(p.user) + estimate(json.dumps(full, separators=(",", ":")))
    )


def test_sent_schema_request_fits_inside_the_counted_fallback_form():
    """What is sent never exceeds what the budget fill counted (D-47)."""
    from context.tokens import estimate

    p = first_prompt(review_inputs())
    sent = estimate(p.system) + estimate(json.dumps(_output_config(), separators=(",", ":")))
    assert sent <= estimate(p.fallback_system)


# ---------------------------------------------------------------------------
# AC2 repair (TC-216-10..12)
# ---------------------------------------------------------------------------


def _mutate(path: str, value: object):
    def apply(review: dict) -> dict:
        target = review
        keys = path.split(".")
        for k in keys[:-1]:
            target = target[int(k)] if k.isdigit() else target[k]
        target[keys[-1]] = value
        return review

    return apply


def _check(candidate_id: str = "V1", reason: str = "ok") -> dict[str, Any]:
    return {"candidate_id": candidate_id, "status": "confirmed", "reason": reason}


@pytest.mark.parametrize(
    "mutate,rule",
    [
        (_mutate("findings.0.failure_scenario", "s" * 1_600), "maxLength"),
        (_mutate("findings.0.title", "t" * 201), "maxLength"),
        (_mutate("findings.0.file", "f" * 401), "maxLength"),
        (_mutate("findings.0.consequence", "c" * 501), "maxLength"),
        (lambda r: {**r, "verifier_checks": [_check(reason="r" * 301)]}, "maxLength"),
        (lambda r: {**r, "verifier_checks": [_check("V")]}, "pattern"),
        (lambda r: {**r, "verifier_checks": [_check("Vx")]}, "pattern"),
        (lambda r: {**r, "verifier_checks": [_check("v1")]}, "pattern"),
        (_mutate("findings.0.line_start", 0), "minimum"),
        (_mutate("findings.0.line_end", -1), "minimum"),
        (_mutate("findings.0.rank", 0), "minimum"),
    ],
    ids=[
        "scenario-1600",
        "title-201",
        "file-401",
        "consequence-501",
        "reason-301",
        "id-V",
        "id-Vx",
        "id-v1",
        "line-start-0",
        "line-end-minus-1",
        "rank-0",
    ],
)
def test_repair_removed_keyword_violation_gets_one_repair(mutate, rule):
    bad = mutate(valid_review())
    rec = Recorder()
    fake = FakeAnthropic([review_message(bad), _ok()])
    result = run(fake, recorder=rec)
    assert fake.calls == 2 and result.repair_calls == 1
    (rebuilt,) = rec.prompts
    _, repair = _repair_parts(fake.stream_requests[1])
    line = repair.split("\n")[1]
    assert line.startswith("Validation error: ")
    error = line.removeprefix("Validation error: ")
    assert len(error) <= 300 and error.isprintable()
    assert "$" in error
    assert dict(rec.warns)[WARN_REPAIR]["rule"]


def test_repair_previous_output_is_fenced_with_a_fresh_nonce():
    ins = review_inputs()
    p = first_prompt(ins)
    rec = Recorder()
    fake = FakeAnthropic([message("{not json"), _ok()])
    result = run(fake, ins, prompt=p, recorder=rec)
    (rebuilt,) = rec.prompts
    assert rebuilt.context.full_files_included == ()
    assert rebuilt.nonce != p.nonce
    req = fake.stream_requests[1]
    assert req["system"] == rebuilt.system
    user, repair = _repair_parts(req)
    assert user == rebuilt.user
    blocks, _ = parse_blocks(user + repair, rebuilt.nonce)
    kind, tag, content = blocks[-1]
    assert (kind, tag) == (REPAIR_KIND, None)
    assert content == "{not json\n"
    assert "JSON" in repair.rsplit(">>>", 1)[-1]
    assert result.context == rebuilt.context and result.prompt is rebuilt


def test_repair_still_invalid_is_model_output_invalid_after_two_calls():
    fake = FakeAnthropic([message("nope"), message("still nope")])
    with pytest.raises(ModelOutputInvalid) as exc:
        run(fake)
    assert fake.calls == 2
    assert exc.value.code == "MODEL_OUTPUT_INVALID"
    assert exc.value.metrics.repair_calls == 1 and exc.value.metrics.calls == 2


@pytest.mark.parametrize(
    "review",
    [
        {"findings": [], "verifier_checks": []},
        valid_review(40),
        {"findings": [finding(line_start=9, line_end=3)], "verifier_checks": []},
        {"findings": [finding(severity="suggestion", failure_scenario="")], "verifier_checks": []},
    ],
    ids=["empty", "40-findings", "line-end-before-start", "blank-scenario"],
)
def test_repair_not_needed_for_full_schema_edges(review):
    result = run(FakeAnthropic([review_message(review)]))
    assert result.findings == review and result.repair_calls == 0


def test_repair_41_findings_goes_to_repair():
    """``maxItems`` is enforced by the validator whether or not it is sent."""
    fake = FakeAnthropic([review_message(valid_review(41)), _ok()])
    assert run(fake).repair_calls == 1


def test_repair_huge_previous_output_is_cut_to_fit_b():
    rec = Recorder()
    huge = "x" * 400_000 + "\n" + "y" * 10
    fake = FakeAnthropic([message(huge), _ok()])
    run(fake, recorder=rec)
    req = fake.stream_requests[1]
    assert request_tokens(req) <= BUDGET
    _, repair = _repair_parts(req)
    assert "[truncated]" in repair and "y" * 10 not in repair


def test_repair_with_no_room_by_estimate_sends_no_repair(monkeypatch):
    """The repair wrapper alone does not fit what B leaves: no repair call."""
    monkeypatch.setattr(model_adapter, "_REPAIR_FOOTER", "x" * (BUDGET * 4))
    rec = Recorder()
    fake = FakeAnthropic([message("nope")])
    with pytest.raises(ModelOutputInvalid) as exc:
        run(fake, recorder=rec)
    assert fake.calls == 1 and fake.counts_made == 1
    assert exc.value.metrics.repair_calls == 0
    assert WARN_REPAIR_NO_ROOM in rec.messages


def test_count_repair_exact_count_over_b_is_model_output_invalid():
    """TC-216-20, DF-27 pinned: no repair is sent; the code is MODEL_OUTPUT_INVALID."""
    rec = Recorder()
    fake = FakeAnthropic([message("nope")], counts=[1_000, BUDGET + 1])
    with pytest.raises(ModelOutputInvalid) as exc:
        run(fake, recorder=rec)
    assert fake.calls == 1 and fake.counts_made == 2
    assert exc.value.code == "MODEL_OUTPUT_INVALID"
    assert WARN_REPAIR_NO_ROOM in rec.messages
    assert WARN_REPAIR_NO_ROOM == (
        "model output invalid; no room for a repair call within max_context_tokens"
    )


# ---------------------------------------------------------------------------
# AC3 count_tokens (TC-216-14..19)
# ---------------------------------------------------------------------------


def test_count_before_every_stream_with_the_same_payload():
    fake = FakeAnthropic([prompt_too_long(), message("nope"), _ok()])
    run(fake)
    assert fake.kinds == ["count", "stream"] * 3
    for count, stream in zip(fake.count_requests, fake.stream_requests, strict=True):
        assert set(count) == COUNT_KEYS
        assert count == {k: stream[k] for k in COUNT_KEYS}
        assert "fallbacks" not in count and "betas" not in count and "max_tokens" not in count


def test_count_exactly_b_is_sent():
    fake = FakeAnthropic([_ok()], counts=[BUDGET])
    result = run(fake)
    assert fake.calls == 1 and result.calls == 1


def test_count_b_plus_one_with_full_files_rebuilds_then_sends_once():
    ins = review_inputs()
    p = first_prompt(ins)
    assert p.context.full_files_included
    rec = Recorder()
    fake = FakeAnthropic([_ok()], counts=[BUDGET + 1, BUDGET])
    result = run(fake, ins, prompt=p, recorder=rec)
    assert fake.kinds == ["count", "count", "stream"]
    (rebuilt,) = rec.prompts
    assert rebuilt.context.full_files_included == ()
    assert fake.stream_requests[0]["messages"][0]["content"][0]["text"] == rebuilt.user
    assert LABEL_FILE not in rebuilt.user
    assert result.context == rebuilt.context
    assert WARN_CONTEXT_RETRY in rec.messages
    assert dict(rec.warns)[WARN_CONTEXT_RETRY]["files"] == len(p.context.full_files_included)


def test_count_rebuild_is_the_runs_one_context_length_rebuild():
    """DF-28 pinned: after a count-triggered rebuild, a ``prompt is too long`` has no retry."""
    rec = Recorder()
    fake = FakeAnthropic([prompt_too_long()], counts=[BUDGET + 1, 10])
    with pytest.raises(ModelApiError) as exc:
        run(fake, recorder=rec)
    assert exc.value.code == "MODEL_API_ERROR"
    assert fake.calls == 1
    assert rec.messages == [WARN_CONTEXT_RETRY, WARN_CONTEXT_AFTER_RETRY]


@pytest.mark.parametrize(
    "counts", [[BUDGET + 1], [BUDGET + 1, BUDGET + 1]], ids=["no-files", "still-over"]
)
def test_count_over_b_with_nothing_to_drop_is_budget_invariant_and_sends_nothing(counts):
    ins = review_inputs(files=()) if len(counts) == 1 else review_inputs()
    fake = FakeAnthropic([], counts=counts)
    with pytest.raises(BudgetInvariantError):
        run(fake, ins)
    assert fake.calls == 0
    assert fake.counts_made == len(counts)


@pytest.mark.parametrize(
    "error",
    [server_error(), overloaded(), connection_error(), timeout_error(), rate_limited()],
    ids=["500", "529", "connection", "timeout", "429"],
)
def test_count_failure_falls_back_to_the_estimate_with_a_warn(error):
    rec = Recorder()
    fake = FakeAnthropic([_ok()], counts=[error])
    result = run(fake, recorder=rec)
    assert fake.calls == 1 and result.calls == 1
    (data,) = [d for m, d in rec.warns if m == WARN_COUNT_FAILED]
    assert set(data) <= {"calls", "error", "status", "request_id"}
    assert data["error"] == type(error).__name__
    assert SENTINEL not in repr(rec.warns)


def test_count_failure_with_estimate_over_b_and_files_rebuilds(monkeypatch):
    monkeypatch.setattr(
        model_adapter,
        "request_tokens",
        lambda r: (
            BUDGET + 1 if any(LABEL_FILE in b["text"] for b in r["messages"][0]["content"]) else 10
        ),
    )
    rec = Recorder()
    fake = FakeAnthropic([_ok()], counts=[server_error(), server_error()])
    result = run(fake, recorder=rec)
    assert fake.calls == 1
    assert result.context.full_files_included == ()
    assert rec.messages.count(WARN_COUNT_FAILED) == 2


def test_count_failure_with_estimate_over_b_and_no_files_is_budget_invariant(monkeypatch):
    monkeypatch.setattr(model_adapter, "request_tokens", lambda r: BUDGET + 1)
    fake = FakeAnthropic([], counts=[server_error()])
    with pytest.raises(BudgetInvariantError):
        run(fake, review_inputs(files=()))
    assert fake.calls == 0


@pytest.mark.parametrize(
    "result",
    [
        loose_message(),  # an object without input_tokens
        type("C", (), {"input_tokens": None})(),
        type("C", (), {"input_tokens": -1})(),
        type("C", (), {"input_tokens": True})(),
        type("C", (), {"input_tokens": 10.0})(),
        type("C", (), {"input_tokens": 10**18 + 1})(),
        None,
    ],
    ids=["missing", "none", "negative", "bool", "float", "huge", "no-object"],
)
def test_count_malformed_result_is_a_count_failure(result):
    rec = Recorder()
    fake = FakeAnthropic([_ok()], counts=[result])
    run(fake, recorder=rec)
    assert fake.calls == 1
    assert WARN_COUNT_FAILED in rec.messages


def test_count_calls_are_not_in_the_call_metrics():
    fake = FakeAnthropic([message("nope"), _ok()], counts=[25_000, 25_000])
    result = run(fake)
    assert fake.counts_made == 2
    assert result.calls == 2
    assert result.input_tokens == 2_000 and result.output_tokens == 400


# ---------------------------------------------------------------------------
# AC4 prompt is too long (TC-216-21..24)
# ---------------------------------------------------------------------------


def test_context_length_retries_once_without_full_files():
    ins = review_inputs()
    p = first_prompt(ins)
    rec = Recorder()
    fake = FakeAnthropic([prompt_too_long(), _ok()])
    result = run(fake, ins, prompt=p, recorder=rec)
    assert fake.kinds == ["count", "stream", "count", "stream"]
    (retry,) = rec.prompts
    assert retry.context.full_files_included == ()
    assert fake.stream_requests[1]["messages"][0]["content"][0]["text"] == retry.user
    assert fake.stream_requests[1]["system"] == retry.system
    assert result.context == retry.context and result.prompt is retry
    assert rec.messages == [WARN_CONTEXT_RETRY]
    assert WARN_CONTEXT_RETRY == "context length rejected; retrying without full files"


def test_context_length_twice_is_model_api_error_with_the_d48_warn():
    rec = Recorder()
    fake = FakeAnthropic([prompt_too_long(), prompt_too_long()])
    with pytest.raises(ModelApiError) as exc:
        run(fake, recorder=rec)
    assert fake.calls == 2
    assert exc.value.code == "MODEL_API_ERROR"
    assert rec.messages == [WARN_CONTEXT_RETRY, WARN_CONTEXT_AFTER_RETRY]
    assert WARN_CONTEXT_AFTER_RETRY == "context length rejected after R4 retry"


def test_context_length_on_the_repair_call_is_model_api_error():
    rec = Recorder()
    fake = FakeAnthropic([message("nope"), prompt_too_long()])
    with pytest.raises(ModelApiError):
        run(fake, recorder=rec)
    assert fake.calls == 2
    assert rec.messages[-1] == WARN_CONTEXT_REPAIR
    assert WARN_CONTEXT_REPAIR == "context length rejected on the repair call"


def test_context_length_with_no_full_files_is_model_api_error_without_retry():
    rec = Recorder()
    fake = FakeAnthropic([prompt_too_long()])
    with pytest.raises(ModelApiError):
        run(fake, review_inputs(files=()), recorder=rec)
    assert fake.calls == 1
    assert rec.messages == [WARN_CONTEXT_NO_FILES]
    assert "no full files to remove" in WARN_CONTEXT_NO_FILES


def test_context_length_match_is_case_folded():
    err = api_status_error(400, "Prompt Is Too Long: 5 > 4", error_type="invalid_request_error")
    fake = FakeAnthropic([err, _ok()])
    assert run(fake).calls == 2


@pytest.mark.parametrize(
    "error",
    [
        api_status_error(
            400, "x" * 4096 + "prompt is too long", error_type="invalid_request_error"
        ),
        bad_request("output_config.format.schema: unsupported keyword"),
        bad_request("Unexpected value for anthropic-beta"),
        api_status_error(413, "prompt is too long", error_type="request_too_large"),
    ],
    ids=["after-4kib", "schema-rejected", "beta-unknown", "413"],
)
def test_context_length_other_rejections_are_model_api_error_without_retry(error):
    fake = FakeAnthropic([error])
    with pytest.raises(ModelApiError) as exc:
        run(fake)
    assert fake.calls == 1
    assert exc.value.code == "MODEL_API_ERROR"


# ---------------------------------------------------------------------------
# AC5 error mapping (TC-216-26..28)
# ---------------------------------------------------------------------------

_MAPPING = [
    (rate_limited(), ModelRateLimited, "MODEL_RATE_LIMITED"),
    (auth_error(), ModelAccessDenied, "MODEL_ACCESS_DENIED"),
    (permission_denied(), ModelAccessDenied, "MODEL_ACCESS_DENIED"),
    (server_error(), ModelApiError, "MODEL_API_ERROR"),
    (overloaded(), ModelApiError, "MODEL_API_ERROR"),
    (api_status_error(404, "model not found"), ModelApiError, "MODEL_API_ERROR"),
    (api_status_error(409, "conflict"), ModelApiError, "MODEL_API_ERROR"),
    (api_status_error(422, "unprocessable"), ModelApiError, "MODEL_API_ERROR"),
    (bad_request(), ModelApiError, "MODEL_API_ERROR"),
    (connection_error(), ModelApiError, "MODEL_API_ERROR"),
    (api_status_error(418, "teapot"), ModelApiError, "MODEL_API_ERROR"),
]
_IDS = ["429", "401", "403", "500", "529", "404", "409", "422", "400", "conn", "418"]


@pytest.mark.parametrize("error,cls,code", _MAPPING, ids=_IDS)
def test_errors_first_call_mapping(error, cls, code):
    fake = FakeAnthropic([error])
    with pytest.raises(cls) as exc:
        run(fake)
    assert exc.value.code == code
    assert fake.calls == 1


@pytest.mark.parametrize("error,cls,code", _MAPPING, ids=_IDS)
def test_errors_repair_call_mapping(error, cls, code):
    fake = FakeAnthropic([message("nope"), error])
    with pytest.raises(cls) as exc:
        run(fake)
    assert exc.value.code == code
    assert fake.calls == 2


def test_errors_mid_stream_failure_is_mapped_too():
    fake = FakeAnthropic([MidStream(overloaded())])
    with pytest.raises(ModelApiError):
        run(fake)


def test_errors_timeout_before_the_deadline_is_model_api_error():
    fake = FakeAnthropic([timeout_error()])
    with pytest.raises(ModelTimeout) as exc:
        run(fake, clock=Clock(step=0.5), deadline=10_000.0)
    assert exc.value.code == "MODEL_API_ERROR"


def test_errors_timeout_past_the_deadline_is_run_timeout():
    clock = Clock(step=0.0)

    def late(kwargs):
        clock.now = 10_001.0
        return timeout_error()

    fake = FakeAnthropic([late])
    with pytest.raises(ModelTimeout) as exc:
        run(fake, clock=clock, deadline=10_000.0)
    assert exc.value.code == "RUN_TIMEOUT"


def test_errors_rate_limit_past_the_deadline_is_run_timeout():
    """DF-25 pinned: throttling past the deadline is RUN_TIMEOUT (spec §13)."""
    clock = Clock(step=0.0)

    def late(kwargs):
        clock.now = 10_001.0
        return rate_limited()

    fake = FakeAnthropic([late])
    with pytest.raises(ModelAdapterError) as exc:
        run(fake, clock=clock, deadline=10_000.0)
    assert exc.value.code == "RUN_TIMEOUT"


def test_errors_a_passed_deadline_sends_no_call():
    fake = FakeAnthropic([_ok()])
    with pytest.raises(ModelTimeout) as exc:
        run(fake, clock=Clock(step=0.0, start=200.0), deadline=100.0)
    assert exc.value.code == "RUN_TIMEOUT"
    assert fake.calls == 0 and fake.counts_made == 0


def test_errors_a_call_returning_after_the_deadline_keeps_its_tokens():
    """The adapter returns; the pipeline's deadline check then makes it RUN_TIMEOUT."""
    clock = Clock(step=0.0)

    def late(kwargs):
        clock.now = 10_001.0
        return _ok()

    result = run(FakeAnthropic([late]), clock=clock, deadline=10_000.0)
    assert result.input_tokens == 1000


def test_errors_carry_partial_metrics():
    fake = FakeAnthropic([message("nope"), server_error()])
    with pytest.raises(ModelApiError) as exc:
        run(fake)
    m = exc.value.metrics
    assert isinstance(m, CallMetrics)
    assert m.calls == 2 and m.input_tokens == 1000 and m.answered_by_model == MODEL


def test_errors_name_class_status_and_request_id_only():
    err = api_status_error(500, SENTINEL, request_id="req_abc-123")
    fake = FakeAnthropic([err])
    with pytest.raises(ModelApiError) as exc:
        run(fake)
    text = str(exc.value)
    assert "InternalServerError" in text and "500" in text and "req_abc-123" in text
    assert SENTINEL not in text
    assert exc.value.__cause__ is None and exc.value.__suppress_context__


def test_errors_request_id_outside_the_allowlist_is_dropped():
    err = api_status_error(500, "x", request_id="req bad\nid" + SENTINEL)
    fake = FakeAnthropic([err])
    with pytest.raises(ModelApiError) as exc:
        run(fake)
    assert SENTINEL not in str(exc.value) and "\n" not in str(exc.value)


# ---------------------------------------------------------------------------
# AC5 refusal (TC-216-29, 30; DF-26)
# ---------------------------------------------------------------------------


def test_refusal_first_call_is_model_refused_with_no_repair():
    fake = FakeAnthropic([message(SENTINEL, stop_reason="refusal")])
    with pytest.raises(ModelRefused) as exc:
        run(fake)
    assert exc.value.code == "MODEL_REFUSED"
    assert fake.calls == 1
    assert SENTINEL not in str(exc.value)
    assert exc.value.metrics.repair_calls == 0


def test_refusal_after_the_context_length_retry_is_model_refused():
    fake = FakeAnthropic([prompt_too_long(), message("", stop_reason="refusal")])
    with pytest.raises(ModelRefused):
        run(fake)
    assert fake.calls == 2


def test_refusal_on_the_repair_call_is_model_refused():
    fake = FakeAnthropic([message("nope"), message("", stop_reason="refusal")])
    with pytest.raises(ModelRefused) as exc:
        run(fake)
    assert fake.calls == 2 and exc.value.metrics.repair_calls == 1


def test_refusal_answered_by_a_fallback_model_is_a_normal_response():
    fake = FakeAnthropic([review_message(valid_review(), model="claude-opus-5-1")])
    result = run(fake)
    assert result.findings == valid_review()
    assert result.answered_by_model == "claude-opus-5-1"


# ---------------------------------------------------------------------------
# AC5 clients and timeouts (TC-216-28)
# ---------------------------------------------------------------------------


class _Factory:
    def __init__(self, fake: FakeAnthropic) -> None:
        self.fake = fake
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> FakeAnthropic:
        self.calls.append(kwargs)
        return self.fake


def test_client_factory_builds_one_client_per_stream_call_with_its_count():
    fake = FakeAnthropic([prompt_too_long(), message("nope"), _ok()])
    factory = _Factory(fake)
    run(None, client_factory=factory, clock=Clock(step=0.0), deadline=1_000.0)
    assert len(factory.calls) == 3
    for kw in factory.calls:
        assert set(kw) == {"read_timeout_seconds", "connect_timeout_seconds", "max_retries"}
        assert kw["max_retries"] == 2
    t = call_timeouts(900.0)
    assert t is not None
    assert factory.calls[0]["read_timeout_seconds"] == t.read
    assert factory.calls[0]["connect_timeout_seconds"] == t.connect


@pytest.mark.parametrize("remaining", [14.0, 40.0, 300.0, 900.0, 5_000.0])
def test_client_call_timeouts_follow_the_spec(remaining):
    t = call_timeouts(remaining)
    per = (remaining - 13) / 3
    if per < 2:
        assert t is None
        return
    assert t is not None
    assert t.connect == pytest.approx(min(10, per / 4))
    assert t.read == pytest.approx(min(600, per - t.connect))


def test_client_too_little_time_left_starts_no_call():
    fake = FakeAnthropic([_ok()])
    with pytest.raises(ModelTimeout) as exc:
        run(None, client_factory=_Factory(fake), clock=Clock(step=0.0, start=0.0), deadline=18.0)
    assert exc.value.code == "RUN_TIMEOUT"
    assert fake.calls == 0 and fake.counts_made == 0


def test_client_without_a_deadline_uses_the_caps():
    factory = _Factory(FakeAnthropic([_ok()]))
    run(None, client_factory=factory)
    assert factory.calls[0]["read_timeout_seconds"] == 600
    assert factory.calls[0]["connect_timeout_seconds"] == 10


@pytest.mark.parametrize("both", [True, False])
def test_client_exactly_one_of_client_and_factory(both):
    fake = FakeAnthropic([_ok()])
    ins = review_inputs()
    with pytest.raises(ValueError):
        model_adapter.review(
            first_prompt(ins),
            ins,
            client=fake if both else None,
            client_factory=_Factory(fake) if both else None,
            settings=__import__("tests.helpers.model_run", fromlist=["settings"]).settings(),
            reasoning_effort="high",
            max_diff_lines=2000,
        )


def test_client_unknown_effort_is_rejected_before_any_call():
    fake = FakeAnthropic([_ok()])
    with pytest.raises(ValueError):
        run(fake, effort="max")
    assert fake.calls == 0


def test_client_make_client_builds_the_sdk_client_with_the_key(monkeypatch):
    seen: list[dict[str, Any]] = []

    class Spy:
        def __init__(self, **kwargs: Any) -> None:
            seen.append(kwargs)

    monkeypatch.setattr(model_adapter.anthropic, "Anthropic", Spy)
    client = model_adapter.make_client(
        api_key="sk-ant-api03-TEST", read_timeout_seconds=100.0, connect_timeout_seconds=7.0
    )
    assert isinstance(client, Spy)
    (kw,) = seen
    assert kw["api_key"] == "sk-ant-api03-TEST"
    assert kw["max_retries"] == 2
    timeout = kw["timeout"]
    assert timeout.connect == 7.0 and timeout.read == 100.0


# ---------------------------------------------------------------------------
# AC6 answering model (TC-216-34..36; DF-32)
# ---------------------------------------------------------------------------


def test_answered_by_model_is_the_message_model():
    result = run(FakeAnthropic([_ok()]))
    assert result.answered_by_model == MODEL
    assert result.metrics.as_metrics()["answered_by_model"] == MODEL


def test_answered_by_the_accepted_call_across_models():
    fake = FakeAnthropic(
        [message("nope", model="claude-sonnet-5-5"), review_message(valid_review(), model="B")]
    )
    result = run(fake)
    assert result.answered_by_model == "B"


@pytest.mark.parametrize("model", [None, "", 42, ["x"]], ids=["none", "empty", "int", "list"])
def test_answered_by_model_missing_or_not_a_string_is_null(model):
    """DF-32 pinned: never substituted from MODEL_ID."""
    fake = FakeAnthropic([loose_message(json.dumps(valid_review()), model=model)])
    result = run(fake)
    assert result.answered_by_model is None
    assert result.cost_usd is None


def test_answered_by_model_absent_attribute_is_null():
    fake = FakeAnthropic([loose_message(json.dumps(valid_review()), omit=("model",))])
    assert run(fake).answered_by_model is None


# ---------------------------------------------------------------------------
# AC7 call budget (TC-216-38, 39)
# ---------------------------------------------------------------------------


def test_call_budget_worst_sequence_uses_exactly_three_calls():
    fake = FakeAnthropic([prompt_too_long(), message("nope"), _ok()])
    result = run(fake)
    assert fake.kinds == ["count", "stream"] * 3
    assert result.calls == 3 and result.repair_calls == 1
    assert result.metrics.as_metrics()["model_calls"] == 3


def test_call_budget_is_three():
    assert MAX_CALLS == 3


def test_call_budget_guard_raises_before_the_fake_sees_the_call(monkeypatch):
    monkeypatch.setattr(model_adapter, "MAX_CALLS", 2)
    fake = FakeAnthropic([prompt_too_long(), message("nope"), _ok()])
    with pytest.raises(CallBudgetExceeded) as exc:
        run(fake)
    assert exc.value.code == "INTERNAL_ERROR"
    assert fake.calls == 2


# ---------------------------------------------------------------------------
# AC8 usage and cost (TC-216-41, 42)
# ---------------------------------------------------------------------------


def test_usage_cost_at_the_price_table():
    fake = FakeAnthropic([review_message(valid_review(), usage=(393_000, 12_000))])
    result = run(fake)
    assert result.input_tokens == 393_000 and result.output_tokens == 12_000
    assert result.cost_usd == 0.906
    assert PRICE_TABLE == {"claude-sonnet-5-5": (2.0, 10.0)}


def test_usage_is_summed_over_every_call_that_returned():
    fake = FakeAnthropic(
        [message("nope", usage=(100, 10)), review_message(valid_review(), usage=(200, 20))]
    )
    result = run(fake)
    assert (result.input_tokens, result.output_tokens) == (300, 30)
    assert result.cost_usd == round((300 * 2 + 30 * 10) / 1e6, 6)


def test_usage_another_model_has_tokens_but_no_cost_and_one_warn():
    rec = Recorder()
    fake = FakeAnthropic([review_message(valid_review(), model="claude-opus-5-1")])
    result = run(fake, recorder=rec)
    assert result.input_tokens == 1000 and result.cost_usd is None
    assert rec.messages.count(WARN_NO_PRICE) == 1
    assert SENTINEL not in repr(rec.warns)


def test_usage_dated_model_id_has_no_cost():
    """DF-31 pinned: exact key match only."""
    fake = FakeAnthropic([review_message(valid_review(), model="claude-sonnet-5-5-20261101")])
    assert run(fake).cost_usd is None


def test_usage_mixed_models_have_no_cost():
    fake = FakeAnthropic([message("nope", model="other"), review_message(valid_review())])
    result = run(fake)
    assert result.cost_usd is None and result.input_tokens == 2000


@pytest.mark.parametrize(
    "usage",
    [None, ("1", 2), (True, 2), (-1, 2), (1, 10**18 + 1), (1.5, 2), (1, None)],
    ids=["missing", "str", "bool", "negative", "huge", "float", "none-out"],
)
def test_usage_missing_or_malformed_nulls_tokens_and_cost(usage):
    fake = FakeAnthropic([loose_message(json.dumps(valid_review()), usage=usage)])
    result = run(fake)
    assert result.input_tokens is None and result.output_tokens is None
    assert result.cost_usd is None


def test_usage_extra_keys_are_ignored():
    msg = review_message(valid_review(), usage=(10, 5))
    msg.usage.cache_read_input_tokens = 99
    result = run(FakeAnthropic([msg]))
    assert (result.input_tokens, result.output_tokens) == (10, 5)


def test_usage_model_ms_is_measured_around_every_call():
    result = run(FakeAnthropic([message("nope"), _ok()]), clock=Clock(step=0.5))
    assert result.model_ms > 0
    assert result.metrics.as_metrics()["model_ms"] == result.model_ms


def test_usage_metrics_use_the_v18_names():
    m = run(FakeAnthropic([_ok()])).metrics.as_metrics()
    assert set(m) == {
        "input_tokens",
        "output_tokens",
        "cost_usd",
        "model_ms",
        "output_mode",
        "repair_calls",
        "reasoning_effort_applied",
        "model_calls",
        "answered_by_model",
    }
    assert "bedrock_ms" not in m and "bedrock_calls" not in m


# ---------------------------------------------------------------------------
# AC10 result shape (TC-216-53)
# ---------------------------------------------------------------------------


def test_result_shape_fields():
    assert {f.name for f in dataclasses.fields(CallMetrics)} == {
        "calls",
        "repair_calls",
        "input_tokens",
        "output_tokens",
        "model_ms",
        "cost_usd",
        "output_mode",
        "reasoning_effort_applied",
        "answered_by_model",
    }
    assert {f.name for f in dataclasses.fields(ReviewResult)} == {
        "findings",
        "metrics",
        "context",
        "prompt",
    }


def test_result_shape_review_keyword_names():
    import inspect

    params = inspect.signature(model_adapter.review).parameters
    assert list(params) == [
        "prompt",
        "inputs",
        "client",
        "client_factory",
        "settings",
        "reasoning_effort",
        "max_diff_lines",
        "warn",
        "sink",
        "nonce_factory",
        "clock",
        "deadline",
    ]


def test_result_shape_error_codes():
    assert {
        cls.code
        for cls in (
            ModelAccessDenied,
            ModelApiError,
            ModelRateLimited,
            ModelRefused,
            ModelOutputInvalid,
        )
    } == {
        "MODEL_ACCESS_DENIED",
        "MODEL_API_ERROR",
        "MODEL_RATE_LIMITED",
        "MODEL_REFUSED",
        "MODEL_OUTPUT_INVALID",
    }
    assert CallBudgetExceeded.code == "INTERNAL_ERROR"


def test_warn_is_optional():
    ins = review_inputs()
    model_adapter.review(
        first_prompt(ins),
        ins,
        client=FakeAnthropic([message("nope"), _ok()]),
        settings=__import__("tests.helpers.model_run", fromlist=["settings"]).settings(),
        reasoning_effort="high",
        max_diff_lines=2000,
    )


def test_no_bedrock_name_in_the_adapter():
    assert not re.search(r"(?i)bedrock|converse", _adapter_source())
