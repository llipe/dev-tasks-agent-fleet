"""DynamoDB outcome store — stamps last_status and last_outcome_url (S-011).

After the pipeline finishes (success or error), the agent stamps its outcome
into the `agent-fleet-config` table so the control plane can read the latest
status without waiting for spans.

Only two attributes are written: `last_status` and `last_outcome_url`.
The item MUST already exist (enforced via ConditionExpression).
Failures are logged but never propagated — the run's actual result is preserved.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

import boto3

# Add the generated contract to the path
_GENERATED_DIR = str(
    Path(__file__).resolve().parent.parent.parent / "packages" / "shared" / "generated"
)
if _GENERATED_DIR not in sys.path:
    sys.path.insert(0, _GENERATED_DIR)

logger = logging.getLogger(__name__)

TABLE_NAME = os.environ.get("TABLE_NAME", "agent-fleet-config")

# Key prefixes from the shared contract
_SUBJECT_PREFIX = "SUBJECT#"
_AGENT_PREFIX = "AGENT#"


def _get_table() -> Any:
    """Get the DynamoDB Table resource. Isolated for testability."""
    dynamodb = boto3.resource("dynamodb")
    return dynamodb.Table(TABLE_NAME)


def _log_error(message: str, **kwargs: object) -> None:
    """Log an error. Isolated for testability."""
    logger.error(message, extra=kwargs)


def stamp_outcome(
    *,
    subject_id: str,
    agent_name: str,
    status: str,
    outcome_url: str,
) -> None:
    """Stamp the pipeline outcome into DynamoDB.

    Uses UpdateItem with a condition expression to ensure the item exists.
    Only writes `last_status` and `last_outcome_url`.

    Args:
        subject_id: Normalized repository identifier (e.g., "owner/repo").
        agent_name: Agent name (e.g., "dep-updater").
        status: Pipeline result status ("success" or "failed").
        outcome_url: PR URL or "" (never None).
    """
    try:
        table = _get_table()
        table.update_item(
            Key={
                "pk": f"{_SUBJECT_PREFIX}{subject_id}",
                "sk": f"{_AGENT_PREFIX}{agent_name}",
            },
            UpdateExpression="SET last_status = :status, last_outcome_url = :url",
            ExpressionAttributeValues={
                ":status": status,
                ":url": outcome_url,
            },
            ConditionExpression="attribute_exists(pk)",
        )
    except Exception as e:
        # Never let a DynamoDB failure mask or change the run's actual result.
        error_type = type(e).__name__
        _log_error(
            f"Failed to stamp outcome to DynamoDB: {error_type}: {e}",
            subject_id=subject_id,
            agent_name=agent_name,
            status=status,
        )
