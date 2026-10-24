# Copied from agents/security-analyst/app/securityAnalyst/credentials.py
# Source commit: 8cfed33b9974f82047b065732ad956936d3fb5d0
# Extended (S-182): `fetch_secret_string`, a generic Secrets Manager read used for
# the Anthropic key and the Projects token (D-50, D-99). Spec §8.1 extends it
# further in later stories: token permissions (D-58).
# Extended (S-186): `TokenContext.app_id`, the fleet App id from the
# `github_installations` row, which marker trust checks against (D-53). A non-int
# or bool `app_id` is a typed `INVALID_APP_ID` error.
# Extended (S-185): the minted token's `permissions` (D-58). `mint_installation`
# returns the token and its permissions, `TokenContext.permissions` carries them,
# and `has_issues_write` is the preflight check. `mint_installation_token` keeps
# the sibling's token-only signature.
"""
Credential resolution — Supabase service role key from Secrets Manager
and GitHub App installation token minting.
"""

from __future__ import annotations

import os
import time
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, NamedTuple

import boto3
import jwt
import requests
from botocore.exceptions import ClientError

from config import SUPABASE_KEY_SECRET_ID, SUPABASE_URL, TOKEN_STALE_THRESHOLD_MINUTES


class CredentialError(Exception):
    """Raised when credential resolution fails."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def _check_app_id(app_id: object) -> int:
    """The App id as a positive ``int``, or ``CredentialError('INVALID_APP_ID')``.

    Marker trust compares it with ``performed_via_github_app.id`` (D-53), so a
    string, float or bool here must fail now, typed, rather than as a
    ``TypeError`` (or a silent mismatch) in ``is_trusted`` later. The message
    names the type only, never the value.
    """
    if isinstance(app_id, bool) or not isinstance(app_id, int) or app_id < 1:
        raise CredentialError(
            "INVALID_APP_ID",
            f"github_installations.app_id must be a positive integer, got {type(app_id).__name__}",
        )
    return app_id


@dataclass
class TokenContext:
    """Holds a minted GitHub installation token with staleness tracking."""

    token: str
    issued_at: float  # time.monotonic()
    installation_id: int
    # The fleet App id (D-53). ``None`` only for a context built by hand.
    app_id: int | None = None
    # The minted token's ``permissions`` object (D-58). ``None`` only for a
    # context built by hand, which therefore fails the ``issues: write`` check.
    permissions: Mapping[str, str] | None = None

    def __post_init__(self) -> None:
        if self.app_id is not None:
            _check_app_id(self.app_id)

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
    try:
        response = sm.get_secret_value(SecretId=sid)
    except ClientError as exc:
        # A Secrets Manager failure (missing secret, access denied, throttling)
        # is a credential-resolution failure — classify it so the entrypoint's
        # `except CredentialError` handler yields a clean terminal chunk rather
        # than letting a raw boto3 exception fall through to UNHANDLED_ERROR
        # (issue #108), mirroring the requests treatment in _get_installation.
        raise CredentialError(
            "SUPABASE_KEY_UNAVAILABLE",
            f"Could not read the Supabase service role key from Secrets Manager "
            f"(secret '{sid}'): {exc}",
        ) from exc
    key = response.get("SecretString")
    if not key:
        raise CredentialError(
            "SUPABASE_KEY_UNAVAILABLE",
            f"Secrets Manager returned no SecretString for the Supabase service "
            f"role key (secret '{sid}')",
        )
    return key


def fetch_secret_string(secret_id: str, code: str = "SECRET_UNAVAILABLE") -> str:
    """Read one SecretString from Secrets Manager (S-182).

    Used for the Anthropic API key and the Projects token. The error names the
    secret id and the AWS error code, never a value; the caller registers the
    returned value in its ``SecretSet`` before using it.
    """
    sm = boto3.client("secretsmanager")
    try:
        response = sm.get_secret_value(SecretId=secret_id)
    except ClientError as exc:
        aws_code = exc.response.get("Error", {}).get("Code", "ClientError")
        raise CredentialError(code, f"Could not read secret '{secret_id}' ({aws_code})") from None
    value = response.get("SecretString")
    if not value:
        raise CredentialError(code, f"Secrets Manager returned no SecretString for '{secret_id}'")
    return value


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
    try:
        resp = requests.get(url, headers=headers, timeout=15)
    except requests.RequestException as exc:
        # A transport failure (DNS/connection/timeout) reaching Supabase is a
        # credential-resolution failure — classify it so the entrypoint's
        # `except CredentialError` handler yields a clean terminal chunk rather
        # than letting a raw requests exception fall through to
        # UNHANDLED_ERROR (issue #106).
        raise CredentialError(
            "SUPABASE_UNREACHABLE",
            f"Could not reach Supabase to resolve installation for org '{org}': {exc}",
        ) from exc
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
    try:
        response = sm.get_secret_value(SecretId=secret_arn)
    except ClientError as exc:
        # Classify a Secrets Manager failure reading the GitHub App PEM as a
        # credential error (issue #108), consistent with fetch_supabase_key.
        raise CredentialError(
            "PEM_UNAVAILABLE",
            f"Could not read the GitHub App private key from Secrets Manager "
            f"(secret '{secret_arn}'): {exc}",
        ) from exc
    pem = response.get("SecretString")
    if not pem:
        raise CredentialError(
            "PEM_UNAVAILABLE",
            f"Secrets Manager returned no SecretString for the GitHub App "
            f"private key (secret '{secret_arn}')",
        )
    return pem


# ---------------------------------------------------------------------------
# Token minting
# ---------------------------------------------------------------------------


class MintedToken(NamedTuple):
    """An installation token and the ``permissions`` GitHub granted it (D-58)."""

    token: str
    permissions: Mapping[str, str]


def _permissions(value: Any) -> Mapping[str, str]:
    """The ``permissions`` object as a read-only ``{name: level}`` map.

    Anything malformed (absent, not an object, non-string entries) is dropped,
    so it reads as "not granted" and fails closed.
    """
    if not isinstance(value, Mapping):
        return MappingProxyType({})
    return MappingProxyType(
        {k: v for k, v in value.items() if isinstance(k, str) and isinstance(v, str)}
    )


def has_issues_write(permissions: object) -> bool:
    """True iff the token was granted ``issues: write`` (D-58)."""
    return isinstance(permissions, Mapping) and permissions.get("issues") == "write"


def mint_installation_token(app_id: int, installation_id: int, pem: str) -> str:
    """The installation token only (the sibling's signature). See :func:`mint_installation`."""
    return mint_installation(app_id, installation_id, pem).token


def mint_installation(app_id: int, installation_id: int, pem: str) -> MintedToken:
    """
    Sign an RS256 JWT as the GitHub App and exchange it for an installation token.

    The JWT is valid for 9 minutes (iat - 60s for clock skew, exp + 540s).
    Returns the token with the ``permissions`` GitHub granted it (D-58).
    """
    now = int(time.time())
    assertion = jwt.encode(
        {"iat": now - 60, "exp": now + 540, "iss": str(app_id)},
        pem,
        algorithm="RS256",
    )
    try:
        resp = requests.post(
            f"https://api.github.com/app/installations/{installation_id}/access_tokens",
            headers={
                "Authorization": f"Bearer {assertion}",
                "Accept": "application/vnd.github+json",
            },
            timeout=30,
        )
    except requests.RequestException as exc:
        # Classify a transport failure reaching GitHub as a credential error
        # (issue #106), consistent with _get_installation.
        raise CredentialError(
            "GITHUB_UNREACHABLE",
            f"Could not reach GitHub to mint installation token: {exc}",
        ) from exc
    resp.raise_for_status()
    payload = resp.json()
    return MintedToken(payload["token"], _permissions(payload.get("permissions")))


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
    app_id = _check_app_id(row.get("app_id"))
    pem = _fetch_pem(row["private_key_secret_arn"])
    minted = mint_installation(app_id, row["installation_id"], pem)
    return TokenContext(
        token=minted.token,
        issued_at=time.monotonic(),
        installation_id=row["installation_id"],
        app_id=app_id,
        permissions=minted.permissions,
    )


def refresh_if_stale(token_ctx: TokenContext, pem: str, app_id: int) -> TokenContext:
    """Re-mint token if >45 min elapsed (req 20)."""
    if token_ctx.is_stale():
        new_token = mint_installation_token(app_id, token_ctx.installation_id, pem)
        return TokenContext(
            token=new_token,
            issued_at=time.monotonic(),
            installation_id=token_ctx.installation_id,
            app_id=token_ctx.app_id,
            permissions=token_ctx.permissions,
        )
    return token_ctx
