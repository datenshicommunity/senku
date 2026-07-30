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
    # Real production "aspire"/farm maps flagged for disproportionate relax PP on datenshi
    # (lets' own relax adapter gives these ~20-40x senku/oracle's number -- a lets-side bug,
    # not senku's; tracked separately). Added here as regression coverage of senku's RX
    # handling at real high-star-rating content, not just the one modest SR~1.8 case above.
    # Cross-validated against real .NET PerformanceCalculator: sr=6.818418495931014, pp=361.545073470113.
    pytest.param("5381367.osu", set(), 1.0, False, False, {"RX"},
                 dict(n300=1096, n100=0, n50=0, n_miss=0), 1372,
                 6.818412378284261, 361.5440992252285, id="RX-farm-5381367"),
    # Cross-validated against real .NET PerformanceCalculator: sr=6.957481669319994, pp=382.62159677220853.
    pytest.param("5645843.osu", set(), 1.0, False, False, {"RX"},
                 dict(n300=1075, n100=0, n50=0, n_miss=0), 1420,
                 6.957506312712217, 382.6256706536426, id="RX-farm-5645843"),
    # Cross-validated against real .NET PerformanceCalculator: sr=3.899620680622358, pp=61.81302391580813.
    pytest.param("4601031.osu", set(), 1.0, False, False, {"RX"},
                 dict(n300=528, n100=0, n50=0, n_miss=0), 733,
                 3.8996204394025114, 61.81301244465943, id="RX-farm-4601031"),
    # Cross-validated against real .NET PerformanceCalculator: sr=3.684146027279857, pp=52.12214200126915.
    pytest.param("4601030.osu", set(), 1.0, False, False, {"RX"},
                 dict(n300=528, n100=0, n50=0, n_miss=0), 733,
                 3.684145802091596, 52.122132443119604, id="RX-farm-4601030"),
    # Cross-validated against real .NET PerformanceCalculator: sr=2.8796857228586723, pp=23.790395459369638.
    pytest.param("5129554.osu", set(), 1.0, False, False, {"RX"},
                 dict(n300=264, n100=0, n50=0, n_miss=0), 272,
                 2.879685493086421, 23.790389764699256, id="RX-farm-5129554"),
    # Cross-validated against real .NET PerformanceCalculator: sr=4.704508142838955, pp=107.8333281964623.
    pytest.param("5129558.osu", set(), 1.0, False, False, {"RX"},
                 dict(n300=490, n100=0, n50=0, n_miss=0), 497,
                 4.704507990607055, 107.83331773064691, id="RX-farm-5129558"),
    # Cross-validated against real .NET PerformanceCalculator: sr=4.411759485870838, pp=95.97621199597597.
    pytest.param("5029221.osu", set(), 1.0, False, False, {"RX"},
                 dict(n300=960, n100=0, n50=0, n_miss=0), 1040,
                 4.411760951886578, 95.97630770859836, id="RX-farm-5029221"),
    # Cross-validated against real .NET PerformanceCalculator: sr=3.8357943599612354, pp=69.57074308382603.
    pytest.param("5424081.osu", set(), 1.0, False, False, {"RX"},
                 dict(n300=1618, n100=0, n50=0, n_miss=0), 2133,
                 3.8357945710792465, 69.57075457490889, id="RX-farm-5424081"),
    # Cross-validated against real .NET PerformanceCalculator: sr=4.474876154224739, pp=95.35785177270066.
    pytest.param("5422098.osu", set(), 1.0, False, False, {"RX"},
                 dict(n300=653, n100=0, n50=0, n_miss=0), 845,
                 4.474876879578805, 95.35789815792502, id="RX-farm-5422098"),
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


def test_osu_extreme_slider_length_drops_the_object(load_fixture):
    """Regression test for a real "aspire"/troll beatmap where senku's star
    rating blew up to 9,969,497 (the map's own real official rating is a
    bounded ~176.7) -- a mapper set several sliders' declared pixel_length
    to hundreds of billions of pixels, which senku previously used at face
    value, producing an astronomical aim travel distance.

    Root cause (confirmed via decompile): the reference client's
    LegacyDecoder wraps every .osu line in a try/catch; ConvertHitObjectParser
    throws OverflowException via Parsing.ParseDouble when a slider's declared
    length exceeds Parsing.MAX_COORDINATE_VALUE (131072.0) -- the whole
    object is then silently dropped, not clamped. Confirmed exactly on the
    real map: 840 raw HitObjects lines -> 819 in the reference's playable
    beatmap, all 21 dropped for this exact reason (zero for any other).
    """
    beatmap = parse_osu_file(load_fixture("std_extreme_slider_length_edge_case.osu"))

    assert len(beatmap.objects) == 3  # the 2 normal circles + the trailing one; the extreme slider is dropped
    assert all(o.kind.name == "CIRCLE" for o in beatmap.objects)

    attributes = calculate(beatmap)
    assert attributes.star_rating == pytest.approx(0.3018816788399207, rel=1e-9)


