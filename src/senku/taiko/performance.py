"""osu!taiko performance (pp) calculation.

Estimates a player's true tap-timing deviation from their accuracy
(via a statistical confidence-bound method), then converts star rating
+ estimated deviation into difficulty pp and accuracy pp components.
Independent implementation; not adapted from any specific codebase.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .._diffutils import erf, erf_inv, logistic_full, SQRT2
from .difficulty import TaikoDifficultyAttributes
from .preprocessing import performance_great_hit_window_for

_Z_99_CONFIDENCE = 2.32634787404


@dataclass(frozen=True)
class TaikoJudgements:
    n_great: int = 0
    n_ok: int = 0
    n_meh: int = 0
    n_miss: int = 0

    @property
    def total_hits(self) -> int:
        return self.n_great + self.n_ok + self.n_meh + self.n_miss


def _compute_deviation_upper_bound(accuracy: float, total_hits: int, great_hit_window: float) -> float:
    n = total_hits
    p = accuracy
    z = _Z_99_CONFIDENCE

    p_lower_bound = (n * p + z * z / 2) / (n + z * z) - z / (n + z * z) * math.sqrt(n * p * (1 - p) + z * z / 4)
    return great_hit_window / (SQRT2 * erf_inv(p_lower_bound))


def calculate_pp(
    attributes: TaikoDifficultyAttributes,
    judgements: TaikoJudgements,
    overall_difficulty: float,
    clock_rate: float = 1.0,
    hidden: bool = False,
    flashlight: bool = False,
    easy: bool = False,
    is_convert: bool = False,
    is_classic: bool = False,
) -> dict:
    total_hits = judgements.total_hits
    # Deliberately NOT attributes.great_hit_window (that's doubled, for the
    # difficulty engine's internal use) -- the performance calculator computes
    # its own un-doubled hit window independently.
    great_hit_window = performance_great_hit_window_for(overall_difficulty, clock_rate)

    if judgements.n_great == 0 or great_hit_window <= 0 or total_hits == 0:
        estimated_unstable_rate = None
    else:
        estimated_unstable_rate = _compute_deviation_upper_bound(judgements.n_great / total_hits, total_hits, great_hit_window) * 10

    total_difficult_hits = total_hits * attributes.consistency_factor

    difficulty_value = _compute_difficulty_value(
        attributes, judgements, estimated_unstable_rate, total_difficult_hits, total_hits,
        hidden, flashlight, easy, is_convert, is_classic, great_hit_window,
    ) * 1.08
    accuracy_value = _compute_accuracy_value(
        attributes, estimated_unstable_rate, total_difficult_hits, total_hits, hidden, flashlight, is_convert,
    ) * 1.1

    return {
        "difficulty": difficulty_value,
        "accuracy": accuracy_value,
        "estimated_unstable_rate": estimated_unstable_rate,
        "total": difficulty_value + accuracy_value,
    }


def _compute_difficulty_value(attributes, judgements, estimated_unstable_rate, total_difficult_hits, total_hits,
                                hidden, flashlight, easy, is_convert, is_classic, great_hit_window) -> float:
    if estimated_unstable_rate is None or total_difficult_hits == 0:
        return 0.0

    rhythm_expected_ur = _compute_deviation_upper_bound(1.0, total_hits, great_hit_window) * 10
    rhythm_maximum_ur = _compute_deviation_upper_bound(0.8, total_hits, great_hit_window) * 10

    rhythm_factor = _reverse_lerp(attributes.rhythm_difficulty / attributes.star_rating, 0.15, 0.4) if attributes.star_rating > 0 else 0.0

    rhythm_penalty = 1 - logistic_full(
        estimated_unstable_rate,
        (rhythm_expected_ur + rhythm_maximum_ur) / 2,
        10 / (rhythm_maximum_ur - rhythm_expected_ur),
        0.25 * pow(rhythm_factor, 3),
    )

    base_difficulty = 5 * max(1.0, attributes.star_rating * rhythm_penalty / 0.110) - 4.0
    difficulty_value = min(pow(base_difficulty, 3) / 69052.51, pow(base_difficulty, 2.25) / 1250.0)

    difficulty_value *= 1 + 0.10 * max(0.0, attributes.star_rating - 10)

    length_bonus = 1 + 0.25 * total_difficult_hits / (total_difficult_hits + 4000)
    difficulty_value *= length_bonus

    miss_penalty = 0.97 + 0.03 * total_difficult_hits / (total_difficult_hits + 1500)
    difficulty_value *= pow(miss_penalty, judgements.n_miss)

    if hidden:
        hidden_bonus = 0.025 if is_convert else 0.1
        if not flashlight:
            if not is_classic:
                hidden_bonus *= 0.2
            if easy and is_classic:
                hidden_bonus *= 0.5
        difficulty_value *= 1 + hidden_bonus

    if flashlight:
        difficulty_value *= max(1.0, 1.050 - min(attributes.mono_stamina_factor / 50, 1) * length_bonus)

    mono_acc_scaling_exponent = 2 + attributes.mono_stamina_factor
    mono_acc_scaling_shift = 500 - 100 * (attributes.mono_stamina_factor * 3)

    return difficulty_value * pow(
        erf(mono_acc_scaling_shift / (SQRT2 * estimated_unstable_rate)), mono_acc_scaling_exponent
    )


def _compute_accuracy_value(attributes, estimated_unstable_rate, total_difficult_hits, total_hits,
                              hidden, flashlight, is_convert) -> float:
    if estimated_unstable_rate is None:
        return 0.0

    accuracy_value = 470 * pow(0.9885, estimated_unstable_rate)
    accuracy_value *= 1 + pow(50 / estimated_unstable_rate, 2) * pow(attributes.star_rating, 2.8) / 600

    if hidden and not is_convert:
        accuracy_value *= 1.075

    accuracy_value *= 1 + 0.3 * total_difficult_hits / (total_difficult_hits + 4000)

    memory_length_bonus = min(1.15, pow(total_hits / 1500.0, 0.3))
    if flashlight and hidden and not is_convert:
        accuracy_value *= max(1.0, 1.05 * memory_length_bonus)

    return accuracy_value


def _reverse_lerp(x: float, start: float, end: float) -> float:
    return min(max((x - start) / (end - start), 0.0), 1.0)
