"""osu!std performance (pp) calculation. Assumes "classic slider accuracy"
(ModClassic default). Uses the score-based legacy miss estimator when a
real legacy total score is provided (matching real replayed legacy scores),
falling back to the combo-based heuristic otherwise. Independent
implementation; not adapted from any specific codebase.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .._diffutils import erf, erf_inv, logistic_full, norm, reverse_lerp, smoothstep, SQRT2
from .difficulty import OsuDifficultyAttributes, difficulty_to_performance, sum_cognition_difficulty
from .legacy_score import calculate_score_based_miss_count, get_legacy_score_multiplier

PERFORMANCE_NORM_EXPONENT = 1.1


@dataclass(frozen=True)
class OsuJudgements:
    n300: int = 0
    n100: int = 0
    n50: int = 0
    n_miss: int = 0


def _difficulty_range(difficulty: float, min_value: float, mid_value: float, max_value: float) -> float:
    if difficulty > 5:
        return mid_value + (max_value - mid_value) * (difficulty - 5) / 5
    if difficulty < 5:
        return mid_value - (mid_value - min_value) * (5 - difficulty) / 5
    return mid_value


def _inverse_difficulty_range(value: float, diff0: float, diff5: float, diff10: float) -> float:
    sign_a = (value - diff5 > 0) - (value - diff5 < 0)
    sign_b = (diff10 - diff5 > 0) - (diff10 - diff5 < 0)
    if sign_a == sign_b:
        return (value - diff5) / (diff10 - diff5) * 5 + 5
    return (value - diff5) / (diff5 - diff0) * 5 + 5


def total_hits(j: OsuJudgements) -> int:
    return j.n300 + j.n100 + j.n50 + j.n_miss


def total_successful_hits(j: OsuJudgements) -> int:
    return j.n300 + j.n100 + j.n50


def total_imperfect_hits(j: OsuJudgements) -> int:
    return j.n100 + j.n50 + j.n_miss


def _miss_penalty(miss_count: float, difficult_strain_count: float) -> float:
    log_term = math.log(max(1.0, difficult_strain_count))
    if log_term == 0:
        # Matches C# double semantics: x/0 with x>0 -> +Inf, 0/0 -> NaN (Python raises instead of doing this silently).
        ratio = math.inf if miss_count > 0 else (math.nan if miss_count == 0 else -math.inf)
    else:
        ratio = miss_count / (4 * log_term)
    return 0.93 / (ratio + 1)


def _combo_scaling_factor(attributes: OsuDifficultyAttributes, score_max_combo: int) -> float:
    if attributes.max_combo <= 0:
        return 1.0
    return min(pow(score_max_combo, 0.8) / pow(attributes.max_combo, 0.8), 1.0)


def calculate_pp(
    attributes: OsuDifficultyAttributes,
    judgements: OsuJudgements,
    score_max_combo: int,
    approach_rate: float,
    overall_difficulty_raw: float,
    clock_rate: float = 1.0,
    flashlight: bool = False,
    legacy_total_score: float | None = None,
    mods: frozenset[str] = frozenset(),
    score_v2: bool = False,
    drain_rate: float = 5.0,
) -> float:
    accuracy = min(max(_accuracy(judgements), 0.0), 1.0)
    score_max_combo = min(max(score_max_combo, 0), attributes.max_combo)

    count_great, count_ok, count_meh, count_miss = judgements.n300, judgements.n100, judgements.n50, judgements.n_miss
    hits = total_hits(judgements)
    imperfect_hits = total_imperfect_hits(judgements)

    great_hit_window = (math.floor(_difficulty_range(overall_difficulty_raw, 80.0, 50.0, 20.0)) - 0.5) / clock_rate
    ok_hit_window = (math.floor(_difficulty_range(overall_difficulty_raw, 140.0, 100.0, 60.0)) - 0.5) / clock_rate
    meh_hit_window = (math.floor(_difficulty_range(overall_difficulty_raw, 200.0, 150.0, 100.0)) - 0.5) / clock_rate

    rate_adjusted_approach_rate = _calculate_rate_adjusted_approach_rate(approach_rate, clock_rate)
    overall_difficulty = (79.5 - great_hit_window) / 6

    # Assumes ModClassic defaults (usingClassicSliderAccuracy=True), no ScoreV2 unless requested.
    combo_based_estimated_miss_count = _calculate_combo_based_estimated_miss_count(attributes, judgements, score_max_combo)

    if legacy_total_score is not None:
        legacy_score_multiplier = get_legacy_score_multiplier(mods, score_v2)
        effective_miss_count = calculate_score_based_miss_count(
            max_combo=attributes.max_combo, slider_count=attributes.slider_count,
            aim_top_weighted_slider_factor=attributes.aim_top_weighted_slider_factor,
            legacy_score_base_multiplier=attributes.legacy_score_base_multiplier,
            legacy_score_multiplier=legacy_score_multiplier,
            maximum_legacy_combo_score=attributes.maximum_legacy_combo_score,
            nested_score_per_object=attributes.nested_score_per_object,
            score_max_combo=score_max_combo, legacy_total_score=legacy_total_score, accuracy=accuracy,
            count_great=count_great, count_ok=count_ok, count_meh=count_meh, count_miss=count_miss,
        )
    else:
        effective_miss_count = combo_based_estimated_miss_count

    effective_miss_count = max(count_miss, effective_miss_count)
    effective_miss_count = min(hits, effective_miss_count)
    effective_miss_count = max(0.0, effective_miss_count)

    aim_estimated_slider_breaks = 0.0
    speed_estimated_slider_breaks = 0.0
    if effective_miss_count > 0:
        aim_estimated_slider_breaks = _calculate_estimated_slider_breaks(attributes.aim_top_weighted_slider_factor, attributes, judgements, score_max_combo, effective_miss_count)
        speed_estimated_slider_breaks = _calculate_estimated_slider_breaks(attributes.speed_top_weighted_slider_factor, attributes, judgements, score_max_combo, effective_miss_count)

    multiplier = 1.12  # PERFORMANCE_BASE_MULTIPLIER

    if "NF" in mods:
        multiplier *= max(0.90, 1.0 - 0.02 * effective_miss_count)

    if "SO" in mods and hits > 0:
        multiplier *= 1.0 - pow(attributes.spinner_count / hits, 0.85)

    if "RX" in mods:
        # OD13.33 is where the great hit window becomes 0 -- beyond the max achievable OD (DTx2 + DA OD11 ~= 12.17).
        ok_multiplier = 0.75 * max(0.0, 1 - overall_difficulty / 13.33 if overall_difficulty > 0.0 else 1.0)
        meh_multiplier = max(0.0, 1 - pow(overall_difficulty / 13.33, 5) if overall_difficulty > 0.0 else 1.0)
        effective_miss_count = min(effective_miss_count + count_ok * ok_multiplier + count_meh * meh_multiplier, hits)

    speed_deviation = _calculate_speed_deviation(attributes, judgements, hits, great_hit_window, ok_hit_window, meh_hit_window)

    aim_value = _compute_aim_value(attributes, judgements, imperfect_hits, hits, score_max_combo, accuracy, effective_miss_count, aim_estimated_slider_breaks,
                                    mods=mods, drain_rate=drain_rate, rate_adjusted_approach_rate=rate_adjusted_approach_rate)
    speed_value = _compute_speed_value(attributes, imperfect_hits, effective_miss_count, speed_estimated_slider_breaks, speed_deviation, mods=mods)
    accuracy_value = _compute_accuracy_value(attributes, judgements, hits, overall_difficulty, mods=mods, score_v2=score_v2, rate_adjusted_approach_rate=rate_adjusted_approach_rate)

    reading_value = _compute_reading_value(attributes, accuracy, effective_miss_count, aim_estimated_slider_breaks)
    flashlight_value = _compute_flashlight_value(attributes, hits, score_max_combo, accuracy, effective_miss_count) if flashlight else 0.0
    cognition_value = sum_cognition_difficulty(reading_value, flashlight_value)

    total_value = norm(PERFORMANCE_NORM_EXPONENT, aim_value, speed_value, accuracy_value, cognition_value) * multiplier

    return total_value


def _accuracy(j: OsuJudgements) -> float:
    hits = total_hits(j)
    if hits == 0:
        return 0.0
    return (j.n300 * 6 + j.n100 * 2 + j.n50) / (hits * 6)


def _calculate_rate_adjusted_approach_rate(approach_rate: float, clock_rate: float) -> float:
    preempt = _difficulty_range(approach_rate, 1800.0, 1200.0, 450.0) / clock_rate
    return _inverse_difficulty_range(preempt, 1800.0, 1200.0, 450.0)


def _calculate_combo_based_estimated_miss_count(attributes: OsuDifficultyAttributes, j: OsuJudgements, score_max_combo: int) -> float:
    if attributes.slider_count <= 0:
        return j.n_miss

    miss_count = float(j.n_miss)

    likely_missed_sliderend_portion = 0.04 + 0.06 * pow(min(attributes.aim_top_weighted_slider_factor, 1.0), 2)
    full_combo_threshold = attributes.max_combo - min(4 + likely_missed_sliderend_portion * attributes.slider_count, attributes.slider_count)

    if score_max_combo < full_combo_threshold:
        miss_count = full_combo_threshold / max(1.0, score_max_combo)

    miss_count = min(miss_count, total_imperfect_hits(j))

    max_possible_slider_breaks = min(attributes.slider_count, (attributes.max_combo - score_max_combo) // 2)

    slider_breaks = miss_count - j.n_miss
    if slider_breaks > max_possible_slider_breaks:
        miss_count = j.n_miss + max_possible_slider_breaks

    return miss_count


def _calculate_estimated_slider_breaks(top_weighted_slider_factor: float, attributes: OsuDifficultyAttributes, j: OsuJudgements, score_max_combo: int, effective_miss_count: float) -> float:
    non_miss_mistakes = j.n100 + j.n50
    if non_miss_mistakes == 0:
        return 0.0

    missed_combo_percent = 1.0 - score_max_combo / attributes.max_combo
    estimated_slider_breaks = min(non_miss_mistakes, effective_miss_count * top_weighted_slider_factor)

    non_miss_mistake_adjustment = (non_miss_mistakes - estimated_slider_breaks + 4.5) / (non_miss_mistakes + 4)

    estimated_slider_breaks *= smoothstep(effective_miss_count, 1, 2)

    return estimated_slider_breaks * non_miss_mistake_adjustment * logistic_full(missed_combo_percent, 0.33, 15)


def _calculate_deviation(great_hit_window: float, ok_hit_window: float, meh_hit_window: float,
                          relevant_great: float, relevant_ok: float, relevant_meh: float) -> float | None:
    if relevant_great + relevant_ok + relevant_meh <= 0:
        return None

    n = max(1.0, relevant_great + relevant_ok)
    p = relevant_great / n

    z = 2.32634787404

    p_lower_bound = min(p, (n * p + z * z / 2) / (n + z * z) - z / (n + z * z) * math.sqrt(n * p * (1 - p) + z * z / 4))

    if p_lower_bound > 0.01:
        deviation = great_hit_window / (SQRT2 * erf_inv(p_lower_bound))
        ok_hit_window_tail_amount = (
            math.sqrt(2 / math.pi) * ok_hit_window * math.exp(-0.5 * pow(ok_hit_window / deviation, 2))
            / (deviation * erf(ok_hit_window / (SQRT2 * deviation)))
        )
        deviation *= math.sqrt(1 - ok_hit_window_tail_amount)
    else:
        deviation = ok_hit_window / math.sqrt(3)

    meh_variance = (meh_hit_window * meh_hit_window + ok_hit_window * meh_hit_window + ok_hit_window * ok_hit_window) / 3

    deviation = math.sqrt(((relevant_great + relevant_ok) * pow(deviation, 2) + relevant_meh * meh_variance) / (relevant_great + relevant_ok + relevant_meh))

    return deviation


def _calculate_speed_deviation(attributes: OsuDifficultyAttributes, j: OsuJudgements, hits: int,
                                great_hit_window: float, ok_hit_window: float, meh_hit_window: float) -> float | None:
    if total_successful_hits(j) == 0:
        return None

    speed_note_count = attributes.speed_note_count
    speed_note_count += (hits - attributes.speed_note_count) * 0.1

    relevant_count_miss = min(j.n_miss, speed_note_count)
    relevant_count_meh = min(j.n50, speed_note_count - relevant_count_miss)
    relevant_count_ok = min(j.n100, speed_note_count - relevant_count_miss - relevant_count_meh)
    relevant_count_great = max(0.0, speed_note_count - relevant_count_miss - relevant_count_meh - relevant_count_ok)

    return _calculate_deviation(great_hit_window, ok_hit_window, meh_hit_window, relevant_count_great, relevant_count_ok, relevant_count_meh)


def _compute_aim_value(attributes: OsuDifficultyAttributes, j: OsuJudgements, imperfect_hits: int, hits: int, score_max_combo: int,
                        accuracy: float, effective_miss_count: float, aim_estimated_slider_breaks: float,
                        mods: frozenset[str] = frozenset(), drain_rate: float = 5.0, rate_adjusted_approach_rate: float = 10.0) -> float:
    if "AP" in mods:
        return 0.0

    aim_difficulty = attributes.aim_difficulty

    if attributes.slider_count > 0 and attributes.aim_difficult_slider_count > 0:
        maximum_possible_dropped_sliders = imperfect_hits
        estimate_improperly_followed_difficult_sliders = min(max(min(maximum_possible_dropped_sliders, attributes.max_combo - score_max_combo), 0.0), attributes.aim_difficult_slider_count)

        slider_nerf_factor = (1 - attributes.slider_factor) * pow(1 - estimate_improperly_followed_difficult_sliders / attributes.aim_difficult_slider_count, 3) + attributes.slider_factor
        aim_difficulty *= slider_nerf_factor

    aim_value = difficulty_to_performance(aim_difficulty)

    length_bonus = 0.95 + 0.35 * min(1.0, hits / 2000.0) + (math.log10(hits / 2000.0) * 0.5 if hits > 2000 else 0.0)
    aim_value *= length_bonus

    if effective_miss_count > 0:
        # countSliderTickMiss is always 0 for classic/legacy scores (statistics dict has no
        # LargeTickMiss entry), so relevant_miss_count reduces to just imperfect_hits here.
        relevant_miss_count = min(effective_miss_count + aim_estimated_slider_breaks, imperfect_hits)
        aim_value *= _miss_penalty(relevant_miss_count, attributes.aim_difficult_strain_count)

    # TC bonuses are excluded when Blinds is present -- increased visual difficulty is unimportant when notes can't be seen.
    if "BL" in mods:
        aim_value *= 1.3 + (hits * (0.0016 / (1 + 2 * effective_miss_count)) * pow(accuracy, 16)) * (1 - 0.003 * drain_rate * drain_rate)
    elif "TC" in mods:
        aim_value *= 1.0 + _calculate_traceable_bonus(rate_adjusted_approach_rate, attributes.slider_factor)

    aim_value *= accuracy

    return aim_value


def _calculate_traceable_bonus(approach_rate: float, slider_factor: float = 1.0) -> float:
    high_ar_slider_visibility_factor = 0.5 + (pow(slider_factor, 6) / 2)
    low_ar_slider_visibility_factor = pow(slider_factor, 6)

    traceable_bonus = 0.0275
    traceable_bonus += 0.025 * (12.0 - max(approach_rate, 7.0)) * high_ar_slider_visibility_factor

    if approach_rate < 7:
        traceable_bonus += 0.025 * (7.0 - max(approach_rate, 0.0)) * low_ar_slider_visibility_factor

    if approach_rate < 0:
        traceable_bonus += 0.025 * (1 - pow(1.5, approach_rate)) * low_ar_slider_visibility_factor

    return traceable_bonus


def _compute_speed_value(attributes: OsuDifficultyAttributes, imperfect_hits: int, effective_miss_count: float,
                          speed_estimated_slider_breaks: float, speed_deviation: float | None, mods: frozenset[str] = frozenset()) -> float:
    if "RX" in mods or speed_deviation is None:
        return 0.0

    speed_value = difficulty_to_performance(attributes.speed_difficulty)

    if effective_miss_count > 0:
        relevant_miss_count = min(effective_miss_count + speed_estimated_slider_breaks, imperfect_hits)
        speed_value *= _miss_penalty(relevant_miss_count, attributes.speed_difficult_strain_count)

    if "BL" in mods:
        # Increasing the speed value by object count for Blinds isn't ideal, so the minimum buff is given.
        speed_value *= 1.12

    speed_high_deviation_multiplier = _calculate_speed_high_deviation_nerf(attributes, speed_deviation)
    speed_value *= speed_high_deviation_multiplier

    effective_hit_window = 20 * pow(4 / attributes.speed_difficulty, 0.35)
    effective_accuracy = erf(effective_hit_window / speed_deviation)
    speed_value *= pow(effective_accuracy, 2)

    return speed_value


def _calculate_speed_high_deviation_nerf(attributes: OsuDifficultyAttributes, speed_deviation: float | None) -> float:
    if speed_deviation is None:
        return 0.0

    speed_value = difficulty_to_performance(attributes.speed_difficulty)

    excess_speed_difficulty_cutoff = 100 + 220 * pow(22 / speed_deviation, 6.5)

    if speed_value <= excess_speed_difficulty_cutoff:
        return 1.0

    scale = 50.0
    adjusted_speed_value = scale * (math.log((speed_value - excess_speed_difficulty_cutoff) / scale + 1) + excess_speed_difficulty_cutoff / scale)

    lerp = 1 - reverse_lerp(speed_deviation, 22.0, 27.0)
    adjusted_speed_value = adjusted_speed_value + (speed_value - adjusted_speed_value) * lerp

    return adjusted_speed_value / speed_value


def _compute_accuracy_value(attributes: OsuDifficultyAttributes, j: OsuJudgements, hits: int, overall_difficulty: float,
                             mods: frozenset[str] = frozenset(), score_v2: bool = False, rate_adjusted_approach_rate: float = 10.0) -> float:
    if "RX" in mods:
        return 0.0

    amount_hit_objects_with_accuracy = attributes.hit_circle_count  # usingClassicSliderAccuracy=True (ModClassic default): sliders excluded, unless ScoreV2.
    if score_v2:
        amount_hit_objects_with_accuracy += attributes.slider_count

    if amount_hit_objects_with_accuracy > 0:
        better_accuracy_percentage = ((j.n300 - max(hits - amount_hit_objects_with_accuracy, 0)) * 6 + j.n100 * 2 + j.n50) / (amount_hit_objects_with_accuracy * 6)
    else:
        better_accuracy_percentage = 0.0

    if better_accuracy_percentage < 0:
        better_accuracy_percentage = 0.0

    accuracy_value = pow(1.52163, overall_difficulty) * pow(better_accuracy_percentage, 24) * 2.83

    accuracy_value *= pow(amount_hit_objects_with_accuracy / 1000.0, 0.3) if amount_hit_objects_with_accuracy < 1000 else pow(amount_hit_objects_with_accuracy / 1000.0, 0.1)

    if "BL" in mods:
        # Increasing the accuracy value by object count for Blinds isn't ideal, so the minimum buff is given.
        accuracy_value *= 1.14
    elif "TC" in mods:
        # Decrease bonus for AR > 10.
        accuracy_value *= 1 + 0.08 * reverse_lerp(rate_adjusted_approach_rate, 11.5, 10.0)

    return accuracy_value


def _compute_reading_value(attributes: OsuDifficultyAttributes, accuracy: float, effective_miss_count: float, aim_estimated_slider_breaks: float) -> float:
    reading_value = difficulty_to_performance(attributes.reading_difficulty)

    if effective_miss_count > 0:
        reading_value *= _miss_penalty(effective_miss_count + aim_estimated_slider_breaks, attributes.reading_difficult_note_count)

    reading_value *= pow(accuracy, 3)

    return reading_value


def _compute_flashlight_value(attributes: OsuDifficultyAttributes, hits: int, score_max_combo: int, accuracy: float, effective_miss_count: float) -> float:
    flashlight_value = 25 * pow(attributes.flashlight_difficulty, 2)  # Flashlight.DifficultyToPerformance

    if effective_miss_count > 0:
        flashlight_value *= 0.97 * pow(1 - pow(effective_miss_count / hits, 0.775), pow(effective_miss_count, 0.875))

    flashlight_value *= _combo_scaling_factor(attributes, score_max_combo)
    flashlight_value *= 0.5 + accuracy / 2.0

    return flashlight_value
