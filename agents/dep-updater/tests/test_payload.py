"""Tests for the control-plane payload envelope (S-009).

Verifies:
- 9.8: Envelope parsing; normalization equivalence with TS over shared fixture
- 9.9: Params validation accept/reject; unknown key rejected not stripped
- 9.10: Missing session_id; missing repo; params null vs {}
- 9.11: Integration test — end-to-end invocation with control-plane-shaped payload
- 9.12: CLI invocation still works via prompt shim
"""

import json
import sys
from pathlib import Path
from typing import Any

import pytest

# Add parent so payload module can be imported
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class TestEnvelopeParsing:
    """9.8: Envelope parsing; normalization equivalence with TS over shared fixture."""

    def test_parse_valid_envelope(self) -> None:
        """A valid control-plane envelope is parsed correctly."""
        from payload import parse_payload

        raw: dict[str, Any] = {
            "session_id": "dep-updater__owner-repo__2025-01-27T10-00-00Z",
            "repo": "owner/repo",
            "params": {"allow_fixes": True, "max_fix_attempts": 3},
        }
        result = parse_payload(raw)
        assert result.session_id == "dep-updater__owner-repo__2025-01-27T10-00-00Z"
        assert result.repo == "owner/repo"
        assert result.clone_url == "https://github.com/owner/repo"
        assert result.params == {"allow_fixes": True, "max_fix_attempts": 3}

    def test_normalization_equivalence_with_shared_fixture(self) -> None:
        """Python normalize_subject_id matches TS results via shared fixture."""
        fixtures_path = (
            Path(__file__).resolve().parent.parent.parent.parent
            / "packages"
            / "shared"
            / "fixtures"
            / "subject-ids.json"
        )
        fixtures = json.loads(fixtures_path.read_text())

        from payload import parse_payload

        for case in fixtures:
            raw: dict[str, Any] = {
                "session_id": "test-session",
                "repo": case["input"],
                "params": {},
            }
            result = parse_payload(raw)
            assert result.repo == case["expected"], (
                f"normalize({case['input']!r}) = {result.repo!r}, expected {case['expected']!r}"
            )

    def test_clone_url_derived_from_normalized_repo(self) -> None:
        """clone_url is built from the normalized repo, not the raw input."""
        from payload import parse_payload

        raw: dict[str, Any] = {
            "session_id": "test-session",
            "repo": "https://github.com/OWNER/REPO.git",
            "params": {},
        }
        result = parse_payload(raw)
        assert result.repo == "owner/repo"
        assert result.clone_url == "https://github.com/owner/repo"

    def test_repo_url_alias_for_repo(self) -> None:
        """Backward compat: repo_url is accepted as an alias for repo."""
        from payload import parse_payload

        raw: dict[str, Any] = {
            "session_id": "test-session",
            "repo_url": "https://github.com/owner/repo",
            "params": {},
        }
        result = parse_payload(raw)
        assert result.repo == "owner/repo"
        assert result.clone_url == "https://github.com/owner/repo"


class TestParamsValidation:
    """9.9: Params validation accept/reject; unknown key rejected not stripped."""

    def test_valid_params_accepted(self) -> None:
        """Valid params within schema pass validation."""
        from payload import parse_payload

        raw: dict[str, Any] = {
            "session_id": "test-session",
            "repo": "owner/repo",
            "params": {"allow_fixes": True, "max_fix_attempts": 3},
        }
        result = parse_payload(raw)
        assert result.params["allow_fixes"] is True
        assert result.params["max_fix_attempts"] == 3

    def test_unknown_key_rejected_not_stripped(self) -> None:
        """Unknown params key raises PayloadError, not silently stripped."""
        from payload import PayloadError, parse_payload

        raw: dict[str, Any] = {
            "session_id": "test-session",
            "repo": "owner/repo",
            "params": {"allow_fixes": True, "max_fix_attempts": 3, "evil_key": True},
        }
        with pytest.raises(PayloadError, match="evil_key"):
            parse_payload(raw)

    def test_wrong_type_rejected(self) -> None:
        """Wrong type for a known key raises PayloadError."""
        from payload import PayloadError, parse_payload

        raw: dict[str, Any] = {
            "session_id": "test-session",
            "repo": "owner/repo",
            "params": {"allow_fixes": True, "max_fix_attempts": "three"},
        }
        with pytest.raises(PayloadError, match="max_fix_attempts"):
            parse_payload(raw)

    def test_max_fix_attempts_below_minimum_rejected(self) -> None:
        """max_fix_attempts below 1 raises PayloadError."""
        from payload import PayloadError, parse_payload

        raw: dict[str, Any] = {
            "session_id": "test-session",
            "repo": "owner/repo",
            "params": {"allow_fixes": True, "max_fix_attempts": 0},
        }
        with pytest.raises(PayloadError, match="max_fix_attempts"):
            parse_payload(raw)

    def test_max_fix_attempts_above_maximum_rejected(self) -> None:
        """max_fix_attempts above 5 raises PayloadError."""
        from payload import PayloadError, parse_payload

        raw: dict[str, Any] = {
            "session_id": "test-session",
            "repo": "owner/repo",
            "params": {"allow_fixes": True, "max_fix_attempts": 6},
        }
        with pytest.raises(PayloadError, match="max_fix_attempts"):
            parse_payload(raw)

    def test_allow_fixes_wrong_type_rejected(self) -> None:
        """allow_fixes as non-boolean raises PayloadError."""
        from payload import PayloadError, parse_payload

        raw: dict[str, Any] = {
            "session_id": "test-session",
            "repo": "owner/repo",
            "params": {"allow_fixes": "yes", "max_fix_attempts": 3},
        }
        with pytest.raises(PayloadError, match="allow_fixes"):
            parse_payload(raw)


