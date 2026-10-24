"""
Typed run params (spec §5.2 v2.0; S-184; D-82, D-93, D-102).

``parse_params`` turns the AgentCore payload's ``params`` into a frozen
:class:`Params`. It enforces the same types and bounds as the seeded
``params_schema``, because a direct invoke bypasses the panel's Ajv check
(D-82). It also applies the seed-equal defaults for the budgets, caps and
status names, because the panel's Ajv runs with ``useDefaults: false``, so a
webhook-started run carries only ``issue_number`` and ``trigger_comment_id``.

- ``issue_number`` is the only required key. It has no default (D-93).
- ``trigger_comment_id`` and ``project`` are optional and default to ``None``.
  The agent never invents a ``project``; board detection handles its absence
  (D-102).
- Unknown keys are ignored and never read. A stale payload therefore can't
  bring back behaviour that issue mode removed (FR-3, D-93).

A missing ``issue_number`` raises :class:`MissingRequiredParam`; a type or
bounds violation raises :class:`InvalidParam`. Both name the key and never the
value, and S-185 turns either into refusal ``invalid_params``. Keys are checked
in schema order, so the reported key is deterministic.

The bounds below mirror the contract fixture
``tests/fixtures/contract/params_schema.json``. The panel's L2.5 test proves the
seed equals that fixture, and this package's tests prove ``DEFAULTS`` and the
bounds equal it too, so changing one side alone fails a test (CT-06, CT-21).
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

# Seed-equal defaults (spec §5.2 v2.0). Checked against the seed by CT-21.
DEFAULTS: Mapping[str, int | str] = MappingProxyType(
    {
        "status_in_progress": "In progress",
        "status_in_review": "In review",
        "status_ready": "Ready",
        "max_turns": 40,
        "cli_timeout_minutes": 30,
        "run_budget_minutes": 55,
        "max_code_files": 10,
        "max_code_lines": 400,
    }
)

# (minimum, maximum or None) per integer key, in schema order.
_INT_BOUNDS: Mapping[str, tuple[int, int | None]] = MappingProxyType(
    {
        "issue_number": (1, None),
        "trigger_comment_id": (1, None),
        "max_turns": (5, 100),
        "cli_timeout_minutes": (5, 45),
        "run_budget_minutes": (10, 55),
        "max_code_files": (1, 50),
        "max_code_lines": (10, 2000),
    }
)

_STATUS_KEYS: tuple[str, ...] = ("status_in_progress", "status_in_review", "status_ready")
_STATUS_MIN_LEN = 1
_STATUS_MAX_LEN = 100

# Schema pattern ``^[A-Za-z0-9-]{1,39}/[1-9][0-9]{0,6}$``, matched with
# ``fullmatch``: Python's ``$`` would also match before a trailing newline.
_PROJECT = re.compile(r"[A-Za-z0-9-]{1,39}/[1-9][0-9]{0,6}")

# Every key, in schema order.
_ORDER: tuple[str, ...] = (
    "issue_number",
    "trigger_comment_id",
    "project",
    *_STATUS_KEYS,
    "max_turns",
    "cli_timeout_minutes",
    "run_budget_minutes",
    "max_code_files",
    "max_code_lines",
)

# The schema's keys, in schema order. S-185 names one in an ``invalid_params``
# refusal, so the reply's key always comes from this closed set (D-104).
SCHEMA_KEYS: tuple[str, ...] = _ORDER


class ParamsError(ValueError):
    """The payload ``params`` are invalid. Names the key, never the value."""

    def __init__(self, key: str, reason: str) -> None:
        self.key = key
        self.reason = reason
        super().__init__(f"{key} {reason}")

    def __repr__(self) -> str:
        return f"{type(self).__name__}(key={self.key!r}, reason={self.reason!r})"


class MissingRequiredParam(ParamsError):
    """A required key (``issue_number``) is absent."""


class InvalidParam(ParamsError):
    """A key has the wrong type or is outside the schema's bounds."""


@dataclass(frozen=True)
class Params:
    issue_number: int
    trigger_comment_id: int | None
    project: str | None
    status_in_progress: str
    status_in_review: str
    status_ready: str
    max_turns: int
    cli_timeout_minutes: int
    run_budget_minutes: int
    max_code_files: int
    max_code_lines: int


def _integer(key: str, value: object) -> int:
    lo, hi = _INT_BOUNDS[key]
    # JSON Schema ``integer``: an int or an integral float, never a bool.
    if isinstance(value, bool):
        raise InvalidParam(key, "must be an integer")
    if isinstance(value, float):
        if not (math.isfinite(value) and value.is_integer()):
            raise InvalidParam(key, "must be an integer")
        value = int(value)
    if not isinstance(value, int):
        raise InvalidParam(key, "must be an integer")
    if value < lo or (hi is not None and value > hi):
        bound = f"at least {lo}" if hi is None else f"between {lo} and {hi}"
        raise InvalidParam(key, f"must be {bound}")
    return value


def _status(key: str, value: object) -> str:
    if not isinstance(value, str):
        raise InvalidParam(key, "must be a string")
    if not _STATUS_MIN_LEN <= len(value) <= _STATUS_MAX_LEN:
        raise InvalidParam(key, f"must be {_STATUS_MIN_LEN} to {_STATUS_MAX_LEN} characters long")
    return value


def _project(value: object) -> str:
    if not isinstance(value, str) or _PROJECT.fullmatch(value) is None:
        raise InvalidParam("project", "must be a Projects v2 board as owner/number")
    return value


def _check(key: str, value: object) -> int | str:
    if key in _INT_BOUNDS:
        return _integer(key, value)
    if key == "project":
        return _project(value)
    return _status(key, value)


def parse_params(raw: object) -> Params:
    """Validate the payload ``params`` and apply the seed-equal defaults.

    Raises :class:`MissingRequiredParam` or :class:`InvalidParam`.
    """
    if not isinstance(raw, Mapping):
        raise InvalidParam("params", "must be an object")
    if "issue_number" not in raw:
        raise MissingRequiredParam("issue_number", "is required")

    values: dict[str, Any] = {}
    for key in _ORDER:
        if key in raw:
            values[key] = _check(key, raw[key])
        else:
            values[key] = DEFAULTS.get(key)
    return Params(**values)
