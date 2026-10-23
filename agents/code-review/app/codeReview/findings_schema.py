"""
The ``submit_review`` output contract (spec §6.3; D-34).

The model returns its review as the input of a forced ``submit_review`` tool
call. Nothing executes: the "tool" is only an output contract the wrapper
validates. This module holds the schema as data, verbatim from spec §6.3.

S-209 adds it because two things need it before the Bedrock adapter exists:
the rubric's categories must equal the schema's ``category`` enum (TC-209-10),
and the budget counts the schema as part of the fixed instructions
(spec §8.4 step 1). S-210 sends it as ``toolConfig`` and adds validation here.

**Validation (S-210).** ``validate_review`` checks a value against
``SUBMIT_REVIEW_SCHEMA`` by walking the schema data, so the constant stays the
single source and the spec §6.3 verbatim tests cover the validator too. It
supports exactly the keywords the schema uses (``type``, ``enum``,
``required``, ``additionalProperties: false``, ``properties``, ``items``,
``maxItems``, ``maxLength``, ``minimum``, ``pattern``); any other keyword in
the schema is a defect (``SchemaError``). No dependency: ``jsonschema`` is not
a sibling dependency, and the schema is small and fixed.

The value is model output and untrusted:

- Cost is linear in the value's size. The recursion follows the schema (depth
  4), never the value: a scalar field holding a 200k-deep list fails its type
  check without descending. ``maxItems`` is checked before any item.
- ``integer`` rejects ``bool`` and ``float`` (``1.0`` too: S-211 compares
  lines as ``int``); ``float`` NaN or Infinity never passes any type here.
- ``pattern`` follows ECMA-262 anchoring: a final ``$`` matches only at the end
  of the string (Python's ``$`` also matches before a final ``\n``), with
  ``re.ASCII``.
- The first violation in document order is reported: required properties in
  schema order, then unexpected properties, then each property in schema
  order. A ``SchemaViolation`` names a path built from schema keys and
  integer indices and a fixed rule text. It never contains the model's text:
  an unexpected key is reported without its name, a bad value without its
  value.

``parse_review_json`` is the fallback mode's strict parse (D-34, DF-21
pinned): the reply must be exactly one JSON value, optionally surrounded by
whitespace. No fence stripping, no extraction from prose, no ``NaN`` or
``Infinity``. Anything else is a ``json`` violation, which the adapter sends
to the repair call.
"""

from __future__ import annotations

import functools
import json
import re
from typing import Any

__all__ = [
    "CATEGORIES",
    "CHECK_STATUSES",
    "MAX_FINDINGS",
    "MAX_REVIEW_JSON_CHARS",
    "SEVERITIES",
    "SUBMIT_REVIEW_SCHEMA",
    "SUBMIT_REVIEW_TOOL",
    "SchemaError",
    "SchemaViolation",
    "parse_review_json",
    "validate_review",
]

SUBMIT_REVIEW_TOOL = "submit_review"
SEVERITIES = ("blocking", "suggestion")
# The rubric's categories (``rubric.md`` v1, PRD FR-20); pinned equal by
# ``tests/unit/test_prompt.py::test_rubric_categories_equal_the_schema_enum``.
CATEGORIES = ("correctness", "edge_case", "maintainability", "intent")
CHECK_STATUSES = ("confirmed", "not_reproduced")
MAX_FINDINGS = 40

SUBMIT_REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["findings", "verifier_checks"],
    "properties": {
        "findings": {
            "type": "array",
            "maxItems": MAX_FINDINGS,
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
                    "severity": {"enum": list(SEVERITIES)},
                    "category": {"enum": list(CATEGORIES)},
                    "file": {"type": "string", "maxLength": 400},
                    "line_start": {"type": "integer", "minimum": 1},
                    "line_end": {"type": "integer", "minimum": 1},
                    "title": {"type": "string", "maxLength": 200},
                    "failure_scenario": {"type": "string", "maxLength": 1500},
                    "consequence": {"type": "string", "maxLength": 500},
                    "rank": {"type": "integer", "minimum": 1},
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
                    "candidate_id": {"type": "string", "pattern": "^V[0-9]+$"},
                    "status": {"enum": list(CHECK_STATUSES)},
                    "reason": {"type": "string", "maxLength": 300},
                },
            },
        },
    },
}


# ---------------------------------------------------------------------------
# Validation (S-210)
# ---------------------------------------------------------------------------

# Longest fallback reply parsed at all. ``maxTokens`` is 16,000, so a real
# reply is far shorter; this only bounds what a misbehaving endpoint can cost.
MAX_REVIEW_JSON_CHARS = 1_000_000

RULE_TYPE = "type"
RULE_REQUIRED = "required"
RULE_ADDITIONAL = "additional"
RULE_ENUM = "enum"
RULE_MAX_ITEMS = "maxItems"
RULE_MAX_LENGTH = "maxLength"
RULE_MINIMUM = "minimum"
RULE_PATTERN = "pattern"
RULE_JSON = "json"

