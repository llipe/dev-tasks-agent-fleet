"""Tests for GitHub credential resolution and the bot committer identity.

Covers the PAT → GitHub App migration (issue #56):

- ``get_github_token`` branch selection: PAT secret vs GitHub App secret
- ``_installation_token`` JWT claims, RS256 signing, token extraction
- HTTP error propagation from the installation-token exchange
- The env-configurable committer identity used for agent commits

No network calls are made: ``requests.post`` is always patched. No key material
is committed — the RSA key below is generated in-process per test session and
never written to disk.
"""

import json
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import jwt
import pytest
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

import main

# ─────────────────────────────────────────────────────────────────
# Throwaway key material, generated in-process
# ─────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def rsa_keypair() -> tuple[str, str]:
    """A throwaway 2048-bit RSA keypair as (private_pem, public_pem).

    Generated at test time so no key material is ever committed. 2048 bits is
    the minimum GitHub accepts and keeps generation fast.
    """
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = (
        key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private_pem, public_pem


def app_secret(private_pem: str) -> dict[str, str]:
    return {
        "app_id": "123456",
        "installation_id": "7891011",
        "private_key": private_pem,
    }


def secretsmanager_returning(payload: dict[str, Any]) -> MagicMock:
    """A boto3 secretsmanager client stub whose GetSecretValue returns payload."""
    client = MagicMock()
    client.get_secret_value.return_value = {"SecretString": json.dumps(payload)}
    return client


def token_response(token: str = "ghs_installationtoken") -> MagicMock:  # noqa: S107
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"token": token, "expires_at": "2026-01-28T11:00:00Z"}
    return resp


# ─────────────────────────────────────────────────────────────────
# get_github_token — branch selection
# ─────────────────────────────────────────────────────────────────


class TestGetGithubTokenBranchSelection:
    """A secret carrying `token` is a PAT; anything else is App credentials."""

    def test_pat_secret_returns_token_verbatim(self) -> None:
        client = secretsmanager_returning({"token": "ghp_classicpat"})
        with patch("main.boto3.client", return_value=client):
            assert main.get_github_token() == "ghp_classicpat"

    def test_pat_branch_never_calls_github(self) -> None:
        client = secretsmanager_returning({"token": "ghp_classicpat"})
        with (
            patch("main.boto3.client", return_value=client),
            patch("main.requests.post") as mock_post,
        ):
            main.get_github_token()
        mock_post.assert_not_called()

    def test_app_secret_exchanges_for_an_installation_token(
        self, rsa_keypair: tuple[str, str]
    ) -> None:
        private_pem, _ = rsa_keypair
        client = secretsmanager_returning(app_secret(private_pem))
        with (
            patch("main.boto3.client", return_value=client),
            patch("main.requests.post", return_value=token_response()) as mock_post,
        ):
            assert main.get_github_token() == "ghs_installationtoken"
        mock_post.assert_called_once()

    def test_reads_the_secret_id_from_module_config(self) -> None:
        client = secretsmanager_returning({"token": "ghp_x"})
        with patch("main.boto3.client", return_value=client):
            main.get_github_token()
        client.get_secret_value.assert_called_once_with(SecretId=main.SECRET_ID)

    def test_default_secret_id_is_the_pat_secret(self) -> None:
        """Cutover ordering: `dep-agent/github-app` does not exist until the
        runbook has been followed, so the code default must stay the PAT secret.
        A local or CLI invocation without GITHUB_SECRET_ID keeps working, and
        rollback is a single env-var flip.
        """
        source = Path(main.__file__).read_text()
        assert 'os.environ.get("GITHUB_SECRET_ID", "dep-agent/github-pat")' in source


# ─────────────────────────────────────────────────────────────────
# _installation_token
# ─────────────────────────────────────────────────────────────────


