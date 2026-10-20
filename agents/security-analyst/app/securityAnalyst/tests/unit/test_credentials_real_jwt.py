"""Real-library JWT signing round-trip for the GitHub App assertion (TC-252-3a).

The existing `test_credentials.py` suite patches `credentials.jwt`, so a breaking
change in `jwt.encode` on a PyJWT upgrade would go undetected (verifier finding
F-1 for issue #252). This module exercises the *real* `credentials.py` signing
path with `jwt` NOT mocked: it generates an RSA key with `cryptography`, calls
`mint_installation_token` (stubbing only the GitHub HTTP exchange), and then
decodes the produced assertion with the matching public key.

It pins the GitHub App JWT contract (RS256 header, string `iss`, integer
`iat`/`exp`, and the exact 600-second validity window) so the audit-driven
PyJWT 2.15.1 upgrade cannot silently change what the agent signs.

See `workstream/archive/test-plan-issue-252-245-244.md` CT-1/CT-2/CT-3 and task 1.5a.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from credentials import CredentialError, mint_installation_token

APP_ID = 123456
INSTALLATION_ID = 7891011


def _rsa_keypair() -> tuple[str, object]:
    """Generate an RSA keypair; return (private PEM str, public key object)."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    return pem, private_key.public_key()


class TestRealJwtSigning:
    """CT-1/CT-2: the real signing path produces a decodable RS256 assertion."""

    @patch("credentials.requests")
    def test_signs_rs256_assertion_decodable_with_public_key(self, mock_requests):
        pem, public_key = _rsa_keypair()

        # Stub only the GitHub HTTP exchange; `jwt` is intentionally real.
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"token": "ghs_installation_token"}
        mock_resp.raise_for_status = MagicMock()
        mock_requests.post.return_value = mock_resp

        token = mint_installation_token(app_id=APP_ID, installation_id=INSTALLATION_ID, pem=pem)
        assert token == "ghs_installation_token"

        # Recover the signed assertion from the Authorization header.
        post_kwargs = mock_requests.post.call_args
        auth_header = post_kwargs.kwargs["headers"]["Authorization"]
        assert auth_header.startswith("Bearer ")
        assertion = auth_header[len("Bearer ") :]

        # Header: alg must be RS256 (the GitHub App requirement).
        header = jwt.get_unverified_header(assertion)
        assert header["alg"] == "RS256"
        assert header["typ"] == "JWT"

        # Verify the signature with the real public key — proves the private
        # PEM actually signed it and PyJWT accepts the RSA backend.
        claims = jwt.decode(assertion, public_key, algorithms=["RS256"])

        # Claim types: iss is a string; iat/exp are integers.
        assert isinstance(claims["iss"], str)
        assert claims["iss"] == str(APP_ID)
        assert isinstance(claims["iat"], int)
        assert isinstance(claims["exp"], int)

        # Validity window: iat = now - 60, exp = now + 540 ⇒ exp - iat == 600.
        assert claims["exp"] - claims["iat"] == 600

    @patch("credentials.requests")
    def test_malformed_pem_is_classified_or_raises(self, mock_requests):
        """CT-3: a malformed PEM must not silently sign; the real `jwt.encode`
        rejects it. The agent surfaces either a classified CredentialError or
        the library error — never a successful token mint."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"token": "should_not_be_reached"}
        mock_resp.raise_for_status = MagicMock()
        mock_requests.post.return_value = mock_resp

        with pytest.raises((CredentialError, Exception)) as exc_info:
            mint_installation_token(
                app_id=APP_ID,
                installation_id=INSTALLATION_ID,
                pem="-----BEGIN RSA PRIVATE KEY-----\nnot-a-real-key\n-----END RSA PRIVATE KEY-----",
            )
        # The GitHub HTTP exchange must never have been reached with a bad key.
        mock_requests.post.assert_not_called()
        assert exc_info.value is not None
