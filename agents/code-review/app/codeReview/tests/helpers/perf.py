"""Wall-clock bounds for the linear-time regression tests.

A bound is tuned on a developer machine under coverage tracing. Shared CI
runners are slower and noisier, so on CI (``CI`` set, as GitHub Actions does)
each bound is multiplied by ``PERF_BOUND_SCALE`` (default 5). The inputs are
sized so a quadratic implementation misses the scaled bound by orders of
magnitude, so the scale keeps the test meaningful while removing runner noise.
"""

from __future__ import annotations

import os

DEFAULT_CI_SCALE = 5.0


def perf_scale() -> float:
    """Return the multiplier applied to every wall-clock bound."""
    raw = os.environ.get("PERF_BOUND_SCALE")
    if raw:
        return float(raw)
    return DEFAULT_CI_SCALE if os.environ.get("CI") else 1.0


def perf_bound(seconds: float) -> float:
    """Return ``seconds`` scaled for the current environment."""
    return seconds * perf_scale()
