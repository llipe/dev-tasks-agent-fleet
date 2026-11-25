"""
CT-14 (S-216) — the fake Anthropic client matches the pinned SDK's surface.

Every keyword the adapter passes to ``FakeAnthropic`` must be a parameter of
the real ``Anthropic().beta.messages.stream`` / ``.messages.count_tokens`` in
the pinned ``anthropic`` version, so a test that passes against the fake does
not depend on a parameter the SDK would reject. The fake's final messages are
real ``anthropic.types.beta.BetaMessage`` objects, and its errors are the
SDK's own classes built over an ``httpx2.Response``.
"""

from __future__ import annotations

import inspect

import anthropic
import pydantic
import pytest
from anthropic.resources.beta.messages.messages import Messages as BetaMessages
from anthropic.resources.messages.messages import Messages
from anthropic.types.beta import BetaMessage

from tests.fixtures.anthropic_fake import (
    FakeAnthropic,
    api_status_error,
    fallback_block,
    message,
    prompt_too_long,
    rate_limited,
    review_message,
    valid_review,
)
from tests.helpers.model_run import run


def _params(fn) -> set[str]:
    return set(inspect.signature(fn).parameters) - {"self"}


def test_every_stream_kwarg_is_a_named_sdk_parameter():
    fake = FakeAnthropic([review_message(valid_review())])
    run(fake)
    (kwargs,) = fake.stream_requests
    assert set(kwargs) <= _params(BetaMessages.stream)
    for name in ("output_config", "betas", "fallbacks"):
        assert name in _params(BetaMessages.stream), f"{name} needs extra_body in this SDK"


def test_every_count_kwarg_is_a_named_sdk_parameter():
    fake = FakeAnthropic([review_message(valid_review())])
    run(fake)
    (kwargs,) = fake.count_requests
    assert set(kwargs) <= _params(Messages.count_tokens)


def test_the_installed_sdk_is_the_pinned_one():
    import tomllib
    from pathlib import Path

    pins = tomllib.loads((Path(__file__).resolve().parents[2] / "pyproject.toml").read_text())
    (pin,) = [d for d in pins["project"]["dependencies"] if d.startswith("anthropic==")]
    assert anthropic.__version__ == pin.split("==", 1)[1]


def test_fake_messages_are_real_sdk_objects():
    msg = message("{}")
    assert isinstance(msg, BetaMessage)
    assert msg.model == "claude-sonnet-5-5" and msg.stop_reason == "end_turn"


@pytest.mark.parametrize("missing", ["model", "usage", "content", "role"])
def test_a_message_without_a_required_field_fails_validation(missing):
    data = message("{}").model_dump()
    del data[missing]
    with pytest.raises(pydantic.ValidationError):
        BetaMessage.model_validate(data)


def test_unknown_block_types_validate_and_are_ignored_by_the_adapter():
    blocks = [
        {"type": "server_tool_use", "id": "srvtoolu_1", "name": "web_search", "input": {}},
        {"type": "text", "text": '{"findings": [], "verifier_checks": []}'},
    ]
    msg = message(blocks=blocks)
    assert [b.type for b in msg.content] == ["server_tool_use", "text"]
    assert run(FakeAnthropic([msg])).findings == {"findings": [], "verifier_checks": []}


@pytest.mark.parametrize(
    "error,cls",
    [
        (rate_limited(), anthropic.RateLimitError),
        (prompt_too_long(), anthropic.BadRequestError),
        (api_status_error(401, "x"), anthropic.AuthenticationError),
        (api_status_error(403, "x"), anthropic.PermissionDeniedError),
        (api_status_error(500, "x"), anthropic.InternalServerError),
    ],
)
def test_fake_errors_are_the_sdks_own_classes(error, cls):
    assert type(error) is cls
    assert isinstance(error, anthropic.APIStatusError)
    assert error.request_id == "req_fixture_0001"
    assert isinstance(error.status_code, int)


def test_the_fake_fallback_block_is_the_sdks_beta_fallback_block():
    """D-86: the real ``BetaFallbackBlock`` type, so the adapter is tested on real shapes."""
    from anthropic.types.beta import BetaFallbackBlock

    msg = message(
        blocks=[{"type": "text", "text": "a"}, fallback_block(), {"type": "text", "text": "b"}]
    )
    assert isinstance(msg.content[1], BetaFallbackBlock)
    assert msg.content[1].type == "fallback"
    assert msg.content[1].to.model == "claude-opus-5-1"
