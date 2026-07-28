"""Shared math helper functions used across difficulty/performance engines.

Small, general-purpose curve-shaping functions (logistic, smoothstep,
error function, p-norm, etc.) -- the same handful of building blocks
recur across every mode's difficulty formula. Written from scratch;
nothing here is mode-specific.
"""

from __future__ import annotations

import math

SQRT2 = 1.4142135623730950


def milliseconds_to_bpm(ms: float, delimiter: int = 4) -> float:
    return 60000.0 / (ms * delimiter)


def logistic_full(x: float, midpoint_offset: float, multiplier: float, max_value: float = 1.0) -> float:
    return max_value / (1.0 + math.exp(multiplier * (midpoint_offset - x)))


def logistic(exponent: float, max_value: float = 1.0) -> float:
    return max_value / (1.0 + math.exp(exponent))


def norm(p: float, *values: float) -> float:
    total = sum(pow(v, p) for v in values)
    return pow(total, 1.0 / p)


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
