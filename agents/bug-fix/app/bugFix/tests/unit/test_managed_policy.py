"""L1 tests for the managed Claude Code policy (TC-180-10, TC-180-11; spec §12, D-51).

The key names are provisional until the S-182 spike pins them against the
installed CLI; when it does, these tests re-run against the spike's keys.

Path rules use Claude Code's ``//`` prefix for an absolute filesystem path.
A single leading ``/`` is resolved relative to the settings file's directory,
so ``Read(/proc/**)`` in ``/etc/claude-code/managed-settings.json`` would
guard ``/etc/claude-code/proc/**`` instead of ``/proc/**``.
"""

from __future__ import annotations

import ipaddress
import json
from pathlib import Path

import pytest

POLICY = Path(__file__).resolve().parents[2] / "managed-settings.json"

REGISTRIES = {"registry.npmjs.org", "registry.yarnpkg.com", "pypi.org", "files.pythonhosted.org"}

DENY_TOOLS = ["Bash(git push:*)", "Bash(gh:*)", "Bash(curl:*)", "Bash(wget:*)", "WebFetch", "WebSearch"]
DENY_PATHS = ["/proc/**", "/etc/claude-code/**", "/work/secrets/**"]


def _policy() -> dict:
    return json.loads(POLICY.read_text())


def _domains() -> list[str]:
    return _policy()["sandbox"]["network"]["allowedDomains"]


def _deny() -> list[str]:
    return _policy()["permissions"]["deny"]


class TestSandbox:
    def test_sandbox_enabled(self):
        assert _policy()["sandbox"]["enabled"] is True

    def test_sandbox_not_escapable(self):
        sb = _policy()["sandbox"]
        assert sb["allowUnsandboxedCommands"] is False
        assert not sb.get("excludedCommands")

    def test_bypass_mode_disabled(self):
        assert _policy()["permissions"]["disableBypassPermissionsMode"] == "disable"

    def test_network_allow_list_is_exactly_the_registries(self):
        domains = _domains()
        assert len(domains) == len(set(domains))
        assert set(domains) == REGISTRIES

    def test_no_local_binding_or_unix_sockets(self):
        net = _policy()["sandbox"]["network"]
        assert net.get("allowLocalBinding", False) is False
        assert not net.get("allowUnixSockets")


class TestDenyRules:
    @pytest.mark.parametrize("rule", DENY_TOOLS)
    def test_tool_denied(self, rule):
        assert rule in _deny()

    @pytest.mark.parametrize("tool", ["Read", "Edit"])
    @pytest.mark.parametrize("path", DENY_PATHS)
    def test_path_denied_as_absolute(self, tool, path):
        assert f"{tool}(/{path})" in _deny(), f"expected {tool}(/{path}) (absolute form)"

    def test_no_relative_form_of_denied_paths(self):
        # The single-slash form is settings-relative and would guard nothing.
        for tool in ("Read", "Edit"):
            for path in DENY_PATHS:
                assert f"{tool}({path})" not in _deny()

    def test_managed_policy_allows_nothing_extra(self):
        # A managed allow rule would widen every repo's settings.
        assert not _policy()["permissions"].get("allow")


class TestNegative:
    @pytest.mark.parametrize("domain", ["github.com", "api.github.com", "objects.githubusercontent.com", "anthropic.com", "localhost"])
    def test_forbidden_hosts_absent(self, domain):
        assert domain not in _domains()

    def test_no_wildcards(self):
        for d in _domains():
            assert "*" not in d, d

    def test_no_cloud_metadata_or_provider_hosts(self):
        for d in _domains():
            assert "amazonaws.com" not in d
            assert not d.startswith("169.254.")

    def test_no_ip_literals(self):
        # Link-local (169.254.0.0/16, the container-credentials and metadata
        # endpoints) and every other IP literal stay out of the allow-list.
        for d in _domains():
            try:
                ipaddress.ip_address(d)
            except ValueError:
                continue
            pytest.fail(f"IP literal in allow-list: {d}")

    def test_policy_carries_no_secret_ids(self):
        text = POLICY.read_text()
        assert "agent-fleet/" not in text
        assert "SECRET" not in text.upper().replace("/WORK/SECRETS", "")
