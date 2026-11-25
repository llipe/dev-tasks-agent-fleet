"""
RT-01 (S-204) — property tactic over arbitrary ``params`` values.

Seed 406001 (issue #406 x 1000 + 1), 5,000 iterations. Properties:

- ``validate_payload`` never raises anything but ``InvalidParams``.
- Accepted => every value is within the spec §5.1 bounds and enums.
- ``bool`` is never accepted for an integer field.
- ``apply_defaults`` is idempotent and its output re-validates.

RT-21 (S-217, test plan §14.8) — seed 481001, 3,000 iterations, biased to ±3
around 100, 20,000 and 900,000 and the other §5.1 bounds: accepted iff within
the v1.8 bounds and enums; ``bool`` never accepted for an integer; and every
integer the shared CT-20 case file pins gets the same verdict here as the file
records (the file the panel's Ajv evaluates).

Replay one iteration with ``PRNG_SEED=<seed> PRNG_ITER=<i>``.
"""

from __future__ import annotations

import json
import os
import random
from pathlib import Path

from config import PARAMS_SCHEMA
from context.selection import InvalidFolders, parse_context_folders
from main import InvalidParams, apply_defaults, validate_payload

SEED = int(os.environ.get("PRNG_SEED", "406001"))
ITERATIONS = 5000
ONLY_ITER = os.environ.get("PRNG_ITER")

RUN_ID = "3f2b8c1e-5d4a-4f6b-9a7c-2e1d0b9a8c7f"
PROPS = PARAMS_SCHEMA["properties"]
INT_KEYS = [k for k, v in PROPS.items() if v["type"] == "integer"]
FOLDER_VALUES = ["docs", "docs,workstream", "", "a/b, c", "..", "/x", "x/", "a,,b", "d\n", "."]


def _near(rng: random.Random, key: str) -> int:
    prop = PROPS[key]
    anchor = rng.choice([prop.get("minimum", 0), prop.get("maximum", 10**6), 0, 1])
    return int(anchor) + rng.randint(-2, 2)


def _value(rng: random.Random, key: str | None, depth: int = 0) -> object:
    if key is not None and rng.random() < 0.5:
        # Plausible value: near a bound for integers, near the enum for strings.
        if key in INT_KEYS:
            return _near(rng, key)
        if key == "context_folders":
            return rng.choice(FOLDER_VALUES)
        return rng.choice([*PROPS[key]["enum"], "HIGH", "max", ""])
    kind = rng.randrange(10)
    if kind == 3:
        return rng.choice([True, False])
    if kind == 4:
        return rng.choice([0.5, 1.0, 7.0, -3.25, 1e9, float(rng.randint(-5, 5))])
    if kind == 5:
        return rng.choice(["", "1", "high", "HIGH", "low", "medium", "x" * rng.randint(0, 20)])
    if kind == 6:
        return None
    if kind == 7 and depth < 2:
        return [_value(rng, None, depth + 1) for _ in range(rng.randint(0, 3))]
    if kind == 8 and depth < 2:
        return {"k": _value(rng, None, depth + 1)}
    return rng.randint(-(2**40), 2**40)


def _params(rng: random.Random) -> object:
    shape = rng.randrange(20)
    if shape == 0:
        return _value(rng, None)  # not an object at all
    params: dict[str, object] = {}
    for key in PROPS:
        if rng.random() < (0.9 if key == "pr_number" else 0.3):
            params[key] = _value(rng, key)
    if rng.random() < 0.1:
        params[rng.choice(["foo", "pr", "PR_NUMBER", "max_diff_line"])] = 1
    return params


def _within_bounds(params: dict) -> bool:
    for key, value in params.items():
        prop = PROPS[key]
        if prop["type"] == "integer":
            if not isinstance(value, int) or isinstance(value, bool):
                return False
            if value < prop.get("minimum", value) or value > prop.get("maximum", value):
                return False
        elif prop["type"] == "string" and key == "context_folders":
            try:
                parse_context_folders(value)
            except InvalidFolders:
                return False
        elif prop["type"] == "string" and value not in prop["enum"]:
            return False
    return True


