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


# Relax (RX) support for catch, added below. Unlike the HR/EZ cases above, there is no
# official reference formula for catch RX to cross-validate against -- the real client's
# CatchModRelax is purely an input-remapping mod (mouse position -> catcher position, no
# difficulty/performance-calculator hook at all). These are first-guess heuristic values,
# pending calibration against real relax-catch community scores once more exist (current
# production usage is negligible). Assertions are qualitative (direction/ordering), not
# pinned to exact expected numbers.

def test_catch_relax_lowers_star_rating_and_preserves_combo(load_fixture):
    """Smoke test on a real map: RX must never change combo/judgement counts, and
    should not increase difficulty (it only removes/dampens movement-strain terms)."""
    beatmap = parse_osu_file(load_fixture("341072.osu"), mods=frozenset())
    nomod = calculate(beatmap)
    relaxed = calculate(beatmap, is_relax=True)

    assert relaxed.star_rating < nomod.star_rating
    assert relaxed.max_combo == nomod.max_combo


def test_catch_relax_dampens_direction_changes_more_than_monotonic_runs(load_fixture):
    """Isolates the two RX movement changes: a zigzag pattern (every object reverses
    direction, maximizing DIRECTION_CHANGE_BONUS's contribution) should see a bigger
    relative star_rating drop under RX than a monotonic run (never reverses, so only
    the flat /1.5 base dampening applies) -- confirms direction-change removal is the
    dominant RX-specific effect, not just the base dampening term.
    """
    zigzag = parse_osu_file(load_fixture("catch_rx_zigzag_edge_case.osu"), mods=frozenset())
    monotonic = parse_osu_file(load_fixture("catch_rx_monotonic_edge_case.osu"), mods=frozenset())

    zigzag_nomod = calculate(zigzag)
    zigzag_relax = calculate(zigzag, is_relax=True)
    monotonic_nomod = calculate(monotonic)
    monotonic_relax = calculate(monotonic, is_relax=True)

    assert zigzag_relax.star_rating < zigzag_nomod.star_rating
    assert monotonic_relax.star_rating < monotonic_nomod.star_rating

    zigzag_ratio = zigzag_relax.star_rating / zigzag_nomod.star_rating
    monotonic_ratio = monotonic_relax.star_rating / monotonic_nomod.star_rating
    assert zigzag_ratio < monotonic_ratio
