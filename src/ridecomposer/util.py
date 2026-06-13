"""Tiny math helpers shared across the engine. Pure stdlib, no surprises."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence

NUMBER = (int, float)


def lerp(a: float, b: float, t: float) -> float:
    """Linear interpolation a..b by t (t is not clamped)."""
    return a + (b - a) * t


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if x < lo else hi if x > hi else x


def percentile(sorted_vals: Sequence[float], p: float) -> float:
    """p in 0..1 over an already-sorted sequence, linearly interpolated."""
    if not sorted_vals:
        return 0.0
    i = p * (len(sorted_vals) - 1)
    lo = int(i)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return lerp(sorted_vals[lo], sorted_vals[hi], i - lo)


def normalizer(vals: Iterable[float]) -> Callable[[float], float]:
    """Build f(x) -> 0..1 from robust 5th/95th percentiles.

    Percentiles (not min/max) so a single GPS/power spike can't flatten the
    whole mapping into the floor — the body of the ride keeps its dynamic range.
    """
    clean = sorted(v for v in vals if isinstance(v, NUMBER))
    lo = percentile(clean, 0.05)
    hi = percentile(clean, 0.95)
    if hi - lo < 1e-9:
        hi = lo + 1.0
    span = hi - lo
    return lambda x: clamp((x - lo) / span)
