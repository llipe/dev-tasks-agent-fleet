"""L1 tests for ``node.py``: the Node.js versions the image ships, the
``engines.node`` range check and the per-repo selection.

A target repo pins Node through ``engines.node`` and pnpm enforces it on a
frozen install (``ERR_PNPM_UNSUPPORTED_ENGINE``). The image ships several
Node majors side by side; the wrapper picks one from the base commit, before
anything of the repo runs, and puts its ``bin`` first on ``fixer``'s PATH.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import node
from node import (
    DEFAULT_NODE,
    NODE_ROOT,
    NODE_VERSIONS,
    NodeChoice,
    RangeError,
    bin_dir,
    satisfies,
    select_node,
)

PKG = Path(__file__).resolve().parents[2]
DOCKERFILE = PKG / "Dockerfile"


class MapReader:
    def __init__(self, files: dict[str, str]) -> None:
        self.files = files

    def read_text(self, path: str) -> str | None:
        return self.files.get(path)


def repo(engines: object = None, **files: str) -> MapReader:
    data: dict = {"name": "x", "version": "1.0.0"}
    if engines is not None:
        data["engines"] = {"node": engines}
    tree = {"package.json": json.dumps(data)}
    tree.update({k.replace("_", "."): v for k, v in files.items()})
    return MapReader(tree)


# ---------------------------------------------------------------------------
# The shipped set
# ---------------------------------------------------------------------------


class TestShippedVersions:
    def test_three_majors_full_versions_ascending(self):
        majors = [int(v.split(".")[0]) for v in NODE_VERSIONS]
        assert majors == sorted(set(majors)) == [22, 24, 26]
        for v in NODE_VERSIONS:
            assert re.fullmatch(r"\d+\.\d+\.\d+", v), v

    def test_default_is_shipped(self):
        assert DEFAULT_NODE in NODE_VERSIONS

    def test_bin_dir_is_under_the_root_by_major(self):
        assert NODE_ROOT == "/opt/node"
        assert bin_dir("24.22.2") == "/opt/node/24/bin"

    def test_bin_dir_refuses_an_unshipped_version(self):
        with pytest.raises(ValueError):
            bin_dir("18.0.0")

    def test_dockerfile_installs_exactly_the_shipped_versions(self):
        text = DOCKERFILE.read_text()
        m = re.search(r'^ARG NODE_VERSIONS="([^"]+)"', text, re.MULTILINE)
        assert m, "no ARG NODE_VERSIONS"
        assert tuple(m.group(1).split()) == NODE_VERSIONS
        m = re.search(r"^ARG NODE_DEFAULT=(\S+)", text, re.MULTILINE)
        assert m and m.group(1) == DEFAULT_NODE

    def test_dockerfile_pins_a_sha256_per_version(self):
        text = DOCKERFILE.read_text()
        for v in NODE_VERSIONS:
            assert re.search(
                rf"\b[0-9a-f]{{64}}\s+node-v{re.escape(v)}-linux-arm64\.tar\.gz", text
            ), v

    def test_the_refusal_phrase_names_the_shipped_majors(self):
        from refusal import REPO_GATE_PHRASES
        from toolchain import NODE_ITEM

        majors = [v.split(".")[0] for v in NODE_VERSIONS]
        named = ", ".join(majors[:-1]) + " or " + majors[-1]
        assert f"must accept Node {named})" in REPO_GATE_PHRASES[NODE_ITEM]

    def test_dockerfile_no_longer_uses_nodesource(self):
        assert "nodesource" not in DOCKERFILE.read_text().lower()


# ---------------------------------------------------------------------------
# satisfies: the node-semver range grammar engines.node uses
# ---------------------------------------------------------------------------


class TestSatisfies:
    @pytest.mark.parametrize(
        ("version", "spec", "expected"),
        [
            # The failing run: >=24.21.0 <25
            ("24.22.2", ">=24.21.0 <25", True),
            ("26.12.1", ">=24.21.0 <25", False),
            ("24.20.0", ">=24.21.0 <25", False),
            # Primitives
            ("24.22.2", ">=24", True),
            ("22.23.4", ">22.23.4", False),
            ("22.23.4", "<=22.23.4", True),
            ("22.23.4", "=22.23.4", True),
            ("22.23.4", "22.23.4", True),
            ("22.23.4", "v22.23.4", True),
            ("22.23.4", "22.23.3", False),
            # X-ranges and partials
            ("24.22.2", "24", True),
            ("24.22.2", "24.x", True),
            ("24.22.2", "24.22", True),
            ("24.22.2", "24.21.x", False),
            ("24.22.2", "*", True),
            ("24.22.2", "", True),
            ("24.22.2", "x", True),
            ("24.22.2", ">=24.x", True),
            ("24.22.2", "<24", False),
            ("24.22.2", "<=24", True),
            ("24.22.2", ">24", False),
            ("26.12.1", ">24", True),
            # Caret and tilde
            ("24.22.2", "^24.1.0", True),
            ("26.12.1", "^24.1.0", False),
            ("24.22.2", "^24", True),
            ("24.22.2", "~24.22.0", True),
            ("24.23.0", "~24.22.0", False),
            ("24.22.2", "~24", True),
            # Hyphen ranges
            ("24.22.2", "22 - 24", True),
            ("26.12.1", "22 - 24", False),
            ("24.22.2", "22.0.0 - 24.10.0", False),
            # Unions
            ("22.23.4", "^20 || ^22", True),
            ("26.12.1", "^20 || ^22", False),
            ("26.12.1", "18.x || 20.x || >=22", True),
            # Spacing variants npm accepts
            ("24.22.2", ">= 24.21.0 < 25", True),
            ("24.22.2", "  >=24  ", True),
            # A prerelease bound sits below its release
            ("24.0.0", ">=24.0.0-rc.1", True),
            ("24.22.2", "<24.0.0-rc.1", False),
        ],
    )
    def test_table(self, version, spec, expected):
        assert satisfies(version, spec) is expected

    @pytest.mark.parametrize(
        "spec",
        ["latest", "lts/*", "node", ">=abc", "24.a", ">>24", "1.2.3.4", "24 -"],
    )
    def test_unparseable_raises(self, spec):
        with pytest.raises(RangeError):
            satisfies("24.22.2", spec)


# ---------------------------------------------------------------------------
# select_node
# ---------------------------------------------------------------------------


V22, V24, V26 = NODE_VERSIONS


class TestSelectNode:
    def test_the_failing_run_picks_24(self):
        choice = select_node(repo(">=24.21.0 <25"))
        assert choice == NodeChoice(V24, "engines.node")

    def test_no_engines_is_the_default(self):
        assert select_node(repo()) == NodeChoice(DEFAULT_NODE, "default")

    def test_no_package_json_is_the_default(self):
        assert select_node(MapReader({})) == NodeChoice(DEFAULT_NODE, "default")

    def test_the_default_wins_when_it_satisfies(self):
        assert select_node(repo(">=22")).version == DEFAULT_NODE

    def test_otherwise_the_highest_satisfying_version(self):
        assert select_node(repo("^22 || ^24")).version == V24

    def test_nothing_satisfies_is_none(self):
        assert select_node(repo(">=30")) is None
        assert select_node(repo("^18")) is None

    @pytest.mark.parametrize("engines", [42, ["24"], {"node": "24"}, True])
    def test_a_non_string_engines_node_is_ignored(self, engines):
        assert select_node(repo(engines)) == NodeChoice(DEFAULT_NODE, "default")

    def test_an_unparseable_range_falls_back_to_the_default(self):
        choice = select_node(repo("lts/*"))
        assert choice == NodeChoice(DEFAULT_NODE, "default (engines.node not parsed)")

    def test_malformed_package_json_is_the_default(self):
        assert select_node(MapReader({"package.json": "{"})).version == DEFAULT_NODE

    @pytest.mark.parametrize("name", [".nvmrc", ".node-version"])
    @pytest.mark.parametrize("text", ["24\n", "v24.22.2\n", "24.1.0", " v24 "])
    def test_a_version_file_picks_its_major(self, name, text):
        reader = repo()
        reader.files[name] = text
        assert select_node(reader) == NodeChoice(V24, name)

    def test_nvmrc_comes_before_node_version(self):
        reader = repo()
        reader.files[".nvmrc"] = "22"
        reader.files[".node-version"] = "24"
        assert select_node(reader) == NodeChoice(V22, ".nvmrc")

    def test_a_version_file_never_overrides_engines(self):
        reader = repo(">=24.21.0 <25")
        reader.files[".nvmrc"] = "22"
        assert select_node(reader) == NodeChoice(V24, "engines.node")

    def test_a_version_file_narrows_within_engines(self):
        reader = repo(">=22")
        reader.files[".nvmrc"] = "22"
        assert select_node(reader) == NodeChoice(V22, ".nvmrc")

    @pytest.mark.parametrize("text", ["lts/*", "node", "18", "", "x" * 5000])
    def test_an_unusable_version_file_is_ignored(self, text):
        reader = repo()
        reader.files[".nvmrc"] = text
        assert select_node(reader) == NodeChoice(DEFAULT_NODE, "default")

    def test_module_has_no_project_imports(self):
        # node.py is a leaf: sandbox.py imports it, so it imports nothing back.
        src = Path(node.__file__).read_text()
        imports = re.findall(r"^(?:from|import) (\w+)", src, re.MULTILINE)
        assert set(imports) <= {"__future__", "json", "re", "dataclasses", "collections", "typing"}
