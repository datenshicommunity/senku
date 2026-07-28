"""Regression tests for senku.taiko, pinned to values cross-validated
against real leaderboard scores at authoring time.
"""

import pytest

from senku.taiko.beatmap import parse_osu_file
from senku.taiko.difficulty import calculate
from senku.taiko.performance import TaikoJudgements, calculate_pp

CASES = [
    pytest.param(
        "4478259.osu", frozenset(), False,
        dict(n_great=940, n_ok=40, n_meh=0, n_miss=7),
        10.14411243345877,
        952.3863462916001,
        id="4478259-nomod",
    ),
    pytest.param(
        "4485117.osu", frozenset(), False,
        dict(n_great=2006, n_ok=31, n_meh=0, n_miss=0),
        8.491874836319077,
        760.029250597632,
        id="4485117-nomod",
    ),
    # HR scales OD (standard *1.4 capped at 10) AND SliderMultiplier (*1.8666666666666665,
    # a `double`-precision constant, not the float32 CS/AR/OD/HP scaling) -- the latter
    # feeds EffectiveBPM, which the Reading skill is very sensitive to (SR still moves
    # even when OD is already saturated at 10). Cross-validated against the real .NET
    # PerformanceCalculator: sr=10.727443687256669, pp_total=1111.784683277077.
    pytest.param(
        "4478259.osu", frozenset({"HR"}), False,
        dict(n_great=940, n_ok=40, n_meh=0, n_miss=7),
        10.727443687256669,
        1111.784683277077,
        id="4478259-HR",
    ),
    # EZ: OD *0.5, SliderMultiplier *0.8. Cross-validated: sr=10.035638641162588,
    # pp_total=784.926936584448.
    pytest.param(
        "4478259.osu", frozenset({"EZ"}), False,
        dict(n_great=940, n_ok=40, n_meh=0, n_miss=7),
        10.035638641162588,
        784.926936584448,
        id="4478259-EZ",
    ),
]


@pytest.mark.parametrize("fixture_name, mods, is_convert, judgements, expected_sr, expected_pp", CASES)
def test_taiko_star_rating_and_pp(load_fixture, fixture_name, mods, is_convert, judgements, expected_sr, expected_pp):
    beatmap = parse_osu_file(load_fixture(fixture_name), mods=mods)
    attributes = calculate(beatmap, is_convert=is_convert)
    result = calculate_pp(attributes, TaikoJudgements(**judgements), overall_difficulty=beatmap.overall_difficulty)

    assert attributes.star_rating == pytest.approx(expected_sr, rel=1e-9)
    assert result["total"] == pytest.approx(expected_pp, rel=1e-9)


def test_taiko_relax(load_fixture):
    """RX is a genuine difficulty-level change in taiko (not performance-only like
    osu!std's RX) -- it zeroes colour's contribution and divides stamina's by 1.5
    inside the strain-peak combination (`combine_peaks` / `is_relax` in difficulty.py),
    which was already implemented and just needed validating. Cross-validated against
    the real .NET PerformanceCalculator: sr=7.311559353348244 (mod-independent of
    judgements, as expected), pp_total=528.3832547087891 (partial combo) /
    703.7161731015071 (full combo).
    """
    beatmap = parse_osu_file(load_fixture("4478259.osu"))
    attributes = calculate(beatmap, is_relax=True)

    assert attributes.star_rating == pytest.approx(7.311559353348244, rel=1e-9)

    partial = calculate_pp(attributes, TaikoJudgements(n_great=940, n_ok=40, n_meh=0, n_miss=7),
                            overall_difficulty=beatmap.overall_difficulty)
    assert partial["total"] == pytest.approx(528.3832547087891, rel=1e-9)

    full_combo = calculate_pp(attributes, TaikoJudgements(n_great=987, n_ok=0, n_meh=0, n_miss=0),
                               overall_difficulty=beatmap.overall_difficulty)
    assert full_combo["total"] == pytest.approx(703.7161731015071, rel=1e-9)
