"""osu!catch performance (pp) calculation. Independent implementation;
not adapted from any specific codebase.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .difficulty import CatchDifficultyAttributes


@dataclass(frozen=True)
class CatchJudgements:
    n_fruit: int = 0  # count300 / Great
    n_large_droplet: int = 0  # count100
    n_small_droplet: int = 0  # count50
    n_small_droplet_miss: int = 0  # countkatu
    n_miss: int = 0  # countmiss (fruit miss + large droplet miss)


def _accuracy(j: CatchJudgements) -> float:
    total = total_hits(j)
    if total == 0:
        return 0.0
    successful = j.n_small_droplet + j.n_large_droplet + j.n_fruit
    return min(max(successful / total, 0.0), 1.0)


def total_hits(j: CatchJudgements) -> int:
    return j.n_small_droplet + j.n_large_droplet + j.n_fruit + j.n_miss + j.n_small_droplet_miss


def total_combo_hits(j: CatchJudgements) -> int:
    return j.n_miss + j.n_large_droplet + j.n_fruit


def calculate_pp(
    attributes: CatchDifficultyAttributes,
    judgements: CatchJudgements,
    max_combo_achieved: int,
    approach_rate: float,
    clock_rate: float = 1.0,
    hidden: bool = False,
    flashlight: bool = False,
    no_fail: bool = False,
) -> float:
    score_max_combo = min(max(max_combo_achieved, 0), attributes.max_combo)

    value = pow(5.0 * max(1.0, attributes.star_rating / 0.0049) - 4.0, 2.0) / 100000.0

    num_total_hits = total_combo_hits(judgements)

    length_bonus = 0.95 + 0.3 * min(1.0, num_total_hits / 2500.0) + (math.log10(num_total_hits / 2500.0) * 0.475 if num_total_hits > 2500 else 0.0)
    value *= length_bonus

    value *= pow(0.97, judgements.n_miss)

    if attributes.max_combo > 0:
        value *= min(pow(score_max_combo, 0.35) / pow(attributes.max_combo, 0.35), 1.0)

    # approach_rate is passed in already adjusted for clock rate / difficulty-adjusting mods.
    approach_rate_factor = 1.0
    if approach_rate > 9.0:
        approach_rate_factor += 0.1 * (approach_rate - 9.0)
    if approach_rate > 10.0:
        approach_rate_factor += 0.1 * (approach_rate - 10.0)
    elif approach_rate < 8.0:
        approach_rate_factor += 0.025 * (8.0 - approach_rate)

    value *= approach_rate_factor

    if hidden:
        if approach_rate <= 10.0:
            value *= 1.05 + 0.075 * (10.0 - approach_rate)
        else:
            value *= 1.01 + 0.04 * (11.0 - min(11.0, approach_rate))

    if flashlight:
        value *= 1.35 * length_bonus

    value *= pow(_accuracy(judgements), 5.5)

    if no_fail:
        value *= max(0.90, 1.0 - 0.02 * judgements.n_miss)

    return value


def preempt_to_approach_rate(preempt_ms: float) -> float:
    if preempt_ms > 1200.0:
        return -(preempt_ms - 1800.0) / 120.0
    return -(preempt_ms - 1200.0) / 150.0 + 5.0


def difficulty_range(difficulty: float, min_value: float, mid_value: float, max_value: float) -> float:
    if difficulty > 5:
        return mid_value + (max_value - mid_value) * (difficulty - 5) / 5
    if difficulty < 5:
        return mid_value - (mid_value - min_value) * (5 - difficulty) / 5
    return mid_value
