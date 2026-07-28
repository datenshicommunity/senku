"""Regression tests for the IEEE754/C#-semantics helpers in _diffutils.py.
Each one exists because a real "aspire"/troll osu! beatmap (deliberately
extreme edge-case content, e.g. slider lengths in the billions, literal
"NaN" as a note's timestamp) crashed senku by hitting a Python/C# numeric
semantics mismatch that normal beatmaps never trigger. See _diffutils.py's
own docstrings for what real-world input pattern each one guards against.
"""

import math

import pytest

from senku._diffutils import norm, safe_divide, safe_pow, safe_round, safe_truncate, unchecked_int32


def test_safe_divide_by_zero():
    assert safe_divide(5.0, 0.0) == math.inf
    assert safe_divide(-5.0, 0.0) == -math.inf
    assert math.isnan(safe_divide(0.0, 0.0))
    assert safe_divide(6.0, 3.0) == 2.0


def test_safe_pow_negative_base_fractional_exponent():
    # Python's ** returns a complex number here; C#'s Math.Pow returns NaN.
    assert math.isnan(safe_pow(-2.0, 1.5))
    # Integer exponents (even as a float) compute normally for a negative base.
    assert safe_pow(-2.0, 2.0) == 4.0
    assert safe_pow(-2.0, 3.0) == -8.0
    assert safe_pow(2.0, 1.5) == pytest.approx(2.0 ** 1.5)


def test_norm_negative_input_does_not_crash():
    # A strain value that goes slightly negative before a fractional-power
    # p-norm previously produced a Python complex number several calls
    # downstream, crashing on an unrelated `if x > 0` comparison.
    result = norm(1.5, -0.5, 2.0)
    assert isinstance(result, float)


def test_safe_truncate_non_finite():
    assert safe_truncate(math.inf) == math.inf
    assert safe_truncate(-math.inf) == -math.inf
    assert math.isnan(safe_truncate(math.nan))
    assert safe_truncate(3.7) == 3.0
    assert safe_truncate(-3.7) == -3.0


def test_safe_round_non_finite():
    assert safe_round(math.inf) == math.inf
    assert math.isnan(safe_round(math.nan))
    assert safe_round(2.5) == 2.0  # banker's rounding, matches Python round() and C# Math.Round()


def test_unchecked_int32_overflow():
    assert unchecked_int32(math.inf) == -(2**31)
    assert unchecked_int32(-math.inf) == -(2**31)
    assert unchecked_int32(math.nan) == -(2**31)
    assert unchecked_int32(2.0**40) == -(2**31)
    assert unchecked_int32(42.9) == 42
