"""Regression tests for senku.taiko, pinned to values cross-validated
against real leaderboard scores at authoring time.
"""

import pytest

from senku.taiko.beatmap import parse_osu_file
from senku.taiko.difficulty import calculate
from senku.taiko.performance import TaikoJudgements, calculate_pp

CASES = [
    pytest.param(
        "4478259.osu",
        dict(n_great=940, n_ok=40, n_meh=0, n_miss=7),
        10.14411243345877,
        952.3863462916001,
        id="4478259",
    ),
    pytest.param(
        "4485117.osu",
        dict(n_great=2006, n_ok=31, n_meh=0, n_miss=0),
        8.491874836319077,
        760.029250597632,
        id="4485117",
    ),
]


@pytest.mark.parametrize("fixture_name, judgements, expected_sr, expected_pp", CASES)
def test_taiko_star_rating_and_pp(load_fixture, fixture_name, judgements, expected_sr, expected_pp):
    beatmap = parse_osu_file(load_fixture(fixture_name))
    attributes = calculate(beatmap)
    result = calculate_pp(attributes, TaikoJudgements(**judgements), overall_difficulty=beatmap.overall_difficulty)

    assert attributes.star_rating == pytest.approx(expected_sr, rel=1e-9)
    assert result["total"] == pytest.approx(expected_pp, rel=1e-9)
