"""L1 hostile-input tests for ``node.py`` (#471 completion gate).

``engines.node``, ``.nvmrc`` and ``.node-version`` are repository-controlled
text, read from the base commit before anything of the repo runs. Whatever
they hold, :func:`node.select_node` must return a choice or ``None`` (the
named ``NODE_ITEM`` miss), never raise; :func:`node.satisfies` may only raise
:class:`node.RangeError`; and both must stay linear on megabyte inputs.

The elapsed bounds follow TESTING.md's hostile-input rule: at least 3x margin
under ``make test-cov``, on inputs large enough that a quadratic scan misses
the bound by an order of magnitude.
"""

from __future__ import annotations

import contextlib
import json
import time

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from node import NODE_VERSIONS, NodeChoice, RangeError, satisfies, select_node

MB = 1_000_000
BOUND_S = 2.0
# CPython's int-string conversion limit (sys.get_int_max_str_digits default).
OVER_INT_LIMIT = "9" * 4301


class MapReader:
    def __init__(self, files: dict[str, str]) -> None:
        self.files = files

    def read_text(self, path: str) -> str | None:
        return self.files.get(path)


def engines(spec: str, files: dict[str, str] | None = None) -> MapReader:
    tree = {"package.json": json.dumps({"name": "x", "engines": {"node": spec}})}
    tree.update(files or {})
    return MapReader(tree)


# ---------------------------------------------------------------------------
# QA-471-01: a number past CPython's int-digit limit is a RangeError, not ValueError
# ---------------------------------------------------------------------------


def test_satisfies_raises_only_range_error_on_a_huge_number():
    with pytest.raises(RangeError):
        satisfies(NODE_VERSIONS[0], OVER_INT_LIMIT)


@pytest.mark.parametrize(
    "spec", [OVER_INT_LIMIT, f">={OVER_INT_LIMIT}", f"24.{OVER_INT_LIMIT}", f"^{OVER_INT_LIMIT}"]
)
def test_select_node_survives_a_huge_number_in_engines(spec):
    assert select_node(engines(spec)) is not None


@pytest.mark.parametrize("name", [".nvmrc", ".node-version"])
def test_a_huge_number_in_a_version_file_is_ignored(name):
    reader = MapReader({name: OVER_INT_LIMIT})
    assert select_node(reader) == NodeChoice(NODE_VERSIONS[-1], "default")


