"""Security-negative cases for the GitHub App assertion (S-204, TESTING.md).

``credentials.py`` is the agent's only authentication path: it signs an RS256
JWT as the GitHub App and exchanges it for an installation token. The ported
``test_credentials_real_jwt.py`` pins the positive contract. This module pins
the negative half with the real ``jwt`` library (never mocked) so a permissive
signing change cannot stay green:

- the assertion does not verify under a different key (invalid signature);
- a tampered claim set fails verification against the right key;
- the issuer is the App id, so a verifier expecting another issuer rejects it;
- the assertion expires: minted an hour ago, it is rejected as expired now;
- the validity window stays inside GitHub's 10-minute ceiling;
- a GitHub rejection (401) never yields a token.

Only the GitHub HTTP exchange is stubbed.
"""

from __future__ import annotations

import base64
import json
import time
from unittest.mock import MagicMock, patch

import jwt
import pytest
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from credentials import mint_installation_token

APP_ID = 424242
INSTALLATION_ID = 99


def _keypair() -> tuple[str, object]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    return pem, key.public_key()


@pytest.fixture(scope="module")
def signer() -> tuple[str, object]:
    return _keypair()


@pytest.fixture(scope="module")
def other_public_key() -> object:
    return _keypair()[1]


def _mint(pem: str, now: float | None = None) -> str:
    """Mint with the real signer; return the assertion sent to GitHub."""
    with patch("credentials.requests.post") as post:
        resp = MagicMock()
        resp.json.return_value = {"token": "ghs_x"}
        resp.raise_for_status = MagicMock()
        post.return_value = resp
        if now is None:
            mint_installation_token(APP_ID, INSTALLATION_ID, pem)
        else:
            with patch("credentials.time.time", return_value=now):
                mint_installation_token(APP_ID, INSTALLATION_ID, pem)
        header = post.call_args.kwargs["headers"]["Authorization"]
    assert header.startswith("Bearer ")
    return header[len("Bearer ") :]


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def test_assertion_fails_verification_under_a_different_key(signer, other_public_key):
    pem, _ = signer
    assertion = _mint(pem)
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(assertion, other_public_key, algorithms=["RS256"])


def test_tampered_claims_fail_verification(signer):
    pem, public_key = signer
    header, payload, signature = _mint(pem).split(".")
    claims = json.loads(_b64url_decode(payload))
    claims["iss"] = "1"  # impersonate another App
    tampered = ".".join([header, _b64url(json.dumps(claims).encode()), signature])
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(tampered, public_key, algorithms=["RS256"])


def test_assertion_is_rejected_for_a_wrong_issuer(signer):
    pem, public_key = signer
    assertion = _mint(pem)
    assert jwt.decode(assertion, public_key, algorithms=["RS256"], issuer=str(APP_ID))
    with pytest.raises(jwt.InvalidIssuerError):
        jwt.decode(assertion, public_key, algorithms=["RS256"], issuer=str(APP_ID + 1))


def test_assertion_is_not_accepted_under_another_algorithm(signer):
    pem, public_key = signer
    assertion = _mint(pem)
    with pytest.raises(jwt.InvalidAlgorithmError):
        jwt.decode(assertion, public_key, algorithms=["HS256"])


def test_assertion_minted_an_hour_ago_is_expired(signer):
    pem, public_key = signer
    stale = _mint(pem, now=time.time() - 3600)
    with pytest.raises(jwt.ExpiredSignatureError):
        jwt.decode(stale, public_key, algorithms=["RS256"])


def test_validity_window_is_inside_github_ceiling(signer):
    pem, public_key = signer
    now = int(time.time())
    claims = jwt.decode(_mint(pem, now=now), public_key, algorithms=["RS256"])
    assert claims["iat"] <= now
    assert claims["exp"] > now
    # GitHub rejects an App JWT whose exp is more than 10 minutes ahead.
    assert claims["exp"] - now <= 600


def test_github_rejection_never_yields_a_token(signer):
    pem, _ = signer
    resp = MagicMock()
    resp.raise_for_status.side_effect = requests.HTTPError("401 Unauthorized")
    resp.json.return_value = {"token": "ghs_must_not_leak"}
    with (
        patch("credentials.requests.post", return_value=resp),
        pytest.raises(requests.HTTPError),
    ):
        mint_installation_token(APP_ID, INSTALLATION_ID, pem)
    resp.json.assert_not_called()
