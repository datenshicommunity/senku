"""Shared math helper functions used across difficulty/performance engines.

Small, general-purpose curve-shaping functions (logistic, smoothstep,
error function, p-norm, etc.) -- the same handful of building blocks
recur across every mode's difficulty formula. Written from scratch;
nothing here is mode-specific.
"""

from __future__ import annotations

import math

import numpy as np

SQRT2 = 1.4142135623730950


def apply_difficulty_mods(circle_size: float, approach_rate: float, overall_difficulty: float, drain_rate: float,
                           mods: frozenset[str]) -> tuple[float, float, float, float]:
    """HR/EZ CS/AR/OD/HP scaling shared across modes that carry these four stats.

    BeatmapDifficulty fields are `float` (single precision) in the real game, and
    mods multiply them in that precision -- match via float32 to reproduce
    identical rounding. Modes that don't use a given stat (e.g. catch ignoring
    OD/HP) can just discard the corresponding return value.
    """
    cs = np.float32(circle_size)
    ar = np.float32(approach_rate)
    od = np.float32(overall_difficulty)
    hp = np.float32(drain_rate)

    if "EZ" in mods:
        cs *= np.float32(0.5)
        ar *= np.float32(0.5)
        od *= np.float32(0.5)
        hp *= np.float32(0.5)
    elif "HR" in mods:
        cs = min(cs * np.float32(1.3), np.float32(10.0))
        ar = min(ar * np.float32(1.4), np.float32(10.0))
        od = min(od * np.float32(1.4), np.float32(10.0))
        hp = min(hp * np.float32(1.4), np.float32(10.0))

    return float(cs), float(ar), float(od), float(hp)


def milliseconds_to_bpm(ms: float, delimiter: int = 4) -> float:
    return 60000.0 / (ms * delimiter)


def logistic_full(x: float, midpoint_offset: float, multiplier: float, max_value: float = 1.0) -> float:
    return max_value / (1.0 + math.exp(multiplier * (midpoint_offset - x)))


def logistic(exponent: float, max_value: float = 1.0) -> float:
    return max_value / (1.0 + math.exp(exponent))


def safe_pow(base: float, exponent: float) -> float:
    """Matches C#'s Math.Pow: a negative base with a non-integer exponent
    yields NaN. Python's ** operator instead returns a complex number, which
    crashes far downstream (e.g. an unrelated `if x > 0` comparison) rather
    than at the actual point of divergence -- a strain value going slightly
    negative before a fractional-power p-norm is a real (if rare) occurrence
    on real beatmaps, not just contrived input."""
    if base < 0 and exponent != math.floor(exponent):
        return math.nan
    return base ** exponent


def norm(p: float, *values: float) -> float:
    total = sum(safe_pow(v, p) for v in values)
    return safe_pow(total, 1.0 / p)


def bell_curve(x: float, mean: float, width: float, multiplier: float = 1.0) -> float:
    return multiplier * math.exp(math.e * -(pow(x - mean, 2) / pow(width, 2)))


def smoothstep_bell_curve(x: float) -> float:
    x = 0.5 - abs(x - 0.5)
    x = min(max(x * 2.0, 0.0), 1.0)
    return x * x * (3.0 - 2.0 * x)


def smoothstep(x: float, start: float, end: float) -> float:
    t = min(max((x - start) / (end - start), 0.0), 1.0)
    return t * t * (3.0 - 2.0 * t)


def smootherstep(x: float, start: float, end: float) -> float:
    t = min(max((x - start) / (end - start), 0.0), 1.0)
    return t * t * t * (t * (6.0 * t - 15.0) + 10.0)


def reverse_lerp(x: float, start: float, end: float) -> float:
    return min(max((x - start) / (end - start), 0.0), 1.0)


def erf(x: float) -> float:
    if x == 0:
        return 0.0
    if math.isinf(x):
        return 1.0 if x > 0 else -1.0
    if math.isnan(x):
        return math.nan

    t = 1.0 / (1.0 + 0.3275911 * abs(x))
    tau = t * (0.254829592 + t * (-0.284496736 + t * (1.421413741 + t * (-1.453152027 + t * 1.061405429))))
    result = 1.0 - tau * math.exp(-x * x)
    return result if x >= 0 else -result


def erfc(x: float) -> float:
    return 1.0 - erf(x)


def erf_inv(x: float) -> float:
    if x <= -1:
        return -math.inf
    if x >= 1:
        return math.inf
    if x == 0:
        return 0.0

    a = 0.147
    sign = 1.0 if x > 0 else -1.0
    x = abs(x)

    ln = math.log(1 - x * x)
    t1 = 2 / (math.pi * a) + ln / 2
    t2 = ln / a
    base_approx = math.sqrt(t1 * t1 - t2) - t1

    correction = pow((x - 0.85) / 0.293, 8) if x >= 0.85 else 0.0
    return sign * (math.sqrt(base_approx) + correction)


def almost_equal(a: float, b: float, epsilon: float) -> bool:
    return abs(a - b) <= epsilon


_INT32_MIN = -(2**31)
_INT32_MAX = 2**31 - 1


def safe_divide(a: float, b: float) -> float:
    """Matches C# double division semantics: division by exact zero yields
    +-Infinity or NaN rather than raising ZeroDivisionError like Python's `/`
    does for floats. Comes up wherever a ratio is built from two beatmap-
    derived deltas that can coincide (e.g. two notes at the same timestamp)."""
    if b == 0:
        if a > 0:
            return math.inf
        if a < 0:
            return -math.inf
        return math.nan
    return a / b


def safe_round(x: float) -> float:
    """Matches C#'s Math.Round(double): returns a double, so infinity/NaN pass
    through unchanged rather than raising like Python's round() (which
    rejects non-finite input outright)."""
    if math.isnan(x) or math.isinf(x):
        return x
    return float(round(x))


def safe_truncate(x: float) -> float:
    """Matches C#'s `Math.Truncate(double)`: returns a double, so infinity/NaN
    pass through unchanged rather than raising like Python's `math.trunc`
    (which converts to an arbitrary-precision int and rejects non-finite
    input). Degenerate beatmap data can legitimately produce infinite
    intermediate ratios here."""
    if math.isnan(x) or math.isinf(x):
        return x
    return float(math.trunc(x))


def unchecked_int32(x: float) -> int:
    """Matches C#'s `unchecked (int)` cast of a double: overflow, underflow,
    infinity, and NaN all silently produce int.MinValue rather than raising
    (Python's `int()` raises OverflowError/ValueError instead). Degenerate
    beatmap data -- e.g. a slider with near-zero velocity computing an
    effectively-infinite duration -- can produce exactly this on troll/edge-
    case maps, and the reference client keeps going rather than crashing."""
    if math.isnan(x) or math.isinf(x) or x > _INT32_MAX or x < _INT32_MIN:
        return _INT32_MIN
    return int(x)
