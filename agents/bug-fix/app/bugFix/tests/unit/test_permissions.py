"""L1: the minted token's ``permissions`` (S-185 AC1; TC-185-01; D-58)."""

from __future__ import annotations

from types import MappingProxyType
from unittest.mock import MagicMock, patch

import pytest

from credentials import (
    MintedToken,
    TokenContext,
    has_issues_write,
    mint_installation,
    mint_installation_token,
    resolve_github_credentials,
)


class TestHasIssuesWrite:
    def test_issues_write_passes(self):
        assert has_issues_write({"issues": "write", "metadata": "read"}) is True

    @pytest.mark.parametrize(
        "permissions",
        [
            {},
            {"issues": "read"},
            {"issues": "WRITE"},
            {"issues": "admin"},
            {"issues": None},
            {"issues": ["write"]},
            {"pull_requests": "write"},
            None,
            [],
            "issues:write",
        ],
    )
    def test_anything_else_fails(self, permissions):
        assert has_issues_write(permissions) is False


def _mint_response(payload):
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


@patch("credentials.jwt")
@patch("credentials.requests")
class TestMintInstallation:
    def test_returns_the_token_and_its_permissions(self, mock_requests, mock_jwt):
        mock_jwt.encode.return_value = "jwt"
        mock_requests.post.return_value = _mint_response(
            {"token": "ghs_x", "permissions": {"issues": "write", "contents": "write"}}
        )
        minted = mint_installation(1, 2, "pem")
        assert minted == MintedToken("ghs_x", {"issues": "write", "contents": "write"})
        assert isinstance(minted.permissions, MappingProxyType)

    @pytest.mark.parametrize("permissions", [None, "write", ["issues"], 7])
    def test_a_missing_or_malformed_permissions_object_is_empty(
        self, mock_requests, mock_jwt, permissions
    ):
        mock_jwt.encode.return_value = "jwt"
        payload = {"token": "ghs_x"}
        if permissions is not None:
            payload["permissions"] = permissions
        mock_requests.post.return_value = _mint_response(payload)
        minted = mint_installation(1, 2, "pem")
        assert dict(minted.permissions) == {}
        assert has_issues_write(minted.permissions) is False

    def test_non_string_permission_values_are_dropped(self, mock_requests, mock_jwt):
        mock_jwt.encode.return_value = "jwt"
        mock_requests.post.return_value = _mint_response(
            {"token": "ghs_x", "permissions": {"issues": "write", "checks": 3, 4: "read"}}
        )
        assert dict(mint_installation(1, 2, "pem").permissions) == {"issues": "write"}

    def test_the_legacy_helper_still_returns_only_the_token(self, mock_requests, mock_jwt):
        mock_jwt.encode.return_value = "jwt"
        mock_requests.post.return_value = _mint_response(
            {"token": "ghs_x", "permissions": {"issues": "write"}}
        )
        assert mint_installation_token(1, 2, "pem") == "ghs_x"


@patch("credentials.mint_installation")
@patch("credentials._fetch_pem")
@patch("credentials._get_installation")
def test_resolve_returns_the_permissions(mock_get, mock_pem, mock_mint):
    mock_get.return_value = {"app_id": 7, "installation_id": 9, "private_key_secret_arn": "arn"}
    mock_pem.return_value = "pem"
    mock_mint.return_value = MintedToken("ghs_x", MappingProxyType({"issues": "write"}))
    ctx = resolve_github_credentials("org", "https://sb", "key")
    assert isinstance(ctx, TokenContext)
    assert ctx.token == "ghs_x"
    assert has_issues_write(ctx.permissions)


def test_a_hand_built_context_has_no_permissions():
    ctx = TokenContext(token="t", issued_at=0.0, installation_id=1)
    assert ctx.permissions is None
    assert has_issues_write(ctx.permissions) is False


@pytest.mark.parametrize(
    "permissions",
    [
        {"issues": "write "},
        {"issues": " write"},
        {"issues": "Write"},
        {"issues": "writ"},
        {"issues": "read,write"},
        {"Issues": "write"},
        {"issues ": "write"},
        {"issues": b"write"},
        {"issues": 1},
        {"issues": True},
        MappingProxyType({}),
    ],
)
def test_issues_write_is_an_exact_match(permissions):
    """QA gate (S-185, D-58): only the exact pair ``issues: write`` passes."""
    assert has_issues_write(permissions) is False


def test_a_read_only_mapping_with_issues_write_passes():
    assert has_issues_write(MappingProxyType({"issues": "write"})) is True
