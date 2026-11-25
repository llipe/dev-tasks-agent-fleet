"""
S-216 (#480) — hostile inputs to the Anthropic adapter (ADR-009; SN-17).

Ports ``test_bedrock_hostile.py``: no API message, prompt text or model text
ever reaches an exception message or a ``warn`` event (TC-216-25, TC-216-31),
and the seeded tactics RT-17 (seed 480004, labelled schema mutations) and
RT-18 (seed 480005, SDK error class x status x message x deadline x call).
Replay one iteration with
``PRNG_SEED=<seed> PRNG_ITER=<i> make test-unit -k <test>``.
"""

from __future__ import annotations

import copy
import json
from typing import Any

import anthropic
import pytest

from findings_schema import SchemaViolation, validate_review
from model_adapter import (
    MESSAGE_SCAN_CHARS,
    ModelAdapterError,
    ModelOutputInvalid,
)
from tests.fixtures.anthropic_fake import (
    FakeAnthropic,
    MidStream,
    api_status_error,
    connection_error,
    message,
    review_message,
    timeout_error,
    valid_review,
)
from tests.helpers.model_run import Clock, Recorder, first_prompt, review_inputs, run
from tests.helpers.prng import Tactic, tactic_seed

SENTINEL = "HOSTILE-SENTINEL-7Q"


def _texts(rec: Recorder, exc: BaseException | None) -> str:
    return repr(rec.warns) + (str(exc) + repr(exc) if exc is not None else "")


# ---------------------------------------------------------------------------
# TC-216-25, TC-216-31: the allowlist
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 422, 429, 500, 529])
@pytest.mark.parametrize("call", ["first", "repair"])
def test_api_message_never_reaches_errors_or_warns(status, call):
    err = api_status_error(status, f"{SENTINEL} prompt is too long {SENTINEL}")
    script: list[Any] = [err] if call == "first" else [message(SENTINEL), err]
    rec = Recorder()
    fake = FakeAnthropic(script)
    with pytest.raises(ModelAdapterError) as exc:
        run(fake, review_inputs(files=()), recorder=rec)
    assert SENTINEL not in _texts(rec, exc.value)
    assert exc.value.__cause__ is None


def test_prompt_text_never_reaches_errors_or_warns():
    ins = review_inputs(title=SENTINEL, body=SENTINEL)
    rec = Recorder()
    fake = FakeAnthropic([message("nope"), api_status_error(500, "x")])
    with pytest.raises(ModelAdapterError) as exc:
        run(fake, ins, prompt=first_prompt(ins), recorder=rec)
    assert SENTINEL in fake.stream_requests[0]["messages"][0]["content"][0]["text"]
    assert SENTINEL not in _texts(rec, exc.value)


def test_model_text_never_reaches_errors_or_warns():
    bad = valid_review()
    bad["findings"][0][SENTINEL] = SENTINEL
    bad["findings"][0]["category"] = SENTINEL
    rec = Recorder()
    fake = FakeAnthropic([review_message(bad), message(f"{SENTINEL} not json")])
    with pytest.raises(ModelOutputInvalid) as exc:
        run(fake, recorder=rec)
    assert SENTINEL not in _texts(rec, exc.value)
    # The repair block's wrapper line names a path and a rule only.
    repair = fake.stream_requests[1]["messages"][0]["content"][1]["text"]
    head = repair.split("<<<UNTRUSTED", 1)[0]
    assert SENTINEL not in head


@pytest.mark.parametrize(
    "error",
    [
        connection_error(),
        timeout_error(),
        MidStream(api_status_error(529, SENTINEL)),
        anthropic.APIResponseValidationError(
            response=api_status_error(200, SENTINEL).response, body={"x": SENTINEL}
        ),
    ],
    ids=["connection", "timeout", "mid-stream", "response-validation"],
)
def test_other_sdk_errors_carry_the_class_only(error):
    rec = Recorder()
    with pytest.raises(ModelAdapterError) as exc:
        run(FakeAnthropic([error]), recorder=rec)
    assert SENTINEL not in _texts(rec, exc.value)
    assert exc.value.code == "MODEL_API_ERROR"


