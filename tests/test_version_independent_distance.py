"""senku must not depend on math.hypot.

CPython changed math.hypot's algorithm in 3.10, so identical inputs can differ in the last bit between
Python versions. Distances feed hard thresholds in the strain calculation (slider path lengths, jump
distances, lazy cursor movement), and that was enough to give different star ratings on 3.9 and 3.10 for
most osu!standard maps. Distances now go through senku._diffutils.hypot (plain sqrt(x*x + y*y)).
"""

import math

import pytest

from senku._diffutils import hypot
from senku.osu.beatmap import parse_osu_file
from senku.osu.difficulty import calculate


def test_hypot_helper_is_plain_arithmetic():
    for x, y in [(3.0, 4.0), (0.0, 0.0), (-5.5, 12.25), (1e-9, 3e-9), (123456.789, -98765.4321)]:
        assert hypot(x, y) == math.sqrt(x * x + y * y)


@pytest.mark.parametrize("fixture", ["5136658.osu", "2089432.osu"])
def test_difficulty_calculation_never_calls_math_hypot(monkeypatch, load_fixture, fixture):
    def boom(*args, **kwargs):
        raise AssertionError("senku called math.hypot; use senku._diffutils.hypot so results do not vary with the Python version")

    monkeypatch.setattr(math, "hypot", boom)
    parsed = parse_osu_file(load_fixture(fixture))
    attrs = calculate(parsed, clock_rate=1.0, hidden=False, flashlight=False, mods=frozenset())
    assert attrs.star_rating > 0
