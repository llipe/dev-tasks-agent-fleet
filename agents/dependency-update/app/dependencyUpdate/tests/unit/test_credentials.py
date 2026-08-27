"""Unit tests for credentials module."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from credentials import (
    CredentialError,
    TokenContext,
    _fetch_pem,
    _get_installation,
    fetch_supabase_key,
    mint_installation_token,
    refresh_if_stale,
    resolve_github_credentials,
)


# ---------------------------------------------------------------------------
# TokenContext
# ---------------------------------------------------------------------------


class TestTokenContext:
    def test_not_stale_when_fresh(self):
        ctx = TokenContext(token="ghs_abc", issued_at=time.monotonic(), installation_id=1)
        assert ctx.is_stale() is False

    def test_stale_after_threshold(self):
        # Simulate token issued 46 minutes ago
        ctx = TokenContext(
            token="ghs_abc",
            issued_at=time.monotonic() - (46 * 60),
            installation_id=1,
        )
        assert ctx.is_stale() is True

    def test_not_stale_at_boundary(self):
        # Just under threshold should not be stale
        ctx = TokenContext(
            token="ghs_abc",
            issued_at=time.monotonic() - (44 * 60 + 59),
            installation_id=1,
        )
        assert ctx.is_stale() is False

    def test_custom_threshold(self):
        ctx = TokenContext(
            token="ghs_abc",
            issued_at=time.monotonic() - (10 * 60),
            installation_id=1,
        )
        assert ctx.is_stale(threshold_minutes=5) is True
        assert ctx.is_stale(threshold_minutes=15) is False


# ---------------------------------------------------------------------------
# fetch_supabase_key
# ---------------------------------------------------------------------------


class TestFetchSupabaseKey:
    @patch("credentials.boto3")
    def test_reads_from_secrets_manager(self, mock_boto3):
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.get_secret_value.return_value = {"SecretString": "sbp_key123"}

        result = fetch_supabase_key("my-secret-id")

        mock_boto3.client.assert_called_once_with("secretsmanager")
        mock_client.get_secret_value.assert_called_once_with(SecretId="my-secret-id")
        assert result == "sbp_key123"

    @patch("credentials.boto3")
    def test_uses_default_secret_id(self, mock_boto3):
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.get_secret_value.return_value = {"SecretString": "key"}

        fetch_supabase_key()

        mock_client.get_secret_value.assert_called_once_with(
            SecretId="agent-fleet/prod/SUPABASE_SERVICE_ROLE_KEY"
        )


# ---------------------------------------------------------------------------
# _get_installation
# ---------------------------------------------------------------------------


class TestGetInstallation:
    @patch("credentials.requests")
    def test_returns_first_row(self, mock_requests):
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {"app_id": 123, "installation_id": 456, "private_key_secret_arn": "arn:aws:sm:..."}
        ]
        mock_resp.raise_for_status = MagicMock()
        mock_requests.get.return_value = mock_resp

        row = _get_installation("myorg", "https://proj.supabase.co", "sbp_key")

        assert row["app_id"] == 123
        assert row["installation_id"] == 456
        # Verify correct URL was called
        call_args = mock_requests.get.call_args
        assert "github_org_slug=eq.myorg" in call_args[0][0]
        assert "is_enabled=eq.true" in call_args[0][0]

    @patch("credentials.requests")
    def test_raises_no_installation_when_empty(self, mock_requests):
        mock_resp = MagicMock()
        mock_resp.json.return_value = []
        mock_resp.raise_for_status = MagicMock()
        mock_requests.get.return_value = mock_resp

        with pytest.raises(CredentialError) as exc_info:
            _get_installation("noorg", "https://proj.supabase.co", "sbp_key")

        assert exc_info.value.code == "NO_INSTALLATION"
        assert "noorg" in exc_info.value.message


# ---------------------------------------------------------------------------
# mint_installation_token
# ---------------------------------------------------------------------------


class TestMintInstallationToken:
    @patch("credentials.requests")
    @patch("credentials.jwt")
    def test_happy_path(self, mock_jwt, mock_requests):
        mock_jwt.encode.return_value = "signed.jwt.assertion"
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"token": "ghs_installation_token"}
        mock_resp.raise_for_status = MagicMock()
        mock_requests.post.return_value = mock_resp

        token = mint_installation_token(app_id=100, installation_id=200, pem="-----BEGIN RSA...")

        mock_jwt.encode.assert_called_once()
        encode_args = mock_jwt.encode.call_args
        payload = encode_args[0][0]
        assert payload["iss"] == "100"
        assert "exp" in payload
        assert "iat" in payload
        assert encode_args[0][1] == "-----BEGIN RSA..."
        assert encode_args[1]["algorithm"] == "RS256"

        mock_requests.post.assert_called_once()
        post_url = mock_requests.post.call_args[0][0]
        assert "/installations/200/access_tokens" in post_url

        assert token == "ghs_installation_token"


# ---------------------------------------------------------------------------
# refresh_if_stale
# ---------------------------------------------------------------------------


class TestRefreshIfStale:
    @patch("credentials.mint_installation_token")
    def test_does_not_refresh_when_fresh(self, mock_mint):
        ctx = TokenContext(token="old", issued_at=time.monotonic(), installation_id=1)
        result = refresh_if_stale(ctx, pem="pem", app_id=100)
        mock_mint.assert_not_called()
        assert result is ctx

    @patch("credentials.mint_installation_token")
    def test_refreshes_when_stale(self, mock_mint):
        mock_mint.return_value = "new_token"
        ctx = TokenContext(
            token="old", issued_at=time.monotonic() - (46 * 60), installation_id=1
        )
        result = refresh_if_stale(ctx, pem="pem", app_id=100)
        mock_mint.assert_called_once_with(100, 1, "pem")
        assert result.token == "new_token"
        assert result.installation_id == 1


# ---------------------------------------------------------------------------
# resolve_github_credentials (integration of the above)
# ---------------------------------------------------------------------------


class TestResolveGithubCredentials:
    @patch("credentials.mint_installation_token")
    @patch("credentials._fetch_pem")
    @patch("credentials._get_installation")
    def test_happy_path(self, mock_get_inst, mock_fetch_pem, mock_mint):
        mock_get_inst.return_value = {
            "app_id": 10,
            "installation_id": 20,
            "private_key_secret_arn": "arn:aws:sm:us-east-1:123:secret/key",
        }
        mock_fetch_pem.return_value = "-----BEGIN RSA PRIVATE KEY-----\n..."
        mock_mint.return_value = "ghs_resolved"

        ctx = resolve_github_credentials("myorg", "https://sb.co", "key123")

        mock_get_inst.assert_called_once_with("myorg", "https://sb.co", "key123")
        mock_fetch_pem.assert_called_once_with("arn:aws:sm:us-east-1:123:secret/key")
        mock_mint.assert_called_once_with(10, 20, "-----BEGIN RSA PRIVATE KEY-----\n...")
        assert ctx.token == "ghs_resolved"
        assert ctx.installation_id == 20
