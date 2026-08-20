"""LLIPE span attribute emission module (S-010).

Maps pipeline outcomes to OpenTelemetry span attributes using constants
from the generated shared contract. Attributes are set on the current
root span in the worker thread's trace context.

The five pipeline outcomes map to the contract's two-status model:
  success (PR created)   → (success, pr, <url>)
  no_updates             → (success, none, "")
  pr_already_open        → (success, pr, <existing url>)
  tests_failing          → (failed, none, "")
  error (exception)      → (failed, none, "")
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from opentelemetry import trace

# Add the generated contract to the path
_GENERATED_DIR = str(
    Path(__file__).resolve().parent.parent.parent / "packages" / "shared" / "generated"
)
if _GENERATED_DIR not in sys.path:
    sys.path.insert(0, _GENERATED_DIR)

from shared_contract import LLIPE  # noqa: E402


@dataclass(frozen=True)
class RunResult:
    """Mapped pipeline outcome ready for span emission."""

    status: str  # "success" | "failed"
    outcome_type: str  # "pr" | "none"
    outcome_url: str  # URL or "" (never None/absent)


def map_result(pipeline_result: str, *, pr_url: str | None = None) -> RunResult:
    """Map a pipeline outcome string to span attributes.

    Args:
        pipeline_result: One of "success", "no_updates", "pr_already_open",
                        "tests_failing", "error".
        pr_url: The PR URL when available (for success/pr_already_open paths).

    Returns:
        RunResult with the mapped status, outcome_type, and outcome_url.
    """
    if pipeline_result == "success":
        return RunResult(
            status="success",
            outcome_type="pr",
            outcome_url=pr_url or "",
        )
    elif pipeline_result == "no_updates":
        return RunResult(
            status="success",
            outcome_type="none",
            outcome_url="",
        )
    elif pipeline_result == "pr_already_open":
        return RunResult(
            status="success",
            outcome_type="pr",
            outcome_url=pr_url or "",
        )
    elif pipeline_result == "tests_failing":
        return RunResult(
            status="failed",
            outcome_type="none",
            outcome_url="",
        )
    else:
        # "error" or any unknown result → failed
        return RunResult(
            status="failed",
            outcome_type="none",
            outcome_url="",
        )


def emit_span_attributes(*, result: RunResult, subject_id: str) -> None:
    """Set LLIPE attributes on the current root span.

    Uses opentelemetry.trace.get_current_span() to access the span from
    the worker thread's context. The root span must have been propagated
    into the thread via context attachment.

    If the span is not recording (e.g., NoOp span), this is a no-op.

    Args:
        result: The mapped RunResult with status, outcome_type, outcome_url.
        subject_id: The normalized subject ID (e.g., "owner/repo").
    """
    span = trace.get_current_span()
    if not span.is_recording():
        return

    span.set_attribute(LLIPE.SUBJECT_ID, subject_id)
    span.set_attribute(LLIPE.RUN_STATUS, result.status)
    span.set_attribute(LLIPE.OUTCOME_TYPE, result.outcome_type)
    span.set_attribute(LLIPE.OUTCOME_URL, result.outcome_url)
