"""Regression tests for senku.osu.

Expected values here are senku's own pinned output (so these are pure
regression tests -- a future change that silently shifts a result will
fail loudly). Each case's comment records the real leaderboard score (or,
where noted, the real .NET PerformanceCalculator oracle) value it was
cross-validated against at authoring time, and the observed relative
difference, for documentation.
"""

import pytest

from senku.osu.beatmap import parse_osu_file
from senku.osu.difficulty import calculate
from senku.osu.performance import OsuJudgements, calculate_pp

# (fixture, beatmap_mods, clock_rate, hidden, flashlight, perf_mods, judgements, combo, expected_sr, expected_pp)
CASES = [
    # real API: sr=2.3113901748803234 (no live nomod score exists on this map; cross-validated
    # against the real .NET PerformanceCalculator directly), pp=27.52989949598166 -- diff ~2e-5%.
    pytest.param("5127976.osu", set(), 1.0, False, False, set(),
                 dict(n300=109, n100=0, n50=0, n_miss=0), 158,
                 2.3113906366620203, 27.529906093686364, id="nomod-SS"),
    # real API: sr=2.093440490000487, pp=12.569232862564142 -- diff ~1.5e-5%.
    pytest.param("5127976.osu", {"EZ"}, 1.0, False, False, set(),
                 dict(n300=109, n100=0, n50=0, n_miss=0), 158,
                 2.0934407611239503, 12.569236198848062, id="EZ"),
    # real API score: sr=7.411836139730947, pp=422.8667733786717 (real leaderboard score) -- diff ~1e-5%.
    pytest.param("5136658.osu", set(), 1.5, False, False, {"DT"},
                 dict(n300=109, n100=2, n50=0, n_miss=0), 159,
                 7.411836434191151, 422.86681814188717, id="DT"),
    # cross-validated against real .NET PerformanceCalculator: sr=1.8752895887740701, pp=11.780201871543847.
    pytest.param("5127976.osu", set(), 0.75, False, False, set(),
                 dict(n300=109, n100=0, n50=0, n_miss=0), 158,
                 1.8752899079438776, 11.780204940222898, id="HT"),
    # real API score: sr=6.990719415832639, pp=376.57121428861126 -- diff ~5e-5%.
    pytest.param("5136658.osu", {"HR"}, 1.0, True, False, {"HR"},
                 dict(n300=110, n100=1, n50=0, n_miss=0), 159,
                 6.990720867462706, 376.57139998962424, id="HD+HR"),
    # real API score: sr=3.7828803545632175, pp=141.17136140310262 -- diff ~5e-6%.
    pytest.param("5127976.osu", {"HR"}, 1.5, True, True, {"HR"},
                 dict(n300=109, n100=0, n50=0, n_miss=0), 158,
                 3.7828801586314085, 141.17135396655178, id="HD+HR+DT+FL"),
    # cross-validated against real .NET PerformanceCalculator: sr=2.3113901748803234, pp=6.543311456312743.
    pytest.param("5127976.osu", set(), 1.0, False, False, {"NF"},
                 dict(n300=100, n100=6, n50=3, n_miss=3), 130,
                 2.3113906366620203, 6.543314209473543, id="NF"),
    # cross-validated against real .NET PerformanceCalculator: sr=0.9457953519826251, pp=17.947228491756817.
    pytest.param("5127976.osu", set(), 1.0, False, False, {"AP"},
                 dict(n300=109, n100=0, n50=0, n_miss=0), 158,
                 0.9457953515260897, 17.94722849085415, id="AP"),
    # cross-validated against real .NET PerformanceCalculator: sr=1.7943579387364148, pp=2.488884259681422.
    pytest.param("5127976.osu", set(), 1.0, False, False, {"RX"},
                 dict(n300=100, n100=6, n50=3, n_miss=3), 130,
                 1.794358362369258, 2.488885012657386, id="RX"),
    # cross-validated against real .NET PerformanceCalculator: sr=2.3113901748803234, pp=8.873826078072733.
    pytest.param("5127976.osu", set(), 1.0, False, False, {"BL"},
                 dict(n300=100, n100=6, n50=3, n_miss=3), 130,
                 2.3113906366620203, 8.873829919569896, id="BL"),
    # cross-validated against real .NET PerformanceCalculator: sr=2.3113901748803234, pp=7.803248263774922.
    pytest.param("5127976.osu", set(), 1.0, False, False, {"TC"},
                 dict(n300=100, n100=6, n50=3, n_miss=3), 130,
                 2.3113906366620203, 7.80325149678493, id="TC"),
    # cross-validated against real .NET PerformanceCalculator: sr=2.0052335373926087, pp=4.723109872514947.
    pytest.param("5127976.osu", set(), 1.0, False, False, {"TD"},
                 dict(n300=100, n100=6, n50=3, n_miss=3), 130,
                 2.005233938052813, 4.723111715867752, id="TD"),
    # cross-validated against real .NET PerformanceCalculator: sr=1.699173444677546, pp=2.8028779443409766.
    pytest.param("5127976.osu", set(), 1.0, False, False, {"MG"},
                 dict(n300=100, n100=6, n50=3, n_miss=3), 130,
                 1.6991736660409238, 2.8028787016015304, id="MG"),
]