# ---------------------------------------------------------------------------
# Regex cost: megabyte inputs stay linear
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "spec",
    [
        # Inputs that parse do per-token work, so they are 100k, not 1 MB: still
        # 1e10 steps for a quadratic scan, ~0.2 s linear under coverage.
        "x " * (MB // 20),  # many wildcard comparators: parses, all match
        "||".join([">=30"] * (MB // 60)),  # many unsatisfiable sets
        ">= " * (MB // 3),  # operator-space collapse
        "a" + " " * MB + "-",  # hyphen backtracking over whitespace
        "a - " * (MB // 4) + "a",  # repeated hyphen separators
        "24.0.0-" + "a." * (MB // 2) + "!",  # long prerelease, bad tail
        "v" + "1" * 4000 + "." + "x" * MB,  # long numeric then junk
        "<" * MB,  # bare operators
    ],
    ids=["x", "or", "opspace", "ws-hyphen", "hyphens", "prerelease", "numeric", "ops"],
)
def test_megabyte_engines_node_is_linear(spec):
    started = time.perf_counter()
    choice = select_node(engines(spec))
    elapsed = time.perf_counter() - started
    assert choice is None or choice.version in NODE_VERSIONS
    assert elapsed < BOUND_S, f"{elapsed:.2f}s"


@pytest.mark.parametrize(
    "text", ["v" + "1" * 4000 + ".1" * (MB // 2), " " * MB + "24", "24" + "\n" * MB]
)
def test_megabyte_version_file_is_linear(text):
    started = time.perf_counter()
    choice = select_node(MapReader({".nvmrc": text}))
    elapsed = time.perf_counter() - started
    assert choice is not None and choice.version in NODE_VERSIONS
    assert elapsed < BOUND_S, f"{elapsed:.2f}s"


def test_a_megabyte_package_json_with_a_non_string_engines_is_the_default():
    reader = MapReader({"package.json": json.dumps({"engines": {"node": ["x"] * (MB // 8)}})})
    assert select_node(reader) == NodeChoice(NODE_VERSIONS[-1], "default")


# ---------------------------------------------------------------------------
# Properties (algebraic; no reference implementation of the grammar)
# ---------------------------------------------------------------------------

versions = st.sampled_from(NODE_VERSIONS)
_part = st.one_of(st.integers(0, 40).map(str), st.sampled_from(["x", "X", "*"]))
partials = st.lists(_part, min_size=1, max_size=3).map(".".join)
ops = st.sampled_from(["", "=", "<", "<=", ">", ">=", "~", "~>", "^"])
comparators = st.builds(lambda o, p: o + p, ops, partials)
sets = st.lists(comparators, min_size=1, max_size=4).map(" ".join)


@settings(max_examples=300, deadline=None)
@given(versions, st.text(max_size=200))
def test_satisfies_returns_a_bool_or_raises_range_error(version, spec):
    with contextlib.suppress(RangeError):
        assert satisfies(version, spec) in (True, False)


@settings(max_examples=300, deadline=None)
@given(st.text(max_size=200), st.text(max_size=50), st.text(max_size=50))
def test_select_node_never_raises_on_arbitrary_text(spec, nvmrc, node_version):
    choice = select_node(engines(spec, {".nvmrc": nvmrc, ".node-version": node_version}))
    assert choice is None or choice.version in NODE_VERSIONS


@settings(max_examples=300, deadline=None)
@given(versions, sets, sets)
def test_or_is_union_and_space_is_intersection(version, a, b):
    assert satisfies(version, f"{a} || {b}") == (satisfies(version, a) or satisfies(version, b))
    assert satisfies(version, f"{a} {b}") == (satisfies(version, a) and satisfies(version, b))


@settings(max_examples=200, deadline=None)
@given(versions, versions)
def test_full_version_comparators_order_like_tuples(version, bound):
    key = tuple(int(p) for p in version.split("."))
    other = tuple(int(p) for p in bound.split("."))
    assert satisfies(version, f">={bound}") == (key >= other)
    assert satisfies(version, f"<{bound}") == (key < other)
    assert satisfies(version, f"={bound}") == (key == other)
    assert satisfies(version, f"{bound} - {bound}") == (key == other)


@settings(max_examples=200, deadline=None)
@given(versions, sets)
def test_a_selection_always_satisfies_a_parsed_engines_range(version, spec):
    del version
    choice = select_node(engines(spec))
    if choice is None:
        assert not any(satisfies(v, spec) for v in NODE_VERSIONS)
    else:
        assert satisfies(choice.version, spec)


# ---------------------------------------------------------------------------
# Branches the #471 suite left uncovered
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("version", "spec", "expected"),
    [
        # ^ on a 0 major: the leftmost non-zero part is fixed (node-semver).
        ("0.3.9", "^0.3.1", True),
        ("0.4.0", "^0.3.1", False),
        ("0.0.3", "^0.0.3", True),
        ("0.0.4", "^0.0.3", False),
        ("0.0.9", "^0.0", True),
        ("0.1.0", "^0.0", False),
        ("0.9.0", "^0", True),
        ("1.0.0", "^0", False),
        # A hyphen range whose upper end is a wildcard has no upper bound.
        ("26.12.1", "22 - *", True),
        ("22.23.4", "24 - x", False),
    ],
)
def test_caret_zero_and_open_hyphen(version, spec, expected):
    assert satisfies(version, spec) is expected


def test_node_choice_major():
    assert NodeChoice("24.22.2", "engines.node").major == 24
