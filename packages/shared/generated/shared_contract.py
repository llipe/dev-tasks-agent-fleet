"""
Generated shared contract module.
DO NOT EDIT — regenerate with: pnpm --filter shared run codegen

Source: packages/shared/src/ (TypeScript Zod schemas)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ─── LLIPE Span Attribute Constants ───────────────────────────────────────────

class LLIPE:
    """Span attribute name constants."""

    SUBJECT_ID: str = "llipe.subject.id"
    RUN_STATUS: str = "llipe.run.status"
    OUTCOME_TYPE: str = "llipe.outcome.type"
    OUTCOME_URL: str = "llipe.outcome.url"


# ─── Span Field Paths ─────────────────────────────────────────────────────────

class SPAN_FIELDS:
    """Span field path mapping for Logs Insights queries."""

    SESSION_ID: str = "resource.attributes.session.id"
    SUBJECT_ID: str = "resource.attributes.llipe.subject.id"
    RUN_STATUS: str = "resource.attributes.llipe.run.status"
    OUTCOME_TYPE: str = "resource.attributes.llipe.outcome.type"
    OUTCOME_URL: str = "resource.attributes.llipe.outcome.url"
    MODEL_ID: str = "attributes.gen_ai.request.model"
    TOKENS_IN: str = "attributes.gen_ai.usage.input_tokens"
    TOKENS_OUT: str = "attributes.gen_ai.usage.output_tokens"
    DURATION_NS: str = "duration"
    SERVICE_NAME: str = "resource.attributes.service.name"
    TIMESTAMP: str = "startTimeUnixNano"


# ─── Status Derivation Constants ───────────────────────────────────────────────

DEFAULT_MAX_LIFETIME_MS: int = 28800000
TERMINATION_GRACE_MS: int = 300000


# ─── DynamoDB Item Schemas ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class SubjectMetaItem:
    """Generated from Zod schema. Do not edit manually."""

    pk: str
    sk: str
    subject_id: str
    created_at: str


@dataclass(frozen=True)
class SubjectAgentItem:
    """Generated from Zod schema. Do not edit manually."""

    pk: str
    sk: str
    enabled: bool
    params: dict[str, Any] = field(default_factory=dict)
    last_session_id: str | None = None
    last_run_at: str | None = None
    last_status: str | None = None
    last_outcome_url: str | None = None


@dataclass(frozen=True)
class AgentConfigItem:
    """Generated from Zod schema. Do not edit manually."""

    pk: str
    sk: str
    agent_name: str
    domain: str | None = None
    default_params: dict[str, Any] = field(default_factory=dict)


# ─── Agent Params Schemas ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class Params_dep_updater:
    """Generated from Zod schema. Do not edit manually."""

    allow_fixes: bool
    max_fix_attempts: int


# ─── Params Schema Registry ───────────────────────────────────────────────────

PARAMS_SCHEMAS: dict[str, type] = {
    "dep-updater": Params_dep_updater,
}
