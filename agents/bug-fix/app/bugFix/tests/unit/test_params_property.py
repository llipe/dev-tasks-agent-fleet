"""RT-06: property-based differential test of ``parse_params`` (S-184 AC4; D-82).

A small reference oracle reads the contract fixture (spec §5.2 v2.0) and
decides, per generated ``params``, whether it is valid and which key fails
first in schema order. ``parse_params`` must agree on every example, accept
every valid input with the seed-equal defaults, and ignore unknown keys.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from params import InvalidParam, MissingRequiredParam, parse_params

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "contract" / "params_schema.json"
SCHEMA: dict[str, Any] = json.loads(FIXTURE.read_text())
PROPS: dict[str, dict[str, Any]] = SCHEMA["properties"]
LEGACY = ["select_labels", "assignee", "foo", "__probe"]


def _oracle_ok(prop: dict[str, Any], v: Any) -> bool:
    if prop["type"] == "integer":
        if isinstance(v, bool) or not isinstance(v, int | float):
            return False
        if isinstance(v, float) and not (math.isfinite(v) and v.is_integer()):
            return False
        return prop["minimum"] <= v <= prop.get("maximum", math.inf)
    if not isinstance(v, str):
        return False
    if "pattern" in prop:
        return re.fullmatch(prop["pattern"].removeprefix("^").removesuffix("$"), v) is not None
    return prop["minLength"] <= len(v) <= prop["maxLength"]


def _oracle(raw: dict[str, Any]) -> tuple[str, str | None]:
    """Return ("ok", None), ("missing", key) or ("invalid", key)."""
    if "issue_number" not in raw:
        return ("missing", "issue_number")
    for key, prop in PROPS.items():
        if key in raw and not _oracle_ok(prop, raw[key]):
            return ("invalid", key)
    return ("ok", None)


def _near(prop: dict[str, Any]) -> st.SearchStrategy[Any]:
    if prop["type"] == "integer":
        lo, hi = prop["minimum"], prop.get("maximum", 2**40)
        return st.one_of(
            st.integers(lo - 2, hi + 2),
            st.sampled_from([lo - 1, lo, hi, hi + 1]),
            st.floats(allow_nan=True, allow_infinity=True),
        )
    if "pattern" in prop:
        return st.one_of(
            st.from_regex(r"[A-Za-z0-9-]{1,39}/[1-9][0-9]{0,6}", fullmatch=True),
            st.text(max_size=50),
        )
    return st.text(max_size=110)


VALUE_NOISE = st.one_of(st.none(), st.booleans(), st.integers(), st.text(max_size=5))


@st.composite
def raw_params(draw: st.DrawFn) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, prop in PROPS.items():
        if draw(st.booleans()):
            out[key] = draw(st.one_of(_near(prop), VALUE_NOISE))
    for key in LEGACY:
        if draw(st.booleans()):
            out[key] = draw(VALUE_NOISE)
    return out


@settings(max_examples=1000, deadline=None)
@given(raw_params())
def test_parse_params_agrees_with_the_schema_oracle(raw: dict[str, Any]) -> None:
    verdict, key = _oracle(raw)
    if verdict == "missing":
        try:
            parse_params(raw)
        except MissingRequiredParam as err:
            assert err.key == key
        else:
            raise AssertionError("expected MissingRequiredParam")
        return
    if verdict == "invalid":
        try:
            parse_params(raw)
        except InvalidParam as err:
            assert err.key == key
        else:
            raise AssertionError(f"expected InvalidParam for {key}")
        return
    p = parse_params(raw)
    for k, prop in PROPS.items():
        got = getattr(p, k)
        if k in raw:
            assert got == raw[k]
        else:
            assert got == prop.get("default")
