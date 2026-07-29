"""Regression test for a RuntimeWarning found stress-testing real "aspire"
beatmaps: a troll timing point with a near-zero scroll_speed makes the
intermediate bpm-multiplier value far exceed float32's range, overflowing
on cast even though the surrounding np.clip masks it either way.
"""

import warnings

from senku._legacy_beat_length import precision_adjusted_beat_length


def test_precision_adjusted_beat_length_extreme_scroll_speed_no_warning():
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        result = precision_adjusted_beat_length(500.0, 1e-30, ruleset="osu")
    assert result == 500.0 * 10.0  # clamped to the "osu" ruleset's hi=1000.0 -> *10.0


def test_precision_adjusted_beat_length_normal_range_unaffected():
    # A no-op pre-clamp for any value already inside [lo, hi] -- must not
    # change behaviour for ordinary (non-troll) beatmaps.
    result = precision_adjusted_beat_length(500.0, 2.0, ruleset="osu")
    assert result == 500.0 * 0.5
