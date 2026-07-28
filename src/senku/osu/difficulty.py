"""osu!std top-level star rating: combines Aim, Speed, and Reading (plus
Flashlight when the FL mod is active) into a single difficulty value via a
performance-weighted p-norm. Independent implementation; not adapted from
any specific codebase.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .._diffutils import norm
from .aim import AimSkill
from .beatmap import OsuBeatmap, OsuObjectKind
from .flashlight import FlashlightSkill
from .legacy_score import calculate_difficulty_peppy_stars_for, calculate_nested_score_per_object, simulate_combo_score
from .preprocessing import build_difficulty_hit_objects
from .reading import ReadingSkill
from .speed import SpeedSkill

PERFORMANCE_BASE_MULTIPLIER = 1.12
PERFORMANCE_NORM_EXPONENT = 1.1


@dataclass
class OsuDifficultyAttributes:
    star_rating: float
    aim_difficulty: float
    speed_difficulty: float
    reading_difficulty: float
    flashlight_difficulty: float
    slider_factor: float
    aim_difficult_strain_count: float
    speed_difficult_strain_count: float
    reading_difficult_note_count: float
    speed_note_count: float
    aim_difficult_slider_count: float
    aim_top_weighted_slider_factor: float
    speed_top_weighted_slider_factor: float
    max_combo: int
    hit_circle_count: int
    slider_count: int
    spinner_count: int
    nested_score_per_object: float
    legacy_score_base_multiplier: int
    maximum_legacy_combo_score: int


def difficulty_to_performance(difficulty: float) -> float:
    return 4.0 * pow(difficulty, 3)


def sum_cognition_difficulty(reading: float, flashlight: float) -> float:
    if reading <= 0:
        return flashlight
    if flashlight <= 0:
        return reading
    return norm(PERFORMANCE_NORM_EXPONENT, reading, flashlight * min(max(flashlight / reading, 0.25), 1.0))


def _calculate_aim_rating(difficulty_value: float) -> float:
    return pow(difficulty_value, 0.63) * 0.02275


def _calculate_rating(difficulty_value: float) -> float:
    return math.sqrt(difficulty_value) * 0.0675


def calculate(beatmap: OsuBeatmap, clock_rate: float = 1.0, hidden: bool = False, flashlight: bool = False,
              mods: frozenset[str] = frozenset(), magnetised_strength: float = 0.5, deflate_start_scale: float = 2.0) -> OsuDifficultyAttributes:
    dobjs = build_difficulty_hit_objects(beatmap, clock_rate, hidden)

    aim = AimSkill(dobjs, include_sliders=True, mods=mods, magnetised_strength=magnetised_strength)
    aim.process_all()
    aim_without_sliders = AimSkill(dobjs, include_sliders=False, mods=mods, magnetised_strength=magnetised_strength)
    aim_without_sliders.process_all()
    speed = SpeedSkill(dobjs, mods=mods)
    speed.process_all()
    reading = ReadingSkill(dobjs, has_hidden_mod=hidden, mods=mods, magnetised_strength=magnetised_strength)
    reading.process_all()

    flashlight_skill = None
    if flashlight:
        flashlight_skill = FlashlightSkill(dobjs, total_objects=len(beatmap.objects), hidden=hidden, mods=mods,
                                            magnetised_strength=magnetised_strength, deflate_start_scale=deflate_start_scale)
        flashlight_skill.process_all()

    aim_difficulty_value = aim.difficulty_value()
    aim_no_sliders_difficulty_value = aim_without_sliders.difficulty_value()
    speed_difficulty_value = speed.difficulty_value()
    reading_difficulty_value = reading.difficulty_value()

    aim_difficult_strain_count = aim.count_top_weighted_strains(aim_difficulty_value)
    speed_difficult_strain_count = speed.count_top_weighted_object_difficulties(speed_difficulty_value)
    reading_difficult_note_count = reading.count_top_weighted_object_difficulties(reading_difficulty_value)

    speed_note_count = speed.relevant_object_count()

    aim_no_sliders_top_weighted_slider_count = aim_without_sliders.count_top_weighted_sliders(aim_no_sliders_difficulty_value)
    aim_no_sliders_difficult_strain_count = aim_without_sliders.count_top_weighted_strains(aim_no_sliders_difficulty_value)

    aim_top_weighted_slider_factor = aim_no_sliders_top_weighted_slider_count / max(1.0, aim_no_sliders_difficult_strain_count - aim_no_sliders_top_weighted_slider_count)

    speed_top_weighted_slider_count = speed.count_top_weighted_sliders(speed_difficulty_value)
    speed_top_weighted_slider_factor = speed_top_weighted_slider_count / max(1.0, speed_difficult_strain_count - speed_top_weighted_slider_count)

    difficult_sliders = aim.get_difficult_sliders()

    hit_circle_count = sum(1 for o in beatmap.objects if o.kind == OsuObjectKind.CIRCLE)
    slider_count = sum(1 for o in beatmap.objects if o.kind == OsuObjectKind.SLIDER)
    spinner_count = sum(1 for o in beatmap.objects if o.kind == OsuObjectKind.SPINNER)

    aim_rating = _calculate_aim_rating(aim_difficulty_value)
    aim_no_sliders_rating = _calculate_aim_rating(aim_no_sliders_difficulty_value)

    slider_factor = (aim_no_sliders_rating / aim_rating) if aim_difficulty_value > 0 else 1.0

    speed_rating = _calculate_rating(speed_difficulty_value)
    reading_rating = _calculate_rating(reading_difficulty_value)

    flashlight_rating = _calculate_rating(flashlight_skill.difficulty_value()) if flashlight_skill is not None else 0.0

    base_aim_performance = difficulty_to_performance(aim_rating)
    base_speed_performance = difficulty_to_performance(speed_rating)
    base_reading_performance = difficulty_to_performance(reading_rating)
    base_flashlight_performance = 25 * pow(flashlight_rating, 2)
    base_cognition_performance = sum_cognition_difficulty(base_reading_performance, base_flashlight_performance)

    base_performance = norm(PERFORMANCE_NORM_EXPONENT, base_aim_performance, base_speed_performance, base_cognition_performance)

    star_rating = pow(base_performance * PERFORMANCE_BASE_MULTIPLIER, 1.0 / 3.0)

    nested_score_per_object = calculate_nested_score_per_object(beatmap)
    legacy_score_base_multiplier = calculate_difficulty_peppy_stars_for(beatmap)
    maximum_legacy_combo_score = simulate_combo_score(beatmap, legacy_score_base_multiplier)

    return OsuDifficultyAttributes(
        star_rating=star_rating,
        aim_difficulty=aim_rating,
        speed_difficulty=speed_rating,
        reading_difficulty=reading_rating,
        flashlight_difficulty=flashlight_rating,
        slider_factor=slider_factor,
        aim_difficult_strain_count=aim_difficult_strain_count,
        speed_difficult_strain_count=speed_difficult_strain_count,
        reading_difficult_note_count=reading_difficult_note_count,
        speed_note_count=speed_note_count,
        aim_difficult_slider_count=difficult_sliders,
        aim_top_weighted_slider_factor=aim_top_weighted_slider_factor,
        speed_top_weighted_slider_factor=speed_top_weighted_slider_factor,
        max_combo=beatmap.max_combo(),
        hit_circle_count=hit_circle_count,
        slider_count=slider_count,
        spinner_count=spinner_count,
        nested_score_per_object=nested_score_per_object,
        legacy_score_base_multiplier=legacy_score_base_multiplier,
        maximum_legacy_combo_score=maximum_legacy_combo_score,
    )
