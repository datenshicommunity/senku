"""Regression tests for senku.catch, pinned to values cross-validated
against real leaderboard scores at authoring time.
"""

import pytest

from senku.catch.beatmap import parse_osu_file
from senku.catch.difficulty import calculate
from senku.catch.performance import CatchJudgements, calculate_pp

CASES = [
    pytest.param(
        "341072.osu",
        dict(n_fruit=983, n_large_droplet=0, n_small_droplet=242, n_small_droplet_miss=0, n_miss=0),
        983,
        5.272840742728842,
        308.7067793217544,
        id="341072",
    ),
    pytest.param(
        "4921835.osu",
        dict(n_fruit=2544, n_large_droplet=77, n_small_droplet=79, n_small_droplet_miss=1, n_miss=1),
        2592,
        10.075895854357011,
        1408.4302505955438,
        id="4921835",
    ),
]


@pytest.mark.parametrize("fixture_name, judgements, combo, expected_sr, expected_pp", CASES)
def test_catch_star_rating_and_pp(load_fixture, fixture_name, judgements, combo, expected_sr, expected_pp):
    beatmap = parse_osu_file(load_fixture(fixture_name))
    attributes = calculate(beatmap)
    pp = calculate_pp(attributes, CatchJudgements(**judgements), max_combo_achieved=combo, approach_rate=beatmap.approach_rate)

    assert attributes.star_rating == pytest.approx(expected_sr, rel=1e-9)
    assert pp == pytest.approx(expected_pp, rel=1e-9)