def test_rt01_params_property():
    rng = random.Random(SEED)
    accepted = 0
    for i in range(ITERATIONS):
        params = _params(rng)
        if ONLY_ITER is not None and str(i) != ONLY_ITER:
            continue
        payload = {
            "run_id": RUN_ID,
            "repository_org": "o",
            "repository_name": "r",
            "params": params,
        }
        context = f"seed={SEED} iter={i} params={params!r}"
        try:
            validate_payload(payload)
        except InvalidParams:
            continue
        except Exception as exc:  # pragma: no cover - property failure path
            raise AssertionError(f"non-InvalidParams {type(exc).__name__}: {context}") from exc

        accepted += 1
        assert isinstance(params, dict), context
        assert set(params) <= set(PROPS), context
        assert "pr_number" in params, context
        assert _within_bounds(params), context

        once = apply_defaults(params)
        assert apply_defaults(once) == once, context
        validate_payload({**payload, "params": once})

    if ONLY_ITER is None:
        # The generator must exercise the accept path, not only rejections.
        assert accepted > 50, f"only {accepted} accepted cases (seed={SEED})"


# ---------------------------------------------------------------------------
# RT-21 (S-217): the v1.8 bounds (D-77, D-90)
# ---------------------------------------------------------------------------

RT21_SEED = int(os.environ.get("PRNG_SEED", "481001"))
RT21_ITERATIONS = 3000
V18_BOUNDS = {
    "max_diff_lines": (100, 20000),
    "max_context_tokens": (20000, 900000),
    "max_suggestions": (0, 20),
    "run_timeout_seconds": (120, 900),
}
ANCHORS = [100, 20000, 900000, 0, 20, 120, 900, 10000, 400000]
CASES_FILE = Path(__file__).resolve().parents[1] / "fixtures" / "params_cases.json"


def _rt21_value(rng: random.Random) -> object:
    roll = rng.random()
    if roll < 0.8:
        return rng.choice(ANCHORS) + rng.randint(-3, 3)
    if roll < 0.9:
        return rng.choice([True, False])
    return rng.choice([str(rng.choice(ANCHORS)), None, 900000.5, [900000]])


def _payload_with(params: object) -> dict[str, object]:
    return {"run_id": RUN_ID, "repository_org": "o", "repository_name": "r", "params": params}


def _accepted(params: object) -> bool:
    try:
        validate_payload(_payload_with(params))
    except InvalidParams:
        return False
    return True


def test_rt21_v18_bounds_property():
    assert {k: (PROPS[k]["minimum"], PROPS[k]["maximum"]) for k in V18_BOUNDS} == V18_BOUNDS
    rng = random.Random(RT21_SEED)
    accepted = rejected = 0
    for i in range(RT21_ITERATIONS):
        key = rng.choice(list(V18_BOUNDS))
        value = _rt21_value(rng)
        if ONLY_ITER is not None and str(i) != ONLY_ITER:
            continue
        lo, hi = V18_BOUNDS[key]
        expected = (
            isinstance(value, int) and not isinstance(value, bool) and lo <= value <= hi
        )
        got = _accepted({"pr_number": 1, key: value})
        assert got == expected, f"seed={RT21_SEED} iter={i} {key}={value!r}"
        accepted += got
        rejected += not got
    if ONLY_ITER is None:
        assert accepted > 500 and rejected > 500


def test_rt21_python_agrees_with_every_pinned_integer_case():
    """The frozen CT-20 sample: Python's verdict equals the one the panel's Ajv must reach."""
    cases = json.loads(CASES_FILE.read_text())["cases"]
    pinned = 0
    for case in cases:
        params = case.get("params")
        if not isinstance(params, dict) or case.get("absent"):
            continue
        ints = {k: v for k, v in params.items() if k in V18_BOUNDS}
        if not ints:
            continue
        pinned += 1
        assert _accepted(params) == case["valid"], case["id"]
    assert pinned >= 15
    edges = {
        (k, v)
        for c in cases
        if isinstance(c.get("params"), dict)
        for k, v in c["params"].items()
        if k in {"max_diff_lines", "max_context_tokens"}
    }
    for edge in [
        ("max_diff_lines", 19999),
        ("max_diff_lines", 20000),
        ("max_diff_lines", 20001),
        ("max_context_tokens", 899999),
        ("max_context_tokens", 900000),
        ("max_context_tokens", 900001),
    ]:
        assert edge in edges, edge  # EC-43: both validators see every edge