def test_osu_negative_slider_length_uses_geometric_distance(load_fixture):
    """Regression test for a real "aspire"/troll beatmap where senku's
    star_rating was 46.51% too low (8.010 vs the map's real official
    14.976) despite hit_circle_count/slider_count/spinner_count and
    max_combo all matching almost exactly -- the earlier extreme-length fix
    only covered pixel_length > 131072, not a *negative* declared length
    (e.g. "-1", a troll mapper's way of saying "just use the control
    points' own geometry").

    Root cause (confirmed via decompile + direct raw-data inspection):
    the reference clamps pixel_length with `Math.Max(0.0, Parsing.ParseDouble(...))`
    -- senku's first fix only added the upper-bound rejection, still using
    the (now non-negative but still wrong) declared value at face value.
    But `_clamp_to_length` is deliberately a no-op when the declared length
    is <=0, so the path already carries the correct geometric length --
    `path_distance` just needs to read that instead of the invalid
    declared value. A slider with curve "L|0:0" (linear, to the origin)
    from head (348,380) has a real geometric length of ~515.27, not 0.
    """
    beatmap = parse_osu_file(load_fixture("std_negative_slider_length_edge_case.osu"))
    slider = next(o for o in beatmap.objects if o.kind.name == "SLIDER")

    assert slider.path_distance == pytest.approx(515.2708025883089, rel=1e-9)

    attributes = calculate(beatmap)
    assert attributes.star_rating == pytest.approx(0.35373420605094213, rel=1e-9)
    assert attributes.max_combo == 7


def test_osu_troll_curve_marker_letters_drops_object(load_fixture):
    """Regression test for a real "aspire"/troll beatmap (2568364) where one
    hit object survived in senku but not in the reference: a slider curve
    spelling out a word one letter-token at a time (e.g. "D|I|C|K|S|B|...",
    each letter a bare pipe-separated token with no coordinate). senku's
    curve parser silently treats any non-"x:y" token as "not a control
    point" and moves on -- but the reference's ConvertHitObjectParser reads
    each letter-first token as a new path-type marker, and two such markers
    landing on the same point-index (i.e. no real coordinate between them)
    make it build a zero-length control-point array and throw indexing into
    it, which drops the WHOLE hit object via the per-line try/catch in
    LegacyDecoder (see slider_curve_would_throw in _slider_path.py).
    """
    beatmap = parse_osu_file(load_fixture("std_troll_curve_marker_letters_edge_case.osu"))

    assert len(beatmap.objects) == 2  # the 2 normal circles; the troll slider is dropped
    assert all(o.kind.name == "CIRCLE" for o in beatmap.objects)

    attributes = calculate(beatmap)
    assert attributes.star_rating == pytest.approx(0.1547211959011954, rel=1e-9)
    assert attributes.max_combo == 2


def test_osu_extreme_bpm_timing_point_is_clamped(load_fixture):
    """Regression test for the residual gap left after the extreme-slider-length
    fix on beatmap 2536330 (star_rating went from 9,969,497 to a still-off
    163.68 after dropping the extreme sliders, vs the map's real official
    176.73). Root cause confirmed via decompile: `TimingControlPoint.BeatLength`
    and `DifficultyControlPoint.SliderVelocity` are both clamped `BindableDouble`s
    in the reference ([6, 60000] and [0.1, 10] respectively, not used at face
    value) -- a troll timing point declaring beat_length=3.341 (~18000 BPM)
    silently becomes 6 (10000 BPM cap), same for an absurd SV multiplier.

    This fixture reproduces one specific real slider from that map exactly
    (same SliderMultiplier=1.7, same beat_length=3.341 timing point, same
    slider geometry/length) in isolation. Cross-validated against the real
    .NET PerformanceCalculator: velocity=28.333333333333332 (confirms both the
    BeatLength clamp -- unclamped would give velocity=50.883 -- and
    GenerateTicks=false suppressing all ticks, nested=2).
    """
    beatmap = parse_osu_file(load_fixture("std_extreme_bpm_timing_point_edge_case.osu"))
    from senku.osu.beatmap import OsuObjectKind
    slider = next(o for o in beatmap.objects if o.kind == OsuObjectKind.SLIDER)

    assert slider.velocity == pytest.approx(28.333333333333332, rel=1e-9)
    assert len(slider.nested) == 2  # head + tail only, ticks suppressed by GenerateTicks=false

    attributes = calculate(beatmap)
    assert attributes.star_rating == pytest.approx(0.119846523006125, rel=1e-9)
    assert attributes.max_combo == 3
