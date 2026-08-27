"""
Credential resolution — Supabase service role key from Secrets Manager
and GitHub App installation token minting.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

import boto3
import jwt
import requests

from config import SUPABASE_KEY_SECRET_ID, SUPABASE_URL, TOKEN_STALE_THRESHOLD_MINUTES


class CredentialError(Exception):
    """Raised when credential resolution fails."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


@dataclass
class TokenContext:
    """Holds a minted GitHub installation token with staleness tracking."""

    token: str
    issued_at: float  # time.monotonic()
    installation_id: int

    def is_stale(self, threshold_minutes: float = TOKEN_STALE_THRESHOLD_MINUTES) -> bool:
        """Return True if the token has been alive longer than threshold."""
        return (time.monotonic() - self.issued_at) > threshold_minutes * 60


# ---------------------------------------------------------------------------
# Supabase service role key
# ---------------------------------------------------------------------------


def fetch_supabase_key(secret_id: str | None = None) -> str:
    """Read the Supabase service role key from AWS Secrets Manager."""
    sid = secret_id or SUPABASE_KEY_SECRET_ID
    sm = boto3.client("secretsmanager")
    response = sm.get_secret_value(SecretId=sid)
    return response["SecretString"]


# ---------------------------------------------------------------------------
# GitHub App installation lookup via PostgREST
# ---------------------------------------------------------------------------


def _get_installation(org: str, supabase_url: str, supabase_key: str) -> dict:
    """
    Query PostgREST for the github_installations row matching the org.

    Returns the row dict with app_id, installation_id, private_key_secret_arn.
    Raises CredentialError('NO_INSTALLATION', ...) if not found or disabled.
    """
    url = (
        f"{supabase_url}/rest/v1/github_installations"
        f"?github_org_slug=eq.{org}&is_enabled=eq.true"
        f"&select=app_id,installation_id,private_key_secret_arn"
    )
    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Accept": "application/json",
    }
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()

    rows = resp.json()
    if not rows:
        raise CredentialError(
            "NO_INSTALLATION",
            f"No enabled github_installations row for org '{org}'",
        )
    return rows[0]


# ---------------------------------------------------------------------------
# PEM fetch
# ---------------------------------------------------------------------------


def _fetch_pem(secret_arn: str) -> str:
    """Read the GitHub App private key PEM from Secrets Manager."""
    sm = boto3.client("secretsmanager")
    response = sm.get_secret_value(SecretId=secret_arn)
    return response["SecretString"]


# ---------------------------------------------------------------------------
# Token minting
# ---------------------------------------------------------------------------


def mint_installation_token(app_id: int, installation_id: int, pem: str) -> str:
    """
    Sign an RS256 JWT as the GitHub App and exchange it for an installation token.

    The JWT is valid for 9 minutes (iat - 60s for clock skew, exp + 540s).
    """
    now = int(time.time())
    assertion = jwt.encode(
        {"iat": now - 60, "exp": now + 540, "iss": str(app_id)},
        pem,
        algorithm="RS256",
    )
    resp = requests.post(
        f"https://api.github.com/app/installations/{installation_id}/access_tokens",
        headers={
            "Authorization": f"Bearer {assertion}",
            "Accept": "application/vnd.github+json",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["token"]


# ---------------------------------------------------------------------------
# High-level resolution
# ---------------------------------------------------------------------------


def resolve_github_credentials(
    org: str,
    supabase_url: str | None = None,
    supabase_key: str | None = None,
) -> TokenContext:
    """
    Full credential resolution flow:
      1. Query github_installations via PostgREST for the org
      2. Fetch PEM from Secrets Manager
      3. Sign JWT, exchange for installation token
      4. Return TokenContext
    """
    url = supabase_url or SUPABASE_URL
    key = supabase_key or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

    row = _get_installation(org, url, key)
    pem = _fetch_pem(row["private_key_secret_arn"])
    token = mint_installation_token(row["app_id"], row["installation_id"], pem)
    return TokenContext(
        token=token,
        issued_at=time.monotonic(),
        installation_id=row["installation_id"],
    )


def refresh_if_stale(
    token_ctx: TokenContext, pem: str, app_id: int
) -> TokenContext:
    """Re-mint token if >45 min elapsed (req 20)."""
    if token_ctx.is_stale():
        new_token = mint_installation_token(app_id, token_ctx.installation_id, pem)
        return TokenContext(
            token=new_token,
            issued_at=time.monotonic(),
            installation_id=token_ctx.installation_id,
        )
    return token_ctx
