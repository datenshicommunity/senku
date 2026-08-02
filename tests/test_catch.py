"""Regression tests for senku.catch, pinned to values cross-validated
against real leaderboard scores at authoring time.
"""

import pytest

from senku.catch.beatmap import parse_osu_file
from senku.catch.difficulty import calculate
from senku.catch.performance import CatchJudgements, calculate_pp

CASES = [
    pytest.param(
        "341072.osu", frozenset(),
        dict(n_fruit=983, n_large_droplet=0, n_small_droplet=242, n_small_droplet_miss=0, n_miss=0),
        983,
        5.272840742728842,
        308.7067793217544,
        id="341072-nomod",
    ),
    pytest.param(
        "4921835.osu", frozenset(),
        dict(n_fruit=2544, n_large_droplet=77, n_small_droplet=79, n_small_droplet_miss=1, n_miss=1),
        2592,
        10.075895854357011,
        1408.4302505955438,
        id="4921835-nomod",
    ),
    # EZ scales CS/AR only (no RNG position jitter). Cross-validated against the
    # real .NET PerformanceCalculator: sr=4.742913161042276, pp=271.58405274144184.
    pytest.param(
        "341072.osu", frozenset({"EZ"}),
        dict(n_fruit=983, n_large_droplet=0, n_small_droplet=242, n_small_droplet_miss=0, n_miss=0),
        983,
        4.742912785864638,
        271.58400973979326,
        id="341072-EZ",
    ),
    # HR scales CS/AR (standard formula) AND runs CatchBeatmapProcessor's legacy
    # xorshift-RNG position-jitter pass (seed 1337) on every fruit/tiny-droplet/
    # banana in time order -- see _legacy_random.py + beatmap.py's
    # _apply_hard_rock_offset/_apply_random_offset/_apply_offset. Cross-validated
    # against the real .NET PerformanceCalculator: sr=5.491569610510469,
    # pp=368.35644056973155 (~3e-8 / ~6e-8 relative diff).
    pytest.param(
        "341072.osu", frozenset({"HR"}),
        dict(n_fruit=983, n_large_droplet=0, n_small_droplet=242, n_small_droplet_miss=0, n_miss=0),
        983,
        5.4915694384648175,
        368.35641747273104,
        id="341072-HR",
    ),
]


@pytest.mark.parametrize("fixture_name, mods, judgements, combo, expected_sr, expected_pp", CASES)
def test_catch_star_rating_and_pp(load_fixture, fixture_name, mods, judgements, combo, expected_sr, expected_pp):
    beatmap = parse_osu_file(load_fixture(fixture_name), mods=mods)
    attributes = calculate(beatmap)
    pp = calculate_pp(attributes, CatchJudgements(**judgements), max_combo_achieved=combo, approach_rate=beatmap.approach_rate)

    assert attributes.star_rating == pytest.approx(expected_sr, rel=1e-9)
    assert pp == pytest.approx(expected_pp, rel=1e-9)


# Relax (RX) support for catch, checked below. An earlier version of this module
# dampened movement-strain terms for is_relax=True as a first-guess heuristic (no
# official reference existed to check it against at the time). Verified directly
# against the official client source since (ppy/osu, checked 2026-08-02):
# CatchDifficultyCalculator.cs and CatchPerformanceCalculator.cs contain zero
# relax-mod-aware code -- unlike osu's Aim/Speed/Flashlight/Reading skills and
# OsuPerformanceCalculator, or taiko's TaikoDifficultyCalculator, which all do.
# CatchModRelax only hooks CatchScoreMultiplierCalculator (legacy scoring, 0.1x)
# and gameplay input remapping -- never difficulty/pp. is_relax is now a
# confirmed no-op for catch, matching the real game exactly, not a heuristic.

def test_catch_relax_matches_nomod(load_fixture):
    """is_relax must produce byte-identical output to nomod for catch -- the official
    client has no relax-aware catch difficulty/performance code at all (see module
    comment above), so unlike osu/taiko, there is nothing for senku to model here."""
    beatmap = parse_osu_file(load_fixture("341072.osu"), mods=frozenset())
    nomod = calculate(beatmap)
    relaxed = calculate(beatmap, is_relax=True)

    assert relaxed.star_rating == nomod.star_rating
    assert relaxed.max_combo == nomod.max_combo


def test_catch_relax_matches_nomod_direction_change_patterns(load_fixture):
    """Same as test_catch_relax_matches_nomod, on the zigzag/monotonic movement-pattern
    fixtures that used to isolate the (now-removed) RX-specific dampening terms --
    kept as regression coverage that is_relax is a true no-op regardless of movement
    pattern, not just on one map."""
    zigzag = parse_osu_file(load_fixture("catch_rx_zigzag_edge_case.osu"), mods=frozenset())
    monotonic = parse_osu_file(load_fixture("catch_rx_monotonic_edge_case.osu"), mods=frozenset())

    assert calculate(zigzag, is_relax=True).star_rating == calculate(zigzag).star_rating
    assert calculate(monotonic, is_relax=True).star_rating == calculate(monotonic).star_rating