class TestInstallationToken:
    """JWT assertion shape, signing algorithm and response handling."""

    def test_assertion_is_signed_rs256_and_verifies_with_the_public_key(
        self, rsa_keypair: tuple[str, str]
    ) -> None:
        private_pem, public_pem = rsa_keypair
        with patch("main.requests.post", return_value=token_response()) as mock_post:
            main._installation_token(app_secret(private_pem))

        assertion = mock_post.call_args.kwargs["headers"]["Authorization"].removeprefix("Bearer ")
        assert jwt.get_unverified_header(assertion)["alg"] == "RS256"
        # Decoding with the matching public key proves the signature is real.
        claims = jwt.decode(assertion, public_pem, algorithms=["RS256"])
        assert claims["iss"] == "123456"

    def test_claims_are_backdated_and_within_githubs_ten_minute_limit(
        self, rsa_keypair: tuple[str, str]
    ) -> None:
        """GitHub rejects a JWT whose iat is in the future relative to its clock,
        and any exp more than 10 minutes ahead."""
        private_pem, public_pem = rsa_keypair
        before = int(time.time())
        with patch("main.requests.post", return_value=token_response()) as mock_post:
            main._installation_token(app_secret(private_pem))
        after = int(time.time())

        assertion = mock_post.call_args.kwargs["headers"]["Authorization"].removeprefix("Bearer ")
        claims = jwt.decode(assertion, public_pem, algorithms=["RS256"])

        assert claims["iat"] <= before - 60 + 1
        assert claims["exp"] - claims["iat"] == 600
        assert claims["exp"] <= after + 540 + 1

    def test_requests_the_installation_specific_endpoint(
        self, rsa_keypair: tuple[str, str]
    ) -> None:
        private_pem, _ = rsa_keypair
        with patch("main.requests.post", return_value=token_response()) as mock_post:
            main._installation_token(app_secret(private_pem))

        url = mock_post.call_args.args[0]
        assert url == "https://api.github.com/app/installations/7891011/access_tokens"

    def test_sends_the_github_json_accept_header_and_a_timeout(
        self, rsa_keypair: tuple[str, str]
    ) -> None:
        private_pem, _ = rsa_keypair
        with patch("main.requests.post", return_value=token_response()) as mock_post:
            main._installation_token(app_secret(private_pem))

        kwargs = mock_post.call_args.kwargs
        assert kwargs["headers"]["Accept"] == "application/vnd.github+json"
        # An unbounded request would hang the pipeline until the runtime's
        # maxLifetime rather than failing fast.
        assert kwargs["timeout"] == 30

    def test_extracts_only_the_token_field(self, rsa_keypair: tuple[str, str]) -> None:
        private_pem, _ = rsa_keypair
        with patch("main.requests.post", return_value=token_response("ghs_specific")):
            assert main._installation_token(app_secret(private_pem)) == "ghs_specific"

    def test_http_error_propagates(self, rsa_keypair: tuple[str, str]) -> None:
        """A 401 from a revoked App key must surface, not be swallowed into an
        empty token that then fails as an opaque git clone error."""
        private_pem, _ = rsa_keypair
        resp = MagicMock()
        resp.raise_for_status.side_effect = requests.HTTPError("401 Client Error")
        with (
            patch("main.requests.post", return_value=resp),
            pytest.raises(requests.HTTPError),
        ):
            main._installation_token(app_secret(private_pem))

    def test_missing_installation_id_raises_keyerror(self, rsa_keypair: tuple[str, str]) -> None:
        private_pem, _ = rsa_keypair
        secret = app_secret(private_pem)
        del secret["installation_id"]
        with (
            patch("main.requests.post", return_value=token_response()),
            pytest.raises(KeyError),
        ):
            main._installation_token(secret)

    def test_malformed_private_key_raises(self) -> None:
        with (
            patch("main.requests.post", return_value=token_response()),
            pytest.raises(Exception),  # noqa: B017 - pyjwt/cryptography error type varies
        ):
            main._installation_token(
                {
                    "app_id": "1",
                    "installation_id": "2",
                    "private_key": "-----BEGIN PRIVATE KEY-----\nnope\n-----END PRIVATE KEY-----",
                }
            )


# ─────────────────────────────────────────────────────────────────
# Committer identity
# ─────────────────────────────────────────────────────────────────


class TestCommitterIdentity:
    """The bot identity must be env-configurable.

    After the GitHub App cutover, commits attributed to the App must use
    ``<app-slug>[bot]`` and the App's numeric bot user email, or GitHub shows the
    commits as authored by an unrelated account. The current PAT-era values stay
    as defaults so nothing changes until the env vars are set.
    """

    def test_defaults_match_the_current_pat_era_identity(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            assert main.resolve_committer_identity() == (
                "dep-update-agent",
                "dep-update-agent@users.noreply.github.com",
            )

    def test_env_vars_override_both_fields(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "GIT_COMMITTER_NAME": "dep-updater[bot]",
                "GIT_COMMITTER_EMAIL": "123456+dep-updater[bot]@users.noreply.github.com",
            },
            clear=True,
        ):
            assert main.resolve_committer_identity() == (
                "dep-updater[bot]",
                "123456+dep-updater[bot]@users.noreply.github.com",
            )

    def test_each_field_overrides_independently(self) -> None:
        with patch.dict("os.environ", {"GIT_COMMITTER_NAME": "only-name"}, clear=True):
            name, email = main.resolve_committer_identity()
        assert name == "only-name"
        assert email == "dep-update-agent@users.noreply.github.com"

    def test_blank_values_fall_back_to_the_defaults(self) -> None:
        with patch.dict(
            "os.environ",
            {"GIT_COMMITTER_NAME": "   ", "GIT_COMMITTER_EMAIL": ""},
            clear=True,
        ):
            assert main.resolve_committer_identity() == (
                "dep-update-agent",
                "dep-update-agent@users.noreply.github.com",
            )

    def test_clone_repo_configures_the_resolved_identity(self) -> None:
        with (
            patch.object(main, "_run") as mock_run,
            patch.dict(
                "os.environ",
                {
                    "GIT_COMMITTER_NAME": "dep-updater[bot]",
                    "GIT_COMMITTER_EMAIL": "123456+dep-updater[bot]@users.noreply.github.com",
                },
                clear=True,
            ),
        ):
            main.clone_repo("https://github.com/o/r", "/tmp/ws", "tok")

        configured = [c.args[0] for c in mock_run.call_args_list if "config" in c.args[0]]
        assert ["git", "config", "user.name", "dep-updater[bot]"] in configured
        assert [
            "git",
            "config",
            "user.email",
            "123456+dep-updater[bot]@users.noreply.github.com",
        ] in configured

    def test_clone_repo_still_scrubs_the_token_from_the_remote(self) -> None:
        """Regression guard: the identity change must not disturb the credential
        scrub that keeps the token out of .git/config."""
        with patch.object(main, "_run") as mock_run, patch.dict("os.environ", {}, clear=True):
            main.clone_repo("https://github.com/o/r", "/tmp/ws", "tok")

        commands = [c.args[0] for c in mock_run.call_args_list]
        assert ["git", "remote", "set-url", "origin", "https://github.com/o/r"] in commands
        clone = next(c for c in commands if "clone" in c)
        assert "x-access-token:tok@" in " ".join(clone)
