"""Regression tests for senku.mania, pinned to values cross-validated
against real leaderboard scores at authoring time (see module docstrings
for the validation methodology).
"""

import pytest

from senku.mania.beatmap import parse_osu_file
from senku.mania.difficulty import star_rating
from senku.mania.performance import ManiaJudgements, calculate_pp

CASES = [
    pytest.param(
        "2089432.osu",
        dict(n_perfect=6770, n_great=1468, n_good=48, n_ok=9, n_meh=1, n_miss=7),
        10.316707634272712,
        1338.5574800856127,
        id="2089432",
    ),
    pytest.param(
        "5074941.osu",
        dict(n_perfect=5732, n_great=3075, n_good=381, n_ok=92, n_meh=41, n_miss=127),
        11.74067501797634,
        1358.0120496102206,
        id="5074941",
    ),
    pytest.param(
        "5107047.osu",
        dict(n_perfect=11752, n_great=4944, n_good=151, n_ok=21, n_meh=16, n_miss=16),
        11.627630733008322,
        1659.8213129270673,
        id="5107047",
    ),
]


@pytest.mark.parametrize("fixture_name, judgements, expected_sr, expected_pp", CASES)
def test_mania_star_rating_and_pp(load_fixture, fixture_name, judgements, expected_sr, expected_pp):
    beatmap = parse_osu_file(load_fixture(fixture_name))
    sr = star_rating(beatmap)
    pp = calculate_pp(sr, ManiaJudgements(**judgements))

    assert sr == pytest.approx(expected_sr, rel=1e-9)
    assert pp == pytest.approx(expected_pp, rel=1e-9)
