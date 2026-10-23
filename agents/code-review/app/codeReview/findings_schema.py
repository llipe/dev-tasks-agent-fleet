"""
The ``submit_review`` output contract (spec §6.3; D-34).

The model returns its review as the input of a forced ``submit_review`` tool
call. Nothing executes: the "tool" is only an output contract the wrapper
validates. This module holds the schema as data, verbatim from spec §6.3.

S-209 adds it because two things need it before the Bedrock adapter exists:
the rubric's categories must equal the schema's ``category`` enum (TC-209-10),
and the budget counts the schema as part of the fixed instructions
(spec §8.4 step 1). S-210 sends it as ``toolConfig`` and adds validation here.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "CATEGORIES",
    "CHECK_STATUSES",
    "MAX_FINDINGS",
    "SEVERITIES",
    "SUBMIT_REVIEW_SCHEMA",
    "SUBMIT_REVIEW_TOOL",
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
