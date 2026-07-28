"""osu!std Flashlight skill: models the difficulty of memorising object
patterns while only a small radius around the cursor is visible (FL mod).
Independent implementation; not adapted from any specific codebase.
"""

from __future__ import annotations

import math

from .._diffutils import reverse_lerp
from .._strain_skill import StrainDecaySkill
from .beatmap import OsuObjectKind
from .preprocessing import NORMALISED_RADIUS, OsuDifficultyHitObject, previous


def flashlight_evaluate(dobjs: list[OsuDifficultyHitObject], index: int, hidden: bool) -> float:
    current = dobjs[index]
    if current.obj.kind == OsuObjectKind.SPINNER:
        return 0.0

    max_opacity_bonus = 0.4
    hidden_bonus = 0.2
    min_velocity = 0.5
    slider_multiplier = 1.3
    min_angle_multiplier = 0.2

    scaling_factor = 52.0 / current.obj.radius
    small_dist_nerf = 1.0
    cumulative_strain_time = 0.0

    flashlight_difficulty = 0.0

    last_obj = current
    angle_repeat_count = 0.0

    for i in range(min(index, 10)):
        current_obj = previous(dobjs, index, i)
        if current_obj is None:
            break

        cumulative_strain_time += last_obj.adjusted_delta_time

        if current_obj.obj.kind != OsuObjectKind.SPINNER:
            jump_distance = math.hypot(
                current.obj.stacked_position[0] - current_obj.obj.stacked_end_position[0],
                current.obj.stacked_position[1] - current_obj.obj.stacked_end_position[1],
            )

            if i == 0:
                small_dist_nerf = min(1.0, jump_distance / 75.0)

            stack_nerf = min(1.0, (current_obj.lazy_jump_distance / scaling_factor) / 25.0)

            opacity_bonus = 1.0 + max_opacity_bonus * (1.0 - current.opacity_at(current_obj.obj.start_time, hidden))

            flashlight_difficulty += stack_nerf * opacity_bonus * scaling_factor * jump_distance / cumulative_strain_time

            if current_obj.angle is not None and current.angle is not None:
                if abs(current_obj.angle - current.angle) < 0.02:
                    angle_repeat_count += max(1.0 - 0.1 * i, 0.0)

        last_obj = current_obj

    flashlight_difficulty = pow(small_dist_nerf * flashlight_difficulty, 2)

    if hidden:
        flashlight_difficulty *= 1.0 + hidden_bonus

    flashlight_difficulty *= min_angle_multiplier + (1.0 - min_angle_multiplier) / (angle_repeat_count + 1.0)

    slider_bonus = 0.0

    if current.obj.kind == OsuObjectKind.SLIDER:
        pixel_travel_distance = current.lazy_travel_distance / scaling_factor
        slider_bonus = pow(max(0.0, pixel_travel_distance / current.travel_time - min_velocity), 0.5)
        slider_bonus *= pixel_travel_distance

        if current.obj.repeat_count > 0:
            slider_bonus /= current.obj.repeat_count + 1

    flashlight_difficulty += slider_bonus * slider_multiplier

    return flashlight_difficulty


class FlashlightSkill:
    def __init__(self, dobjs: list[OsuDifficultyHitObject], total_objects: int, hidden: bool = False,
                 mods: frozenset[str] = frozenset(), magnetised_strength: float = 0.5, deflate_start_scale: float = 2.0):
        self.dobjs = dobjs
        self.total_objects = total_objects
        self.hidden = hidden
        self.mods = mods
        self.magnetised_strength = magnetised_strength
        self.deflate_start_scale = deflate_start_scale

        self._skill = StrainDecaySkill(
            skill_multiplier=0.058,
            strain_decay_base=0.15,
            strain_value_of=self._strain_value_of,
        )

    def _strain_value_of(self, do: OsuDifficultyHitObject) -> float:
        index = do.index
        difficulty = flashlight_evaluate(self.dobjs, index, self.hidden)

        if "TD" in self.mods:
            difficulty = pow(difficulty, 0.9)
        if "MG" in self.mods:
            difficulty *= 1.0 - self.magnetised_strength
        if "DF" in self.mods:
            difficulty *= min(max(reverse_lerp(self.deflate_start_scale, 11, 1), 0.1), 1.0)
        if "RX" in self.mods:
            difficulty *= 0.7
        if "AP" in self.mods:
            difficulty *= 0.4

        difficulty *= 0.985 + pow(max(0.0, do.overall_difficulty), 2) / 4000
        return difficulty

    def process_all(self) -> None:
        for do in self.dobjs:
            self._skill.process(do)

    def difficulty_value(self) -> float:
        total = sum(self._skill.get_current_strain_peaks())
        total *= 0.7 + 0.1 * min(1.0, self.total_objects / 200.0) + (
            0.2 * min(1.0, (self.total_objects - 200) / 200.0) if self.total_objects > 200 else 0.0
        )
        return total

    @staticmethod
    def difficulty_to_performance(difficulty: float) -> float:
        return 25 * pow(difficulty, 2)
