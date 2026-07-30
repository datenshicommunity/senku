import random

import senku._slider_path as slider_path
from senku._slider_path import build_path, path_length, slider_curve_would_throw


def test_slider_curve_would_throw_on_three_consecutive_markers():
    # "D|I|C|..." -- the middle marker (I) ends up with zero control points
    # assigned to it once C starts, which is exactly the empty-segment
    # condition ConvertHitObjectParser.convertPoints throws on (indexing
    # vertices[0] of a zero-length array). Real-world case: a troll curve
    # spelling out a word one letter-token at a time (e.g. "D|I|C|K|S|B|...").
    assert slider_curve_would_throw("D|I|C|10:10|20:20") is True


def test_slider_curve_would_throw_on_trailing_marker_with_no_points():
    # "B|L" with nothing after -- L is the last marker and gets an empty
    # slice all the way to the end.
    assert slider_curve_would_throw("B|L") is True


def test_slider_curve_does_not_throw_for_two_leading_markers_then_points():
    # The very first-ever marker is special-cased (gets an implicit anchor
    # point), so a single pair of leading letters followed by real
    # coordinates is legitimate and must not be rejected.
    assert slider_curve_would_throw("B|L|10:10") is False


def test_slider_curve_does_not_throw_for_normal_curve():
    assert slider_curve_would_throw("B|10:10|20:20|30:30") is False


def test_slider_curve_does_not_throw_for_non_consecutive_marker():
    # A curve-type change in the middle of real points is normal
    # (multi-segment sliders) and must not be flagged.
    assert slider_curve_would_throw("B|10:10|L|20:20|30:30") is False


def test_bezier_downsample_cap_does_not_distort_moderately_sized_curves(monkeypatch):
    # Regression test: a real "aspire" beatmap (2568364) has a legitimate
    # (non-troll) single Bezier segment with 900 control points. The old
    # _MAX_BEZIER_CONTROL_POINTS=300 cap downsampled it and silently changed
    # its geometric path length by more than 2x (1624 vs the true ~720.4),
    # which flipped a tick-count decision downstream and threw off
    # max_combo/star_rating. Confirm a curve in that size range is NOT
    # downsampled at the current cap, by checking it produces a materially
    # different (and here, known-larger/wrong) result at the old cap.
    random.seed(0)
    points = [(100.0, 100.0)]
    x, y = 100.0, 100.0
    for _ in range(500):
        x = max(0.0, min(500.0, x + random.uniform(-5, 5)))
        y = max(0.0, min(400.0, y + random.uniform(-5, 5)))
        points.append((x, y))

    monkeypatch.setattr(slider_path, "_MAX_BEZIER_CONTROL_POINTS", 5000)
    full_length = path_length(build_path("B", points, 0.0))

    monkeypatch.setattr(slider_path, "_MAX_BEZIER_CONTROL_POINTS", 300)
    downsampled_length = path_length(build_path("B", points, 0.0))

    assert abs(downsampled_length - full_length) / full_length > 0.1
