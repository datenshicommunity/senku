"""senku: another rhythm game performance calculator.

Pure-Python difficulty and performance (pp) calculation for a 4-mode
circle-clicking rhythm game. Each mode lives in its own submodule
(`senku.mania`, `senku.taiko`, `senku.catch`, `senku.osu`), each exposing
a `beatmap` parser, a `difficulty` calculator, and a `performance`
calculator with the same shape:

    from senku.osu.beatmap import parse_osu_file
    from senku.osu.difficulty import calculate
    from senku.osu.performance import calculate_pp, OsuJudgements

    beatmap = parse_osu_file(text)
    attributes = calculate(beatmap)
    pp = calculate_pp(attributes, OsuJudgements(n300=..., n100=..., n50=..., n_miss=...), ...)
"""

__version__ = "1.1.6"
