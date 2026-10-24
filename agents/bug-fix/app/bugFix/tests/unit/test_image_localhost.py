"""L1 tests for ``localhost`` resolution in the image (S-182 fix round 3).

srt 0.0.81 and the CLI's Bash sandbox hard-code their proxy as
``http://…@localhost:<port>``, and the sandbox's network namespace has no DNS,
so ``localhost`` must come from NSS. On AgentCore ``/etc/hosts`` is empty and
read-only (re-probe 2c), so fix round 2's run-time append can't work. The image
resolves ``localhost`` with ``libnss-myhostname`` (``hosts: files myhostname
dns``) and prefers IPv4 through ``/etc/gai.conf``.

The behaviour is asserted against the built image by ``scripts/image-smoke.sh``
with an empty, read-only ``/etc/hosts`` bind-mounted. These tests pin the
committed Dockerfile and the smoke assertions.
"""

from __future__ import annotations

import re
from pathlib import Path

PKG = Path(__file__).resolve().parents[2]
DOCKERFILE = PKG / "Dockerfile"
SMOKE = PKG / "scripts" / "image-smoke.sh"


def _apt_packages() -> set[str]:
    text = DOCKERFILE.read_text()
    m = re.search(r"apt-get install -y --no-install-recommends(.*?)&&", text, re.DOTALL)
    assert m, "no apt-get install line"
    return set(m.group(1).replace("\\", " ").split())


def _run_lines() -> str:
    """Only the build instructions, without comments."""
    return "\n".join(
        line for line in DOCKERFILE.read_text().splitlines() if not line.lstrip().startswith("#")
    )


class TestDockerfile:
    def test_installs_libnss_myhostname(self):
        assert "libnss-myhostname" in _apt_packages()

    def test_sets_hosts_line_and_fails_the_build_if_not_set(self):
        text = _run_lines()
        assert "/etc/nsswitch.conf" in text
        # Written explicitly, then verified: a grep that fails the RUN if the
        # line isn't exactly myhostname before dns.
        assert re.search(r"grep -qx[E]? .*files myhostname dns.* /etc/nsswitch\.conf", text)

    def test_prefers_ipv4_through_gai_conf(self):
        text = _run_lines()
        assert "precedence ::ffff:0:0/96 100" in text
        assert "/etc/gai.conf" in text

    def test_never_writes_etc_hosts(self):
        # BuildKit bind-mounts /etc/hosts during the build, and AgentCore's is
        # read-only at run time: writing it is never the fix.
        assert not re.search(r">>?\s*/etc/hosts", _run_lines())

    def test_documents_why(self):
        text = DOCKERFILE.read_text()
        assert "read-only" in text
        assert "re-probe 2c" in text


class TestSmokeAssertions:
    def test_simulates_agentcore_with_an_empty_read_only_hosts(self):
        assert "dst=/etc/hosts,readonly" in SMOKE.read_text()

    def test_checks_nss_resolution_and_ipv4_first(self):
        text = SMOKE.read_text()
        assert "getent ahostsv4 localhost" in text
        assert "getaddrinfo" in text
        assert "127.0.0.1" in text

    def test_checks_nsswitch_order_and_gai_conf(self):
        text = SMOKE.read_text()
        assert "files myhostname dns" in text
        assert "/etc/gai.conf" in text

    def test_checks_the_wrapper_preflight(self):
        text = SMOKE.read_text()
        assert "check_localhost()" in text
        assert "ensure_hosts" not in text