@pytest.mark.parametrize(
    "fixture_name, beatmap_mods, clock_rate, hidden, flashlight, perf_mods, judgements, combo, expected_sr, expected_pp",
    CASES,
)
def test_osu_star_rating_and_pp(load_fixture, fixture_name, beatmap_mods, clock_rate, hidden, flashlight,
                                 perf_mods, judgements, combo, expected_sr, expected_pp):
    beatmap = parse_osu_file(load_fixture(fixture_name), mods=frozenset(beatmap_mods))
    attributes = calculate(beatmap, clock_rate=clock_rate, hidden=hidden, flashlight=flashlight, mods=frozenset(perf_mods))
    j = OsuJudgements(**judgements)
    pp = calculate_pp(
        attributes, j, score_max_combo=combo, approach_rate=beatmap.approach_rate,
        overall_difficulty_raw=beatmap.overall_difficulty, clock_rate=clock_rate,
        flashlight=flashlight, mods=frozenset(perf_mods), drain_rate=beatmap.drain_rate,
    )

    assert attributes.star_rating == pytest.approx(expected_sr, rel=1e-9)
    assert pp == pytest.approx(expected_pp, rel=1e-9)


def test_osu_legacy_score_simulator_broken_combo(load_fixture):
    """A real DT score with a broken combo (112/160) and a known legacy total
    score (370467) -- exercises the ScoreV1 simulator's score-based miss
    estimator. Real pp=345.174; senku's score-based estimate matches to
    ~1e-5%, while the combo-based-only estimate (asserted below too) is
    ~2.7% off -- that gap is *expected*, not a bug, and is exactly why the
    score-based path exists for scores with a known total score.
    """
    beatmap = parse_osu_file(load_fixture("5136658.osu"))
    attributes = calculate(beatmap, clock_rate=1.5)
    j = OsuJudgements(n300=108, n100=2, n50=0, n_miss=1)

    pp_score_based = calculate_pp(
        attributes, j, score_max_combo=112, approach_rate=beatmap.approach_rate,
        overall_difficulty_raw=beatmap.overall_difficulty, clock_rate=1.5,
        legacy_total_score=370467, mods=frozenset({"DT"}),
    )
    pp_combo_based = calculate_pp(
        attributes, j, score_max_combo=112, approach_rate=beatmap.approach_rate,
        overall_difficulty_raw=beatmap.overall_difficulty, clock_rate=1.5,
    )

    assert pp_score_based == pytest.approx(345.17343250285984, rel=1e-9)
    assert pp_combo_based == pytest.approx(335.94715440560765, rel=1e-9)


