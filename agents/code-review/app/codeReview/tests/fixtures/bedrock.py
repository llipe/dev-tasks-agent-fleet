"""
A fake Bedrock Runtime ``converse`` (S-210; reused by S-213).

``FakeConverse`` stands in for the boto3 ``bedrock-runtime`` client. It makes
no network call and imports no AWS client: it records every request (a deep
copy of the keyword arguments, so tests can assert the exact request shape,
CT-06) and answers from a script, in order. A script item is one of:

- a response ``dict`` (built with ``tool_use_response`` or ``text_response``,
  CT-07 shapes), returned as a deep copy;
- an ``Exception`` instance, raised (``client_error`` builds the modeled
  botocore ``ClientError`` subclass the real client raises, with
  ``{"Error": {"Code", "Message"}, "ResponseMetadata"}``);
- a callable ``(request) -> dict``, for a response that depends on the request.

A call past the end of the script raises ``AssertionError`` ("unexpected
Converse call"), so a test also pins the number of calls.
"""

from __future__ import annotations

import copy
import functools
from collections.abc import Callable, Iterable, Sequence
from typing import Any

from botocore.exceptions import ClientError

__all__ = [
    "FakeConverse",
    "access_denied",
    "client_error",
    "context_length_rejected",
    "finding",
    "reasoning_rejected",
    "service_unavailable",
    "text_response",
    "throttled",
    "tool_choice_rejected",
    "tool_use_response",
    "valid_review",
    "validation_error",
]

ScriptItem = dict[str, Any] | BaseException | Callable[[dict[str, Any]], dict[str, Any]]


class FakeConverse:
    """A scripted, recording stand-in for ``bedrock-runtime.converse``."""

    def __init__(self, script: Iterable[ScriptItem] = ()) -> None:
        self.script: list[ScriptItem] = list(script)
        self.requests: list[dict[str, Any]] = []

    def push(self, *items: ScriptItem) -> FakeConverse:
        self.script.extend(items)
        return self

    def converse(self, **kwargs: Any) -> dict[str, Any]:
        self.requests.append(copy.deepcopy(kwargs))
        if not self.script:
            raise AssertionError(f"unexpected Converse call #{len(self.requests)}")
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        if callable(item):
            return item(copy.deepcopy(kwargs))
        return copy.deepcopy(item)

    @property
    def calls(self) -> int:
        return len(self.requests)


# ---------------------------------------------------------------------------
# Responses (CT-07)
# ---------------------------------------------------------------------------


def _usage(usage: tuple[int, int] | None) -> dict[str, Any]:
    if usage is None:
        return {}
    i, o = usage
    return {"usage": {"inputTokens": i, "outputTokens": o, "totalTokens": i + o}}


def tool_use_response(
    tool_input: Any,
    *,
    name: str = "submit_review",
    usage: tuple[int, int] | None = (1000, 200),
    stop_reason: str = "tool_use",
    before: Sequence[dict[str, Any]] = (),
    tool_use_id: str = "tooluse_1",
) -> dict[str, Any]:
    """A response whose message holds ``before`` blocks, then one ``toolUse`` block."""
    content = [*before, {"toolUse": {"toolUseId": tool_use_id, "name": name, "input": tool_input}}]
    return {
        "output": {"message": {"role": "assistant", "content": content}},
        "stopReason": stop_reason,
        **_usage(usage),
        "metrics": {"latencyMs": 1234},
    }


def text_response(
    text: str,
    *,
    usage: tuple[int, int] | None = (1000, 200),
    stop_reason: str = "end_turn",
    before: Sequence[dict[str, Any]] = (),
) -> dict[str, Any]:
    """A response whose message holds ``before`` blocks, then one text block."""
    return {
        "output": {"message": {"role": "assistant", "content": [*before, {"text": text}]}},
        "stopReason": stop_reason,
        **_usage(usage),
        "metrics": {"latencyMs": 1234},
    }


# ---------------------------------------------------------------------------
# Errors (botocore ``ClientError`` shapes)
# ---------------------------------------------------------------------------


@functools.cache
def _modeled_exceptions() -> Any:
    """The real client's exception factory (no network: the client is never called)."""
    import botocore.session

    return (
        botocore.session.Session()
        .create_client(
            "bedrock-runtime",
            region_name="us-east-1",
            aws_access_key_id="fixture",
            aws_secret_access_key="fixture",
        )
        .exceptions
    )


def client_error(
    code: str, message: str = "", *, status: int = 400, request_id: str = "req-0001"
) -> ClientError:
    """A botocore error as the real client raises it: the modeled subclass for a
    Bedrock Runtime code (``ValidationException``, ``ThrottlingException``, ...),
    plain ``ClientError`` for any other code, with the full ``ResponseMetadata``."""
    cls = _modeled_exceptions().from_code(code)
    return cls(
        {
            "Error": {"Code": code, "Message": message},
            "ResponseMetadata": {
                "RequestId": request_id,
                "HTTPStatusCode": status,
                "HTTPHeaders": {
                    "content-type": "application/json",
                    "x-amzn-requestid": request_id,
                    "x-amzn-errortype": code,
                },
                "RetryAttempts": 0,
            },
        },
        "Converse",
    )


def validation_error(message: str) -> ClientError:
    return client_error("ValidationException", message)


def tool_choice_rejected() -> ClientError:
    return validation_error("This model doesn't support the toolConfig.toolChoice.tool field.")


def reasoning_rejected(field: str = "reasoning_effort") -> ClientError:
    return validation_error(f"The model returned the following errors: Unknown parameter: {field}")


def context_length_rejected() -> ClientError:
    return validation_error("Input is too long for requested model.")


def access_denied() -> ClientError:
    return client_error(
        "AccessDeniedException",
        "You don't have access to the model with the specified model ID.",
        status=403,
    )


def throttled() -> ClientError:
    return client_error("ThrottlingException", "Too many requests, please wait.", status=429)


def service_unavailable() -> ClientError:
    return client_error("ServiceUnavailableException", "Service unavailable.", status=503)


# ---------------------------------------------------------------------------
# Review objects (spec §6.3)
# ---------------------------------------------------------------------------


def finding(rank: int = 1, **overrides: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "severity": "blocking",
        "category": "correctness",
        "file": "src/app.py",
        "line_start": 1,
        "line_end": 1,
        "title": "Off-by-one in the size check",
        "failure_scenario": "A size of exactly 10 is rejected.",
        "consequence": "Valid widgets cannot be saved.",
        "rank": rank,
    }
    out.update(overrides)
    return out


def valid_review(n: int = 1, checks: Sequence[dict[str, Any]] = ()) -> dict[str, Any]:
    return {"findings": [finding(k + 1) for k in range(n)], "verifier_checks": list(checks)}
