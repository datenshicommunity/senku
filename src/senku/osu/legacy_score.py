"""osu!std legacy (ScoreV1) score simulation, used only to estimate a more
precise miss count from a real legacy score's total score value (when
combo was broken) than the plain combo-based heuristic can provide.
Independent implementation; not adapted from any specific codebase.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal

from .beatmap import OsuBeatmap, OsuObjectKind

_MOD_MULTIPLIERS = {
    # acronym -> (non_scorev2_multiplier, scorev2_multiplier)
    "EZ": (0.5, 0.5),
    "HT": (0.3, 0.3),
    "HD": (1.06, 1.06),
    "HR": (1.06, 1.10),
    "DT": (1.12, 1.20),
    "FL": (1.12, 1.12),
    "SO": (0.9, 0.9),
}


def get_legacy_score_multiplier(mods: frozenset[str], score_v2: bool = False) -> float:
    if "RX" in mods or "AP" in mods:
        return 0.0

    multiplier = 1.0

    if "NF" in mods:
        multiplier *= 1.0 if score_v2 else 0.5

    for acronym, (non_v2, v2) in _MOD_MULTIPLIERS.items():
        if acronym in mods:
            multiplier *= v2 if score_v2 else non_v2

    return multiplier


def calculate_difficulty_peppy_stars(circle_size: float, overall_difficulty: float, drain_rate: float,
                                      object_count: int, drain_length: int) -> int:
    if drain_length != 0:
        ratio = Decimal(object_count) / Decimal(drain_length) * 8
        object_to_drain_ratio = min(max(ratio, Decimal(0)), Decimal(16))
    else:
        object_to_drain_ratio = Decimal(16)

    drain_rate_d = Decimal(str(drain_rate))
    od_d = Decimal(str(overall_difficulty))
    cs_d = Decimal(str(circle_size))

    total = (drain_rate_d + od_d + cs_d + object_to_drain_ratio) / Decimal(38) * Decimal(5)
    return int(total.to_integral_value(rounding=ROUND_HALF_EVEN))


def _drain_length(beatmap: OsuBeatmap) -> int:
    if not beatmap.objects:
        return 0
    break_length = sum(int(round(e)) - int(round(s)) for s, e in beatmap.breaks)
    return (int(round(beatmap.objects[-1].start_time)) - int(round(beatmap.objects[0].start_time)) - break_length) // 1000


def calculate_difficulty_peppy_stars_for(beatmap: OsuBeatmap) -> int:
    object_count = len(beatmap.objects)
    return calculate_difficulty_peppy_stars(beatmap.circle_size, beatmap.overall_difficulty, beatmap.drain_rate,
                                             object_count, _drain_length(beatmap))


def calculate_spinner_score(duration_ms: float) -> float:
    spin_score = 100
    bonus_spin_score = 1000

    maximum_rotations_per_second = 477.0 / 60
    minimum_rotations_per_second = 3.0

    seconds_duration = duration_ms / 1000

    total_half_spins_possible = int(seconds_duration * maximum_rotations_per_second * 2)
    half_spins_required_for_completion = int(seconds_duration * minimum_rotations_per_second)
    half_spins_required_before_bonus = half_spins_required_for_completion + 3

    full_spins = total_half_spins_possible // 2

    score = spin_score * full_spins

    bonus_spins = (total_half_spins_possible - half_spins_required_before_bonus) // 2
    bonus_spins = max(0, bonus_spins - full_spins // 2)

    score += bonus_spin_score * bonus_spins

    return float(score)


def calculate_nested_score_per_object(beatmap: OsuBeatmap) -> float:
    big_tick_score = 30
    small_tick_score = 10

    amount_of_big_ticks = 0
    amount_of_small_ticks = 0
    spinner_score = 0.0

    for o in beatmap.objects:
        if o.kind == OsuObjectKind.SLIDER:
            amount_of_big_ticks += 2 + o.repeat_count
            amount_of_small_ticks += sum(1 for n in o.nested if n.kind.name == "TICK")
        elif o.kind == OsuObjectKind.SPINNER:
            spinner_score += calculate_spinner_score(o.end_time - o.start_time)

    slider_score = amount_of_big_ticks * big_tick_score + amount_of_small_ticks * small_tick_score

    object_count = len(beatmap.objects)
    if object_count == 0:
        return 0.0
    return (slider_score + spinner_score) / object_count


def simulate_combo_score(beatmap: OsuBeatmap, score_multiplier: int) -> int:
    """Returns the ScoreV1 "combo score" portion accumulated across the whole
    beatmap at full combo -- i.e. attributes.MaximumLegacyComboScore.
    """
    combo = 0
    combo_score = 0
    per_hit_base = 300 // 25 * score_multiplier  # constant: only HitCircle/Slider/Spinner add combo score, all scoreIncrease=300

    for o in beatmap.objects:
        if o.kind == OsuObjectKind.SLIDER:
            combo += len(o.nested)  # head/ticks/repeats/tail all increment combo, add no combo score
            combo_score += int(max(0, combo - 1) * per_hit_base)
            # slider itself does not increment combo further (already done via nested objects)
        else:
            combo_score += int(max(0, combo - 1) * per_hit_base)
            combo += 1

    return combo_score


def calculate_score_based_miss_count(
    max_combo: int,
    slider_count: int,
    aim_top_weighted_slider_factor: float,
    legacy_score_base_multiplier: int,
    legacy_score_multiplier: float,
    maximum_legacy_combo_score: int,
    nested_score_per_object: float,
    score_max_combo: int,
    legacy_total_score: float,
    accuracy: float,
    count_great: int,
    count_ok: int,
    count_meh: int,
    count_miss: int,
) -> float:
    if max_combo == 0:
        return 0.0

    total_hits = count_great + count_ok + count_meh + count_miss
    total_imperfect_hits = count_ok + count_meh + count_miss

    maximum_miss_count = _calculate_maximum_combo_based_miss_count(
        max_combo, slider_count, aim_top_weighted_slider_factor, score_max_combo, count_miss, total_imperfect_hits,
    )

    score_v1_multiplier = legacy_score_base_multiplier * legacy_score_multiplier
    relevant_combo_per_object = _calculate_relevant_score_combo_per_object(max_combo, maximum_legacy_combo_score, legacy_score_base_multiplier)

    def score_at_combo(combo: float) -> float:
        estimated_objects = combo / relevant_combo_per_object - 1 if relevant_combo_per_object > 0 else 0.0

        combo_score = (
            (2 * (relevant_combo_per_object - 1) + (estimated_objects - 1) * relevant_combo_per_object) * estimated_objects / 2
            if relevant_combo_per_object > 0 else 0.0
        )
        combo_score *= accuracy * 300 / 25 * score_v1_multiplier

        objects_hit = (total_hits - count_miss) * combo / max_combo
        non_combo_score = (300 + nested_score_per_object) * accuracy * objects_hit

        return combo_score + non_combo_score

    score_obtained_during_max_combo = score_at_combo(score_max_combo)
    remaining_score = legacy_total_score - score_obtained_during_max_combo

    if remaining_score <= 0:
        return maximum_miss_count

    remaining_combo = max_combo - score_max_combo
    expected_remaining_score = score_at_combo(remaining_combo)

    score_based_miss_count = expected_remaining_score / remaining_score
    score_based_miss_count = max(score_based_miss_count, 1.0)

    return min(score_based_miss_count, maximum_miss_count)


def _calculate_relevant_score_combo_per_object(max_combo: int, maximum_legacy_combo_score: int, legacy_score_base_multiplier: int) -> float:
    combo_score = maximum_legacy_combo_score
    combo_score /= 300.0 / 25.0 * legacy_score_base_multiplier

    result = (max_combo - 2) * max_combo
    result /= max(max_combo + 2 * (combo_score - 1), 1)
    return result


def _calculate_maximum_combo_based_miss_count(max_combo: int, slider_count: int, aim_top_weighted_slider_factor: float,
                                               score_max_combo: int, count_miss: int, total_imperfect_hits: int) -> float:
    if slider_count <= 0:
        return float(count_miss)

    miss_count = 0.0

    likely_missed_sliderend_portion = 0.04 + 0.06 * pow(min(aim_top_weighted_slider_factor, 1.0), 2)
    full_combo_threshold = max_combo - min(4 + likely_missed_sliderend_portion * slider_count, slider_count)

    if score_max_combo < full_combo_threshold:
        miss_count = pow(full_combo_threshold / max(1.0, score_max_combo), 2.5)

    miss_count = min(miss_count, total_imperfect_hits)

    max_possible_slider_breaks = min(slider_count, (max_combo - score_max_combo) // 2)

    slider_breaks = miss_count - count_miss

    if slider_breaks > max_possible_slider_breaks:
        miss_count = count_miss + max_possible_slider_breaks

    return miss_count
