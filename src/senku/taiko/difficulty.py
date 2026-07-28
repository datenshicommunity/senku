"""Top-level osu!taiko star rating: combines rhythm, reading, colour and
stamina strain into a single rating, using the peaks-per-section
p-norm-combination approach. Independent implementation; not adapted
from any specific codebase.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .._diffutils import norm, reverse_lerp
from .._strain_skill import StrainDecaySkill
from . import colour as colour_mod
from . import reading as reading_mod
from . import rhythm as rhythm_mod
from .beatmap import TaikoBeatmap
from .preprocessing import TaikoDifficultyHitObject, build_difficulty_hit_objects
from .stamina import StaminaSkillState

_DIFFICULTY_MULTIPLIER = 0.084375
_RHYTHM_SKILL_MULTIPLIER = 0.770 * _DIFFICULTY_MULTIPLIER
_READING_SKILL_MULTIPLIER = 0.100 * _DIFFICULTY_MULTIPLIER
_COLOUR_SKILL_MULTIPLIER = 0.375 * _DIFFICULTY_MULTIPLIER
_STAMINA_SKILL_MULTIPLIER = 0.445 * _DIFFICULTY_MULTIPLIER


@dataclass
class TaikoDifficultyAttributes:
    star_rating: float
    mechanical_difficulty: float
    rhythm_difficulty: float
    reading_difficulty: float
    colour_difficulty: float
    stamina_difficulty: float
    mono_stamina_factor: float
    consistency_factor: float
    stamina_top_strains: float
    great_hit_window: float


def _rescale(sr: float) -> float:
    if sr < 0:
        return sr
    return 10.43 * math.log(sr / 8 + 1)


def calculate(beatmap: TaikoBeatmap, clock_rate: float = 1.0, is_convert: bool = False, is_relax: bool = False) -> TaikoDifficultyAttributes:
    objects = build_difficulty_hit_objects(beatmap, clock_rate)

    if not objects:
        ghw = 0.0
        return TaikoDifficultyAttributes(0, 0, 0, 0, 0, 0, 1, 0, 0, ghw)

    colour_mod.process_and_assign(objects)
    rhythm_mod.assign_ratios(objects)
    rhythm_mod.process_and_assign([o for o in objects if o.is_hit])

    rhythm_skill = StrainDecaySkill(1.0, 0.4, lambda o: rhythm_mod.evaluate_strain_value(o))
    reading_state = reading_mod.ReadingSkillState()
    reading_skill = StrainDecaySkill(1.0, 0.4, reading_state.strain_value_at)
    colour_skill = StrainDecaySkill(0.12, 0.8, lambda o: colour_mod.evaluate_difficulty_of(o))

    stamina_state = StaminaSkillState(single_colour_stamina=False, is_convert=is_convert)
    mono_stamina_state = StaminaSkillState(single_colour_stamina=True, is_convert=is_convert)

    stamina_peaks: list[float] = []
    mono_stamina_peaks: list[float] = []
    stamina_object_difficulties: list[float] = []
    _stamina_current_section_peak = 0.0
    _mono_current_section_peak = 0.0
    _section_end = None

    for obj in objects:
        rhythm_skill.process(obj)
        reading_skill.process(obj)
        colour_skill.process(obj)

        if _section_end is None:
            _section_end = math.ceil(obj.start_time / 400.0) * 400.0

        while obj.start_time > _section_end:
            stamina_peaks.append(_stamina_current_section_peak)
            mono_stamina_peaks.append(_mono_current_section_peak)
            _stamina_current_section_peak = stamina_state.calculate_initial_strain(_section_end, obj)
            _mono_current_section_peak = mono_stamina_state.calculate_initial_strain(_section_end, obj)
            _section_end += 400.0

        stamina_val = stamina_state.strain_value_at(obj)
        mono_val = mono_stamina_state.strain_value_at(obj)
        stamina_object_difficulties.append(stamina_val)
        _stamina_current_section_peak = max(stamina_val, _stamina_current_section_peak)
        _mono_current_section_peak = max(mono_val, _mono_current_section_peak)

    stamina_peaks.append(_stamina_current_section_peak)
    mono_stamina_peaks.append(_mono_current_section_peak)

    def weighted_sum(peaks: list[float]) -> float:
        difficulty = 0.0
        weight = 1.0
        for p in sorted((x for x in peaks if x > 0), reverse=True):
            difficulty += p * weight
            weight *= 0.9
        return difficulty

    stamina_difficulty_value = weighted_sum(stamina_peaks)
    mono_stamina_difficulty_value = weighted_sum(mono_stamina_peaks)

    rhythm_skill_value = rhythm_skill.difficulty_value() * _RHYTHM_SKILL_MULTIPLIER
    reading_skill_value = reading_skill.difficulty_value() * _READING_SKILL_MULTIPLIER
    colour_skill_value = colour_skill.difficulty_value() * _COLOUR_SKILL_MULTIPLIER
    stamina_skill_value = stamina_difficulty_value * _STAMINA_SKILL_MULTIPLIER
    mono_stamina_skill_value = mono_stamina_difficulty_value * _STAMINA_SKILL_MULTIPLIER
    mono_stamina_factor = 1.0 if stamina_skill_value == 0 else pow(mono_stamina_skill_value / stamina_skill_value, 5)

    stamina_difficult_strains = _count_top_weighted_strains(stamina_object_difficulties, stamina_difficulty_value)

    pattern_multiplier = pow(stamina_skill_value * colour_skill_value, 0.10)
    strain_length_bonus = 1 + 0.15 * reverse_lerp(stamina_difficult_strains, 1000, 1555)

    def combine_peaks(rhythm_p: list[float], reading_p: list[float], colour_p: list[float], stamina_p: list[float]) -> list[float]:
        combined: list[float] = []
        for i in range(len(colour_p)):
            rp = rhythm_p[i] * _RHYTHM_SKILL_MULTIPLIER * pattern_multiplier
            rdp = reading_p[i] * _READING_SKILL_MULTIPLIER
            cp = 0.0 if is_relax else colour_p[i] * _COLOUR_SKILL_MULTIPLIER
            sp = stamina_p[i] * _STAMINA_SKILL_MULTIPLIER * strain_length_bonus
            sp /= 1.5 if (is_convert or is_relax) else 1.0

            peak = norm(2, norm(1.5, cp, sp), rp, rdp)
            if peak > 0:
                combined.append(peak)
        return combined

    rhythm_peaks = rhythm_skill.get_current_strain_peaks()
    reading_peaks = reading_skill.get_current_strain_peaks()
    colour_peaks = colour_skill.get_current_strain_peaks()

    combined_peaks = combine_peaks(rhythm_peaks, reading_peaks, colour_peaks, stamina_peaks)
    combined_rating = weighted_sum(combined_peaks)

    rhythm_obj_diff = rhythm_skill.get_object_difficulties()
    reading_obj_diff = reading_skill.get_object_difficulties()
    colour_obj_diff = colour_skill.get_object_difficulties()
    # NOTE: reuses the SAME weighted combine_peaks (skill multipliers, pattern
    # multiplier, strain length bonus, convert/relax dampening all included)
    # -- not a raw p-norm of the unweighted per-object difficulties.
    hit_object_strain_peaks = combine_peaks(rhythm_obj_diff, reading_obj_diff, colour_obj_diff, stamina_object_difficulties)

    if hit_object_strain_peaks:
        sorted_desc = sorted(hit_object_strain_peaks, reverse=True)
        top_n = 1 + len(hit_object_strain_peaks) // 20
        top_average = sum(sorted_desc[:top_n]) / top_n
        consistency_factor = sum(hit_object_strain_peaks) / (top_average * len(hit_object_strain_peaks)) if top_average > 0 else 0.0
    else:
        consistency_factor = 0.0

    star_rating = _rescale(combined_rating * 1.4)

    skills_sum = rhythm_skill_value + reading_skill_value + colour_skill_value + stamina_skill_value
    skill_rating = star_rating / skills_sum if skills_sum > 0 else 0.0

    rhythm_difficulty = rhythm_skill_value * skill_rating
    reading_difficulty = reading_skill_value * skill_rating
    colour_difficulty = colour_skill_value * skill_rating
    stamina_difficulty = stamina_skill_value * skill_rating
    mechanical_difficulty = colour_difficulty + stamina_difficulty

    from .preprocessing import great_hit_window_for
    ghw = great_hit_window_for(beatmap.overall_difficulty, clock_rate)

    return TaikoDifficultyAttributes(
        star_rating=star_rating,
        mechanical_difficulty=mechanical_difficulty,
        rhythm_difficulty=rhythm_difficulty,
        reading_difficulty=reading_difficulty,
        colour_difficulty=colour_difficulty,
        stamina_difficulty=stamina_difficulty,
        mono_stamina_factor=mono_stamina_factor,
        consistency_factor=consistency_factor,
        stamina_top_strains=stamina_difficult_strains,
        great_hit_window=ghw,
    )


def _count_top_weighted_strains(object_difficulties: list[float], difficulty_value: float, decay_weight: float = 0.9) -> float:
    if not object_difficulties:
        return 0.0
    consistent_top_strain = difficulty_value * (1 - decay_weight)
    if consistent_top_strain == 0:
        return float(len(object_difficulties))

    from .._diffutils import logistic_full
    return sum(logistic_full(s / consistent_top_strain, 0.88, 10, 1.1) for s in object_difficulties)
