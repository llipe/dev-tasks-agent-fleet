"""
Configuration — environment variable reads and constants.
"""

from __future__ import annotations

import os

# --- Supabase ---
SUPABASE_URL: str = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY_SECRET_ID: str = os.environ.get(
    "SUPABASE_KEY_SECRET_ID", "agent-fleet/prod/SUPABASE_SERVICE_ROLE_KEY"
)

# --- AWS / Model ---
MODEL_ID: str = os.environ.get("MODEL_ID", "us.anthropic.claude-sonnet-4-6")

# --- Timeouts (seconds) ---
TEST_TIMEOUT: int = int(os.environ.get("TEST_TIMEOUT", "600"))
TOOL_COMMAND_TIMEOUT: int = int(os.environ.get("TOOL_COMMAND_TIMEOUT", "180"))

# --- Agent behaviour ---
DEFAULT_FIX_MODE: str = "llm_fix"
DEFAULT_MAX_FIX_ATTEMPTS: int = 3
MAX_FIX_ATTEMPTS_CEILING: int = 5
DEFAULT_FAIL_ON_FINDINGS: bool = False

# --- Token refresh ---
TOKEN_STALE_THRESHOLD_MINUTES: float = 45.0
