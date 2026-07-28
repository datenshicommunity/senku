"""Stamina difficulty for osu!taiko.

Models the mechanical demand of alternating hands to hit same-colour
notes: the harder a same-colour repeat is to reach with an available
finger, the higher the strain. Independent implementation of the same
finger-alternation concept; not adapted from any specific codebase.
"""

from __future__ import annotations

from .._diffutils import logistic, reverse_lerp
from .beatmap import TaikoObjectKind
from .preprocessing import TaikoDifficultyHitObject


def _speed_bonus(interval: float) -> float:
    interval = max(interval, 1.0)
    return 20.0 / interval


def _available_fingers_for(hit_object: TaikoDifficultyHitObject) -> int:
    previous_colour_change = hit_object.colour_data.previous_colour_change() if hit_object.colour_data else None
    next_colour_change = hit_object.colour_data.next_colour_change() if hit_object.colour_data else None

    if previous_colour_change is not None and hit_object.start_time - previous_colour_change.start_time < 300:
        return 2
    if next_colour_change is not None and next_colour_change.start_time - hit_object.start_time < 300:
        return 2
    return 8


def evaluate_stamina_difficulty_of(hit_object: TaikoDifficultyHitObject) -> float:
    if not hit_object.is_hit:
        return 0.0

    previous = hit_object.previous(1)
    previous_mono = hit_object.previous_mono(_available_fingers_for(hit_object) - 1)

    object_strain = 0.5
    if previous is None:
        return object_strain

    if previous_mono is not None:
        object_strain += _speed_bonus(hit_object.start_time - previous_mono.start_time) + 0.5 * _speed_bonus(
            hit_object.start_time - previous.start_time
        )

    return object_strain


class StaminaSkillState:
    """Mirrors the reference's dual-decay StrainSkill for stamina.

    Two instances of this run per beatmap: one over all hit objects
    (colour-aware, with a mono-length bonus), one restricted to a single
    colour's stream (no bonus, but with an index-based strain dampener
    for very long mono streams -- common on converts).
    """

    def __init__(self, single_colour_stamina: bool, is_convert: bool):
        self.single_colour_stamina = single_colour_stamina
        self.is_convert = is_convert
        self.current_strain = 0.0

    def _strain_decay(self, ms: float) -> float:
        return pow(0.4, ms / 1000)

    def strain_value_at(self, hit_object: TaikoDifficultyHitObject) -> float:
        self.current_strain *= self._strain_decay(hit_object.delta_time)

        stamina_difficulty = evaluate_stamina_difficulty_of(hit_object) * 1.1

        mono_streak = hit_object.colour_data.mono_streak if hit_object.colour_data else None
        index = mono_streak.hit_objects.index(hit_object) if mono_streak is not None else 0

        mono_length_bonus = 1.0 if self.is_convert else 1.0 + 0.5 * reverse_lerp(index, 5, 20)

        if not self.single_colour_stamina:
            stamina_difficulty *= mono_length_bonus

        self.current_strain += stamina_difficulty

        if self.single_colour_stamina:
            return logistic(-(index - 10) / 2.0, self.current_strain)
        return self.current_strain

    def calculate_initial_strain(self, time: float, current: TaikoDifficultyHitObject) -> float:
        if self.single_colour_stamina:
            return 0.0
        previous = current.previous(0)
        return self.current_strain * self._strain_decay(time - previous.start_time)
