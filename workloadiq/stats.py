"""Small numeric helpers, pure standard library.

Keeping these in one place means we can later swap the internals for numpy
without touching callers.
"""

from __future__ import annotations

from typing import Sequence


def mean(values: Sequence[float]) -> float:
    vals = list(values)
    return sum(vals) / len(vals) if vals else 0.0


def quantile(values: Sequence[float], q: float) -> float:
    """Linear-interpolation quantile (same method as numpy's default)."""
    vals = sorted(values)
    if not vals:
        return 0.0
    if len(vals) == 1:
        return vals[0]
    q = min(max(q, 0.0), 1.0)
    pos = q * (len(vals) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(vals) - 1)
    frac = pos - lo
    return vals[lo] * (1 - frac) + vals[hi] * frac


def p95(values: Sequence[float]) -> float:
    return quantile(values, 0.95)


def linreg(xs: Sequence[float], ys: Sequence[float]) -> tuple[float, float]:
    """Ordinary least squares. Returns (slope, intercept). Slope is 0 if degenerate."""
    n = len(xs)
    if n < 2:
        return 0.0, (ys[0] if ys else 0.0)
    mx = mean(xs)
    my = mean(ys)
    denom = sum((x - mx) ** 2 for x in xs)
    if denom == 0:
        return 0.0, my
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom
    intercept = my - slope * mx
    return slope, intercept


def safe_ratio(numerator: float, denominator: float) -> float:
    """recent/baseline style ratio with graceful handling of ~zero baselines."""
    eps = 1e-9
    if abs(denominator) < eps:
        if abs(numerator) < eps:
            return 1.0
        return float("inf")
    return numerator / denominator
