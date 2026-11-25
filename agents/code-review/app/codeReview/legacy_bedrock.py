"""
TEMPORARY: the Bedrock Converse helpers the context-selection call still uses.

S-216 (#480) moved the review call to the Anthropic API (``model_adapter.py``)
and deleted ``bedrock_adapter.py``. The selection call (``context/selection.py``,
PRD v1.4 FR-32–FR-34) moves to the Anthropic client in S-217 (#481), which
deletes this module, ``tests/fixtures/bedrock.py``, and the pipeline's
``bedrock_factory`` dep. Until then this is the selection call's client
factory and response helpers, unchanged from ``bedrock_adapter``. Nothing
else may import it (pinned by ``tests/unit/test_layout.py``).
"""

from __future__ import annotations

import math
import os
import re
from typing import Any, Protocol

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

__all__ = [
    "ACCEPTED_STOP_REASONS",
    "MAX_ATTEMPTS",
    "ClientFactory",
    "ConverseClient",
    "aws_error_name",
    "make_client",
    "response_usage",
    "usage_cost",
]

MAX_ATTEMPTS = 3  # botocore standard retry mode
CONNECT_TIMEOUT_SECONDS = 10
MAX_USAGE_TOKENS = 10**18
# Stop reasons whose Converse reply is complete.
ACCEPTED_STOP_REASONS = frozenset({"tool_use", "end_turn", "stop_sequence"})
_AWS_NAME_RE = re.compile(r"[A-Za-z0-9_.:-]{1,100}", re.ASCII)


class ConverseClient(Protocol):
    def converse(self, **kwargs: Any) -> Any: ...


class ClientFactory(Protocol):
    """``make_client``'s shape; the selection call passes ``max_attempts=1``."""

    def __call__(
        self,
        *,
        read_timeout_seconds: float,
        connect_timeout_seconds: float,
        max_attempts: int = ...,
    ) -> ConverseClient: ...


def make_client(
    *,
    read_timeout_seconds: float,
    connect_timeout_seconds: float = CONNECT_TIMEOUT_SECONDS,
    region_name: str | None = None,
    max_attempts: int = MAX_ATTEMPTS,
) -> ConverseClient:
    """A ``bedrock-runtime`` client with standard retries and the given timeouts."""
    config = Config(
        retries={"mode": "standard", "total_max_attempts": max_attempts},
        read_timeout=read_timeout_seconds,
        connect_timeout=connect_timeout_seconds,
    )
    region = region_name or os.environ.get("AWS_REGION") or None
    client: ConverseClient = boto3.client("bedrock-runtime", region_name=region, config=config)
    return client


def aws_error_name(exc: ClientError) -> str:
    """The ADR-009 allowlisted error code of ``exc`` (never its message)."""
    response = exc.response if isinstance(exc.response, dict) else {}
    error = response.get("Error") if isinstance(response.get("Error"), dict) else {}
    raw = error.get("Code") if isinstance(error, dict) else None
    return raw if isinstance(raw, str) and _AWS_NAME_RE.fullmatch(raw) else "unknown"


def _count(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= MAX_USAGE_TOKENS:
        return value
    return None


def response_usage(response: Any) -> tuple[int, int] | None:
    """``(input, output)`` tokens of a Converse response, ``None`` when absent or malformed."""
    usage = response.get("usage") if isinstance(response, dict) else None
    if not isinstance(usage, dict):
        return None
    i, o = _count(usage.get("inputTokens")), _count(usage.get("outputTokens"))
    return (i, o) if i is not None and o is not None else None


def usage_cost(tokens: tuple[int, int] | None, prices: tuple[float, float] | None) -> float | None:
    """USD for ``tokens`` at ``(input, output)`` per-million prices; ``None`` if one is unknown."""
    if tokens is None or prices is None:
        return None
    try:
        value = (tokens[0] * prices[0] + tokens[1] * prices[1]) / 1_000_000
    except OverflowError:  # pragma: no cover - counts are bounded, kept as a guard
        return None
    return round(value, 6) if math.isfinite(value) else None
