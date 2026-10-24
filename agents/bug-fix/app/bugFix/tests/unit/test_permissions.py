"""L1: the minted token's ``permissions`` (S-185 AC1; TC-185-01; D-58)."""

from __future__ import annotations

from types import MappingProxyType
from unittest.mock import MagicMock, patch

import pytest

from credentials import (
    CredentialError,
    MintedToken,
    PermissionMissing,
    TokenContext,
    has_issues_write,
    mint_installation,
    mint_installation_token,
    refresh_if_stale,
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


def _mint_response(payload, status=201):
    resp = MagicMock()
    resp.status_code = status
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


# ---------------------------------------------------------------------------
# QA 6: a failed mint is a CredentialError; a refresh re-checks issues: write
# ---------------------------------------------------------------------------

JWT = "eyJhbGciOiJSUzI1NiJ9.signed.assertion"


@patch("credentials.jwt")
@patch("credentials.requests")
class TestMintFailures:
    @pytest.mark.parametrize("status", [301, 302, 307, 400, 401, 403, 404, 422, 500, 503])
    def test_a_non_2xx_mint_is_a_credential_error(self, mock_requests, mock_jwt, status):
        import requests as real_requests

        mock_jwt.encode.return_value = JWT
        mock_requests.RequestException = real_requests.RequestException
        resp = _mint_response({"message": f"Bad credentials {JWT}", "token": "ghs_x"}, status)
        resp.raise_for_status.side_effect = real_requests.HTTPError(f"{status} for {JWT}")
        mock_requests.post.return_value = resp
        with pytest.raises(CredentialError) as exc:
            mint_installation(1, 2, "pem")
        assert not isinstance(exc.value, real_requests.HTTPError)
        assert exc.value.code == "TOKEN_MINT_FAILED"
        assert exc.value.error_code == "CREDENTIALS_UNAVAILABLE"
        assert str(status) in str(exc.value)
        assert JWT not in str(exc.value) and "Bad credentials" not in str(exc.value)

    def test_the_mint_never_follows_a_redirect(self, mock_requests, mock_jwt):
        mock_jwt.encode.return_value = JWT
        mock_requests.post.return_value = _mint_response({"token": "ghs_x"})
        mint_installation(1, 2, "pem")
        assert mock_requests.post.call_args.kwargs["allow_redirects"] is False

    @pytest.mark.parametrize(
        "payload", [ValueError("no json"), [], {"token": ""}, {"token": 7}, {}]
    )
    def test_a_mint_body_without_a_token_is_a_credential_error(
        self, mock_requests, mock_jwt, payload
    ):
        mock_jwt.encode.return_value = JWT
        resp = _mint_response(None)
        if isinstance(payload, Exception):
            resp.json.side_effect = payload
        else:
            resp.json.return_value = payload
        mock_requests.post.return_value = resp
        with pytest.raises(CredentialError) as exc:
            mint_installation(1, 2, "pem")
        assert exc.value.code == "TOKEN_MINT_FAILED"


def _stale(permissions):
    return TokenContext(
        token="ghs_old", issued_at=0.0, installation_id=20, app_id=10, permissions=permissions
    )


@patch("credentials.mint_installation")
class TestRefreshRechecksPermissions:
    def test_the_refreshed_token_carries_its_own_permissions(self, mock_mint):
        granted = MappingProxyType({"issues": "write", "contents": "write"})
        mock_mint.return_value = MintedToken("ghs_new", granted)
        with patch("credentials.time.monotonic", return_value=10_000.0):
            new = refresh_if_stale(_stale({"issues": "write"}), "pem", 10)
        assert new.token == "ghs_new"
        assert new.permissions is granted

    @pytest.mark.parametrize("granted", [{}, {"issues": "read"}, {"contents": "write"}])
    def test_a_refreshed_token_without_issues_write_is_permission_missing(self, mock_mint, granted):
        mock_mint.return_value = MintedToken("ghs_new", MappingProxyType(granted))
        with (
            patch("credentials.time.monotonic", return_value=10_000.0),
            pytest.raises(PermissionMissing) as exc,
        ):
            refresh_if_stale(_stale({"issues": "write"}), "pem", 10)
        assert isinstance(exc.value, CredentialError)
        assert exc.value.error_code == "GITHUB_PERMISSION_MISSING"
        assert "ghs_new" not in str(exc.value)

    def test_a_fresh_token_is_not_reminted(self, mock_mint):
        with patch("credentials.time.monotonic", return_value=1.0):
            ctx = _stale({"issues": "write"})
            assert refresh_if_stale(ctx, "pem", 10) is ctx
        mock_mint.assert_not_called()


@patch("credentials.requests")
@pytest.mark.parametrize("status", [301, 302, 307])
def test_the_installation_lookup_never_follows_a_redirect(mock_requests, status):
    from credentials import _get_installation

    resp = _mint_response([{"app_id": 1}], status)
    mock_requests.get.return_value = resp
    with pytest.raises(CredentialError) as exc:
        _get_installation("org", "https://sb", "sb_secret_key")
    assert mock_requests.get.call_args.kwargs["allow_redirects"] is False
    assert exc.value.error_code == "CREDENTIALS_UNAVAILABLE"
    assert "sb_secret_key" not in str(exc.value)