class TestMissingFields:
    """9.10: Missing session_id; missing repo; params null vs {}."""

    def test_missing_session_id_raises(self) -> None:
        """Missing session_id raises PayloadError with clear message."""
        from payload import PayloadError, parse_payload

        raw: dict[str, Any] = {
            "repo": "owner/repo",
            "params": {},
        }
        with pytest.raises(PayloadError, match="session_id"):
            parse_payload(raw)

    def test_missing_repo_raises(self) -> None:
        """Missing repo (and no repo_url) raises PayloadError with clear message."""
        from payload import PayloadError, parse_payload

        raw: dict[str, Any] = {
            "session_id": "test-session",
            "params": {},
        }
        with pytest.raises(PayloadError, match="repo"):
            parse_payload(raw)

    def test_params_null_uses_defaults(self) -> None:
        """params: null → all defaults applied."""
        from payload import parse_payload

        raw: dict[str, Any] = {
            "session_id": "test-session",
            "repo": "owner/repo",
            "params": None,
        }
        result = parse_payload(raw)
        assert result.params == {"allow_fixes": True, "max_fix_attempts": 3}

    def test_params_empty_dict_uses_defaults(self) -> None:
        """params: {} → all defaults applied."""
        from payload import parse_payload

        raw: dict[str, Any] = {
            "session_id": "test-session",
            "repo": "owner/repo",
            "params": {},
        }
        result = parse_payload(raw)
        assert result.params == {"allow_fixes": True, "max_fix_attempts": 3}

    def test_params_missing_uses_defaults(self) -> None:
        """params key missing → all defaults applied."""
        from payload import parse_payload

        raw: dict[str, Any] = {
            "session_id": "test-session",
            "repo": "owner/repo",
        }
        result = parse_payload(raw)
        assert result.params == {"allow_fixes": True, "max_fix_attempts": 3}

    def test_partial_params_fills_defaults(self) -> None:
        """Partial params merges with defaults."""
        from payload import parse_payload

        raw: dict[str, Any] = {
            "session_id": "test-session",
            "repo": "owner/repo",
            "params": {"allow_fixes": False},
        }
        result = parse_payload(raw)
        assert result.params == {"allow_fixes": False, "max_fix_attempts": 3}


class TestPromptShim:
    """9.5/9.12: Preserve the prompt-unwrapping CLI shim."""

    def test_prompt_unwrap_with_json_string(self) -> None:
        """CLI shim: payload wrapped in prompt key is unwrapped."""
        from payload import parse_payload

        inner = json.dumps(
            {
                "session_id": "cli-session",
                "repo": "owner/repo",
                "params": {"allow_fixes": True, "max_fix_attempts": 2},
            }
        )
        raw: dict[str, Any] = {"prompt": inner}
        result = parse_payload(raw)
        assert result.session_id == "cli-session"
        assert result.repo == "owner/repo"
        assert result.params["max_fix_attempts"] == 2

    def test_prompt_unwrap_with_repo_url_key(self) -> None:
        """CLI shim supports legacy repo_url in wrapped payload."""
        from payload import parse_payload

        inner = json.dumps(
            {
                "session_id": "cli-session",
                "repo_url": "https://github.com/owner/repo",
            }
        )
        raw: dict[str, Any] = {"prompt": inner}
        result = parse_payload(raw)
        assert result.repo == "owner/repo"
        assert result.clone_url == "https://github.com/owner/repo"

    def test_direct_payload_not_unwrapped(self) -> None:
        """When repo is present directly, prompt key is not used for unwrapping."""
        from payload import parse_payload

        raw: dict[str, Any] = {
            "session_id": "direct-session",
            "repo": "owner/repo",
            "prompt": "some other value",  # Should be ignored
        }
        result = parse_payload(raw)
        assert result.session_id == "direct-session"


class TestIntegration:
    """9.11: Integration test — end-to-end invocation with control-plane-shaped payload."""

    def test_full_control_plane_payload(self) -> None:
        """End-to-end: control-plane sends full payload with all fields."""
        from payload import parse_payload

        raw: dict[str, Any] = {
            "session_id": "dep-updater__myorg-myrepo__2025-01-27T10-00-00Z",
            "repo": "myorg/myrepo",
            "params": {
                "allow_fixes": True,
                "max_fix_attempts": 5,
            },
        }
        result = parse_payload(raw)
        assert result.session_id == "dep-updater__myorg-myrepo__2025-01-27T10-00-00Z"
        assert result.repo == "myorg/myrepo"
        assert result.clone_url == "https://github.com/myorg/myrepo"
        assert result.params["allow_fixes"] is True
        assert result.params["max_fix_attempts"] == 5

    def test_control_plane_payload_with_uppercase_repo(self) -> None:
        """Repo is normalized even when the orchestrator passes mixed case."""
        from payload import parse_payload

        raw: dict[str, Any] = {
            "session_id": "dep-updater__MyOrg-MyRepo__2025-01-27T10-00-00Z",
            "repo": "MyOrg/MyRepo",
            "params": {},
        }
        result = parse_payload(raw)
        assert result.repo == "myorg/myrepo"
        assert result.clone_url == "https://github.com/myorg/myrepo"

    def test_control_plane_payload_minimal(self) -> None:
        """Minimal valid payload from orchestrator — only required fields."""
        from payload import parse_payload

        raw: dict[str, Any] = {
            "session_id": "dep-updater__owner-repo__2025-01-27T10-00-00Z",
            "repo": "owner/repo",
        }
        result = parse_payload(raw)
        assert result.session_id == "dep-updater__owner-repo__2025-01-27T10-00-00Z"
        assert result.repo == "owner/repo"
        assert result.params == {"allow_fixes": True, "max_fix_attempts": 3}