@pytest.mark.parametrize(
    "request_id",
    ["req bad", "x" * 101, f"req\n{SENTINEL}", "req<b>", None],
    ids=["space", "long", "newline", "markup", "none"],
)
def test_request_ids_outside_the_allowlist_are_dropped(request_id):
    err = api_status_error(500, "x", request_id=request_id)
    rec = Recorder()
    fake = FakeAnthropic([_ok()], counts=[err])
    run(fake, recorder=rec)
    with pytest.raises(ModelAdapterError) as exc:
        run(FakeAnthropic([err]))
    text = _texts(rec, exc.value)
    if request_id is not None:
        assert request_id not in text
    assert "request_id" not in rec.warns[0][1]


def _ok() -> Any:
    return review_message(valid_review())


# ---------------------------------------------------------------------------
# RT-17 (seed 480004): labelled mutations, one repair each
# ---------------------------------------------------------------------------

_STRING_FIELDS = {"file": 400, "title": 200, "failure_scenario": 1500, "consequence": 500}
_INT_FIELDS = ("line_start", "line_end", "rank")
_ENUMS = {"severity": ("blocking", "suggestion"), "category": ("correctness", "edge_case")}


def _mutation(rng, review: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    """``(rule, path prefix, mutated)``: one stripped or kept rule broken."""
    out = copy.deepcopy(review)
    f = out["findings"][0]
    kind = rng.choice(["maxLength", "minimum", "pattern", "enum", "type", "required", "additional"])
    if kind == "maxLength":
        name = rng.choice(sorted(_STRING_FIELDS))
        f[name] = "a" * (_STRING_FIELDS[name] + rng.randint(1, 50))
        return "maxLength", f"$.findings[0].{name}", out
    if kind == "minimum":
        name = rng.choice(_INT_FIELDS)
        f[name] = rng.randint(-5, 0)
        return "minimum", f"$.findings[0].{name}", out
    if kind == "pattern":
        bad = rng.choice(["V", "Vx", "v1", "X1", "V1 ", " V1", "V-1", ""])
        out["verifier_checks"] = [{"candidate_id": bad, "status": "confirmed", "reason": "r"}]
        return "pattern", "$.verifier_checks[0].candidate_id", out
    if kind == "enum":
        name = rng.choice(sorted(_ENUMS))
        f[name] = rng.choice(["style", "critical", "", "Blocking"])
        return "enum", f"$.findings[0].{name}", out
    if kind == "type":
        name = rng.choice([*_INT_FIELDS, *sorted(_STRING_FIELDS)])
        f[name] = rng.choice([True, 1.5, None, [1], {"a": 1}]) if name in _INT_FIELDS else 7
        return "type", f"$.findings[0].{name}", out
    if kind == "required":
        name = rng.choice([*_INT_FIELDS, *sorted(_STRING_FIELDS), "severity"])
        del f[name]
        return "required", f"$.findings[0].{name}", out
    f["extra_" + str(rng.randint(0, 9))] = 1
    return "additional", "$.findings[0]", out


def test_rt17_every_labelled_mutation_is_rejected_and_repaired_once():
    tactic = Tactic.from_env(tactic_seed(480, 4), 1500)
    rng = tactic.rng()
    base = valid_review()
    for i in range(tactic.iterations):
        rule, path, mutated = _mutation(rng, base)
        if not tactic.selected(i):
            continue
        ctx = tactic.context(i, (rule, path))
        with pytest.raises(SchemaViolation) as exc:
            validate_review(mutated)
        assert exc.value.rule == rule, ctx
        assert str(exc.value).startswith(path), ctx
        if i % 25 == 0 or tactic.replaying:  # the adapter route, sampled
            fake = FakeAnthropic([review_message(mutated), _ok()])
            result = run(fake)
            assert result.repair_calls == 1 and fake.calls == 2, ctx


# ---------------------------------------------------------------------------
# RT-18 (seed 480005): error class x status x message x deadline x call
# ---------------------------------------------------------------------------

_CLASSES: list[tuple[int | None, str]] = [
    (400, "BadRequestError"),
    (401, "AuthenticationError"),
    (403, "PermissionDeniedError"),
    (404, "NotFoundError"),
    (409, "ConflictError"),
    (422, "UnprocessableEntityError"),
    (429, "RateLimitError"),
    (500, "InternalServerError"),
    (529, "OverloadedError"),
    (418, "APIStatusError"),
    (None, "APIConnectionError"),
    (None, "APITimeoutError"),
]


def _oracle(status: int | None, cls: str, phrase_in_scan: bool, late: bool, call: str) -> str:
    """The expected code (TC-216-26/27, DF-25); ``retry`` for the R4 path."""
    if cls == "RateLimitError":
        return "RUN_TIMEOUT" if late else "MODEL_RATE_LIMITED"
    if cls in ("AuthenticationError", "PermissionDeniedError"):
        return "MODEL_ACCESS_DENIED"
    if cls == "APITimeoutError":
        return "RUN_TIMEOUT" if late else "MODEL_API_ERROR"
    if cls == "BadRequestError" and phrase_in_scan and call == "first":
        # The R4 rebuild; past the deadline the retry is never started.
        return "RUN_TIMEOUT" if late else "retry"
    return "MODEL_API_ERROR"


def _make(status: int | None, cls: str, text: str) -> BaseException:
    if cls == "APIConnectionError":
        return connection_error()
    if cls == "APITimeoutError":
        return timeout_error()
    kind = "invalid_request_error" if status == 400 else "api_error"
    return api_status_error(status or 500, text, error_type=kind, cls=getattr(anthropic, cls))


def test_rt18_error_mapping_matches_the_table_oracle():
    tactic = Tactic.from_env(tactic_seed(480, 5), 1500)
    rng = tactic.rng()
    for i in range(tactic.iterations):
        status, cls = rng.choice(_CLASSES)
        has_phrase = rng.random() < 0.5
        offset = rng.choice([0, 10, MESSAGE_SCAN_CHARS - 30, MESSAGE_SCAN_CHARS, 6000])
        phrase = rng.choice(["prompt is too long", "PROMPT IS TOO LONG", "Prompt Is Too Long"])
        filler = "".join(rng.choice("abc xyz") for _ in range(offset))
        text = f"{SENTINEL}{filler}{phrase if has_phrase else 'other'}: {SENTINEL}"
        start = len(SENTINEL) + offset
        in_scan = has_phrase and start + len(phrase) <= MESSAGE_SCAN_CHARS
        late = rng.random() < 0.3
        call = rng.choice(["first", "repair"])
        if not tactic.selected(i):
            continue
        expected = _oracle(status, cls, in_scan, late, call)
        clock = Clock(step=0.0)
        error = _make(status, cls, text)

        def raise_late(
            kwargs: Any, error: BaseException = error, late: bool = late, clock: Clock = clock
        ) -> Any:
            if late:
                clock.now = 10_001.0
            return error

        script: list[Any] = [raise_late] if call == "first" else [message("nope"), raise_late]
        if expected == "retry":
            script.append(_ok())
        rec = Recorder()
        fake = FakeAnthropic(script)
        ctx = tactic.context(i, (status, cls, has_phrase, offset, late, call))
        if expected == "retry":
            result = run(fake, recorder=rec, clock=clock, deadline=10_000.0)
            assert result.calls == 2, ctx
        else:
            with pytest.raises(ModelAdapterError) as exc:
                run(fake, recorder=rec, clock=clock, deadline=10_000.0)
            assert exc.value.code == expected, ctx
            assert SENTINEL not in _texts(rec, exc.value), ctx


def test_rt18_the_oracle_covers_every_class():
    assert {c for _, c in _CLASSES} >= {
        "RateLimitError",
        "AuthenticationError",
        "PermissionDeniedError",
        "APITimeoutError",
        "APIConnectionError",
        "BadRequestError",
    }
    assert json.dumps(_CLASSES)