def test_osu_difficulty_adjust(load_fixture):
    """DA (ModDifficultyAdjust) directly overrides CS/AR/OD/HP, including
    extended-limits values beyond the normal [0, 10] range (e.g. AR11/OD11,
    a real farming combo with DT). Cross-validated against the real .NET
    PerformanceCalculator: sr=3.0559963087549034/pp=72.9927876128346 for the
    first case, sr=5.341830093686243/pp=325.0637253779071 for DA+DT.
    """
    text = load_fixture("5127976.osu")

    beatmap = parse_osu_file(text, difficulty_adjust={"cs": 6.5, "ar": 9.8, "od": 8.5, "hp": 7.0})
    attributes = calculate(beatmap, mods=frozenset({"DA"}))
    j = OsuJudgements(n300=109, n100=0, n50=0, n_miss=0)
    pp = calculate_pp(attributes, j, score_max_combo=158, approach_rate=beatmap.approach_rate,
                       overall_difficulty_raw=beatmap.overall_difficulty, mods=frozenset({"DA"}))

    assert attributes.star_rating == pytest.approx(3.0559879993996586, rel=1e-9)
    assert pp == pytest.approx(72.99257528928322, rel=1e-9)

    # Extended limits: DA CS5/AR11/OD11/HP5 + DT.
    beatmap_ext = parse_osu_file(text, difficulty_adjust={"cs": 5.0, "ar": 11.0, "od": 11.0, "hp": 5.0})
    attributes_ext = calculate(beatmap_ext, clock_rate=1.5, mods=frozenset({"DA", "DT"}))
    pp_ext = calculate_pp(attributes_ext, j, score_max_combo=158, approach_rate=beatmap_ext.approach_rate,
                           overall_difficulty_raw=beatmap_ext.overall_difficulty, clock_rate=1.5,
                           mods=frozenset({"DA", "DT"}))

    assert attributes_ext.star_rating == pytest.approx(5.341830022896172, rel=1e-9)
    assert pp_ext == pytest.approx(325.0637198380129, rel=1e-9)


def test_osu_aim_total_value_zero_division():
    """Regression test for a real crash found on real-world std maps: when both
    snap and agility difficulty are 0 (e.g. very early objects, or unusual
    spacing), `combined_snap_difficulty` is exactly 0 and
    `flow_difficulty / combined_snap_difficulty` raised ZeroDivisionError in
    Python where C# double division silently yields Infinity/NaN. Fixed by
    replicating IEEE754 semantics (same pattern as _miss_penalty).
    """
    from senku.osu.aim import _calculate_total_value

    # 0/0 -> NaN -> _calculate_snap_flow_probability returns 1.0 (p_snap=1, p_flow=0);
    # combined_snap_difficulty is also 0, so total_difficulty = 0*1 + 0*0 = 0.
    assert _calculate_total_value(0.0, 0.0, 0.0) == pytest.approx(0.0, abs=1e-12)
    # positive/0 -> +Infinity -> _calculate_snap_flow_probability returns 1.0 (p_snap=1,
    # p_flow=0), so the nonzero flow_difficulty gets weighted by p_flow=0 -> still 0.
    # The point of this case isn't the *value* (0 either way) -- it's that it
    # doesn't raise ZeroDivisionError.
    assert _calculate_total_value(0.0, 0.0, 5.0) == pytest.approx(0.0, abs=1e-12)


def test_osu_malformed_slider_curve_token_does_not_crash(load_fixture):
    """Regression test for a crash on a real "aspire"/troll beatmap: a
    mapper stuffed a non-coordinate token (no ":") into a slider's curve
    field -- previously `_parse_curve` raised ValueError trying to unpack
    it as an "x:y" pair. Fixed by skipping tokens without a colon instead
    of treating the whole slider as malformed.
    """
    beatmap = parse_osu_file(load_fixture("std_malformed_slider_token_edge_case.osu"))
    attributes = calculate(beatmap)

    assert attributes.star_rating == pytest.approx(0.1432439930261732, rel=1e-9)