_KNOWN_KEYWORDS = frozenset(
    {
        "type",
        "enum",
        "required",
        "additionalProperties",
        "properties",
        "items",
        "maxItems",
        "maxLength",
        "minimum",
        "pattern",
    }
)
_ROOT = "$"


class SchemaError(Exception):
    """The schema uses a keyword the validator does not implement: a defect."""

    code = "INTERNAL_ERROR"


class SchemaViolation(ValueError):
    """A value fails ``SUBMIT_REVIEW_SCHEMA``.

    ``path`` is ``$``, ``$.findings[3].category`` and so on: schema keys and
    integer indices only. ``rule`` is one of the ``RULE_*`` names. The message
    is ``"<path>: <fixed text>"`` and never contains the value.
    """

    def __init__(self, path: str, rule: str, detail: str) -> None:
        self.path = path
        self.rule = rule
        super().__init__(f"{path}: {detail}")


@functools.cache
def _pattern(source: str) -> re.Pattern[str]:
    """``source`` with ECMA-262 end anchoring: a final unescaped ``$`` is ``\\Z``."""
    if source.endswith("$") and not source.endswith("\\$"):
        source = source[:-1] + "\\Z"
    return re.compile(source, re.ASCII)


def _is_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


_TYPE_CHECKS = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": _is_integer,
}


def _check(value: Any, schema: dict[str, Any], path: str) -> None:
    unknown = set(schema) - _KNOWN_KEYWORDS
    if unknown:
        raise SchemaError(f"unsupported schema keywords at {path}: {sorted(unknown)}")
    # Every enum here is a list of strings; ``in`` on a list never hashes.
    if "enum" in schema and (not isinstance(value, str) or value not in schema["enum"]):
        raise SchemaViolation(path, RULE_ENUM, "is not an allowed value")
    kind = schema.get("type")
    if kind is not None:
        check = _TYPE_CHECKS.get(kind)
        if check is None:
            raise SchemaError(f"unsupported schema type at {path}: {kind!r}")
        if not check(value):
            raise SchemaViolation(
                path, RULE_TYPE, f"must be {'an' if kind[0] in 'aio' else 'a'} {kind}"
            )
    if kind == "object":
        _check_object(value, schema, path)
    elif kind == "array":
        _check_array(value, schema, path)
    elif kind == "string":
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            raise SchemaViolation(
                path, RULE_MAX_LENGTH, f"is longer than {schema['maxLength']} characters"
            )
        if "pattern" in schema and _pattern(schema["pattern"]).search(value) is None:
            raise SchemaViolation(path, RULE_PATTERN, f"does not match {schema['pattern']}")
    elif kind == "integer" and "minimum" in schema and value < schema["minimum"]:
        raise SchemaViolation(path, RULE_MINIMUM, f"is less than {schema['minimum']}")


def _check_object(value: dict[Any, Any], schema: dict[str, Any], path: str) -> None:
    properties: dict[str, Any] = schema.get("properties", {})
    for name in schema.get("required", ()):
        if name not in value:
            raise SchemaViolation(f"{path}.{name}", RULE_REQUIRED, "is required")
    if schema.get("additionalProperties", True) is False:
        for key in value:
            if not isinstance(key, str) or key not in properties:
                raise SchemaViolation(path, RULE_ADDITIONAL, "has an unexpected property")
    for name, sub in properties.items():
        if name in value:
            _check(value[name], sub, f"{path}.{name}")


def _check_array(value: list[Any], schema: dict[str, Any], path: str) -> None:
    if "maxItems" in schema and len(value) > schema["maxItems"]:
        raise SchemaViolation(path, RULE_MAX_ITEMS, f"has more than {schema['maxItems']} items")
    items = schema.get("items")
    if items is not None:
        for k, item in enumerate(value):
            _check(item, items, f"{path}[{k}]")


def validate_review(value: Any) -> dict[str, Any]:
    """Return ``value`` if it satisfies ``SUBMIT_REVIEW_SCHEMA``, else raise ``SchemaViolation``."""
    _check(value, SUBMIT_REVIEW_SCHEMA, _ROOT)
    review: dict[str, Any] = value
    return review


def _reject_constant(_name: str) -> Any:
    raise ValueError("non-finite number")


def parse_review_json(text: str) -> Any:
    """Parse ``text`` as exactly one JSON value (whitespace around it allowed).

    Raises ``SchemaViolation`` (path ``$``, rule ``json``) for anything else:
    a fence, prose before or after, two values, ``NaN``/``Infinity``, nesting
    too deep for the parser, an integer over Python's digit limit, or text
    longer than ``MAX_REVIEW_JSON_CHARS``. The message carries at most the
    character offset, never the text.
    """
    if len(text) > MAX_REVIEW_JSON_CHARS:
        raise SchemaViolation(_ROOT, RULE_JSON, "is not exactly one JSON object (too long)")
    try:
        return json.loads(text, parse_constant=_reject_constant)
    except json.JSONDecodeError as exc:
        raise SchemaViolation(
            _ROOT, RULE_JSON, f"is not exactly one JSON object (char {int(exc.pos)})"
        ) from None
    except (ValueError, RecursionError):
        raise SchemaViolation(_ROOT, RULE_JSON, "is not exactly one JSON object") from None
