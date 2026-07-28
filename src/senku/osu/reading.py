"""osu!std Reading skill: models the cognitive difficulty of processing
overlapping/dense object patterns and (with Hidden) memorising objects that
fade out before they need to be hit. Independent implementation; not adapted
from any specific codebase.
"""

from __future__ import annotations

import math

from .._diffutils import norm, reverse_lerp, smootherstep
from ._harmonic_skill import HarmonicSkill
from .beatmap import OsuObjectKind
from .preprocessing import NORMALISED_RADIUS, OsuDifficultyHitObject, next_obj, previous

_READING_WINDOW_SIZE = 3000.0
_DISTANCE_INFLUENCE_THRESHOLD = NORMALISED_RADIUS * 2 * 1.5


def _reading_high_bpm_bonus(ms: float) -> float:
    return 1 / (1 - pow(0.8, ms / 1000))


def _get_time_nerf_factor(delta_time: float) -> float:
    return min(max(2 - delta_time / (_READING_WINDOW_SIZE / 2), 0.0), 1.0)


def _retrieve_past_visible_objects(dobjs: list[OsuDifficultyHitObject], index: int) -> list[OsuDifficultyHitObject]:
    current = dobjs[index]
    result = []
    for i in range(index):
        hit_object = previous(dobjs, index, i)
        if (hit_object is None
                or current.start_time - hit_object.start_time > _READING_WINDOW_SIZE
                or hit_object.start_time < current.start_time - current.preempt):
            break
        result.append(hit_object)
    return result


def _get_past_object_difficulty_influence(dobjs: list[OsuDifficultyHitObject], index: int) -> float:
    current = dobjs[index]
    influence = 0.0
    for loop_obj in _retrieve_past_visible_objects(dobjs, index):
        loop_difficulty = current.opacity_at(loop_obj.obj.start_time, False)
        loop_difficulty *= smootherstep(loop_obj.lazy_jump_distance, 15, _DISTANCE_INFLUENCE_THRESHOLD)

        time_between = current.start_time - loop_obj.start_time
        loop_difficulty *= _get_time_nerf_factor(time_between)

        influence += loop_difficulty
    return influence


def _retrieve_current_visible_object_density(dobjs: list[OsuDifficultyHitObject], index: int) -> float:
    current = dobjs[index]
    visible_object_count = 0.0

    j = index + 1
    while j < len(dobjs):
        hit_object = dobjs[j]
        if (hit_object.start_time - current.start_time > _READING_WINDOW_SIZE
                or current.start_time < hit_object.start_time - hit_object.preempt):
            break

        time_between = hit_object.start_time - current.start_time
        time_nerf_factor = _get_time_nerf_factor(time_between)

        visible_object_count += hit_object.opacity_at(current.obj.start_time, False) * time_nerf_factor
        j += 1

    return visible_object_count


def _get_constant_angle_nerf_factor(dobjs: list[OsuDifficultyHitObject], index: int) -> float:
    current = dobjs[index]

    minimum_angle_relevancy_time = 2000.0
    maximum_angle_relevancy_time = 200.0

    constant_angle_count = 0.0
    idx = 0
    current_time_gap = 0.0

    loop_obj_prev0 = current
    loop_obj_prev1 = None
    loop_obj_prev2 = None

    while current_time_gap < minimum_angle_relevancy_time:
        loop_obj = previous(dobjs, index, idx)
        if loop_obj is None:
            break

        long_interval_factor = 1 - reverse_lerp(loop_obj.adjusted_delta_time, maximum_angle_relevancy_time, minimum_angle_relevancy_time)

        if loop_obj.angle is not None and current.angle is not None:
            angle_difference = abs(current.angle - loop_obj.angle)
            angle_difference_alternating = math.pi

            if loop_obj_prev0.angle is not None and loop_obj_prev1 is not None and loop_obj_prev1.angle is not None and loop_obj_prev2 is not None and loop_obj_prev2.angle is not None:
                angle_difference_alternating = abs(loop_obj_prev1.angle - loop_obj.angle)
                angle_difference_alternating += abs(loop_obj_prev2.angle - loop_obj_prev0.angle)

                weight = 1.0
                weight *= reverse_lerp(min(loop_obj.angle, loop_obj_prev0.angle) * 180 / math.pi, 20, 5)
                weight *= reverse_lerp(max(loop_obj.angle, loop_obj_prev0.angle) * 180 / math.pi, 60, 120)

                angle_difference_alternating = math.pi + (0.1 * angle_difference_alternating - math.pi) * weight

            stack_factor = smootherstep(loop_obj.lazy_jump_distance, 0, NORMALISED_RADIUS)

            constant_angle_count += math.cos(3 * min(math.radians(30), min(angle_difference, angle_difference_alternating) * stack_factor)) * long_interval_factor

        current_time_gap = current.start_time - loop_obj.start_time
        idx += 1

        loop_obj_prev2 = loop_obj_prev1
        loop_obj_prev1 = loop_obj_prev0
        loop_obj_prev0 = loop_obj

    ratio = (2 / constant_angle_count) if constant_angle_count != 0 else math.inf
    return min(max(ratio, 0.2), 1.0)


def _calculate_density_difficulty(next_object: OsuDifficultyHitObject | None, velocity: float, constant_angle_nerf_factor: float,
                                   past_object_difficulty_influence: float, current_visible_object_density: float) -> float:
    density_multiplier = 2.4
    density_difficulty_base = 2.5

    future_object_difficulty_influence = math.sqrt(current_visible_object_density)

    if next_object is not None:
        future_object_difficulty_influence *= smootherstep(next_object.lazy_jump_distance, 15, _DISTANCE_INFLUENCE_THRESHOLD)

    note_density_difficulty = pow(past_object_difficulty_influence + future_object_difficulty_influence, 1.7) * 0.4 * constant_angle_nerf_factor * velocity
    note_density_difficulty = max(0.0, note_density_difficulty - density_difficulty_base)
    note_density_difficulty = pow(note_density_difficulty, 0.45) * density_multiplier

    return note_density_difficulty


def _calculate_preempt_difficulty(velocity: float, constant_angle_nerf_factor: float, preempt: float) -> float:
    preempt_balancing_factor = 140000.0
    preempt_starting_point = 500.0

    preempt_difficulty = pow((preempt_starting_point - preempt + abs(preempt - preempt_starting_point)) / 2, 2.5) / preempt_balancing_factor
    preempt_difficulty *= constant_angle_nerf_factor * velocity

    return preempt_difficulty


def _calculate_hidden_difficulty(dobjs: list[OsuDifficultyHitObject], index: int, past_object_difficulty_influence: float,
                                  current_visible_object_density: float, velocity: float, constant_angle_nerf_factor: float) -> float:
    current = dobjs[index]
    hidden_multiplier = 0.28

    preempt_factor = pow(current.preempt, 2.2) * 0.01
    density_factor = pow(current_visible_object_density + past_object_difficulty_influence, 3.3) * 3

    hidden_difficulty = (preempt_factor + density_factor) * constant_angle_nerf_factor * velocity * 0.01
    hidden_difficulty = pow(hidden_difficulty, 0.4) * hidden_multiplier

    previous_obj = previous(dobjs, index, 0)

    if (current.lazy_jump_distance == 0 and current.opacity_at(previous_obj.obj.start_time, True) == 0
            and previous_obj.start_time > current.start_time - current.preempt):
        hidden_difficulty += hidden_multiplier * 2500 / pow(current.adjusted_delta_time, 1.5)

    return hidden_difficulty


def reading_evaluate(dobjs: list[OsuDifficultyHitObject], index: int, hidden: bool) -> float:
    current = dobjs[index]
    if current.obj.kind == OsuObjectKind.SPINNER or index == 0:
        return 0.0

    next_object = next_obj(dobjs, index, 0)

    velocity = max(1.0, current.lazy_jump_distance / current.adjusted_delta_time)

    current_visible_object_density = _retrieve_current_visible_object_density(dobjs, index)
    past_object_difficulty_influence = _get_past_object_difficulty_influence(dobjs, index)

    constant_angle_nerf_factor = _get_constant_angle_nerf_factor(dobjs, index)

    note_density_difficulty = _calculate_density_difficulty(next_object, velocity, constant_angle_nerf_factor, past_object_difficulty_influence, current_visible_object_density)

    hidden_difficulty = _calculate_hidden_difficulty(dobjs, index, past_object_difficulty_influence, current_visible_object_density, velocity, constant_angle_nerf_factor) if hidden else 0.0

    preempt_difficulty = _calculate_preempt_difficulty(velocity, constant_angle_nerf_factor, current.preempt)

    reading_difficulty = norm(1.5, preempt_difficulty, hidden_difficulty, note_density_difficulty)
    reading_difficulty *= _reading_high_bpm_bonus(current.adjusted_delta_time)

    return reading_difficulty


class ReadingSkill:
    def __init__(self, dobjs: list[OsuDifficultyHitObject], has_hidden_mod: bool = False,
                 mods: frozenset[str] = frozenset(), magnetised_strength: float = 0.5):
        self.dobjs = dobjs
        self.has_hidden_mod = has_hidden_mod
        self.current_strain = 0.0
        self.reduced_note_count = 0.0
        self.mods = mods
        self.magnetised_strength = magnetised_strength
        self._reduced_duration: float | None = None
        self._harmonic = HarmonicSkill(harmonic_scale=1.0, decay_exponent=0.9)

    @staticmethod
    def _strain_decay(ms: float) -> float:
        return pow(0.8, ms / 1000)

    def _calculate_adjusted_difficulty(self, index: int) -> float:
        do = self.dobjs[index]
        difficulty = reading_evaluate(self.dobjs, index, self.has_hidden_mod)

        if "TD" in self.mods:
            difficulty = pow(difficulty, 0.89)
        if "MG" in self.mods:
            difficulty *= 1.0 - self.magnetised_strength
        if "RX" in self.mods:
            difficulty *= 0.4
        if "AP" in self.mods:
            difficulty *= 0.1

        difficulty *= 0.825 + pow(max(0.0, do.overall_difficulty), 2.2) / 1125.0
        return difficulty

    def _object_difficulty_of(self, index: int) -> float:
        skill_multiplier = 2.5
        reduced_difficulty_duration = 60 * 1000

        do = self.dobjs[index]

        decay = self._strain_decay(do.delta_time)
        self.current_strain *= decay
        self.current_strain += self._calculate_adjusted_difficulty(index) * (1 - decay) * skill_multiplier

        if self._reduced_duration is None:
            self._reduced_duration = do.start_time + reduced_difficulty_duration

        if do.start_time <= self._reduced_duration:
            self.reduced_note_count += 1

        return self.current_strain

    def process_all(self) -> None:
        for i in range(len(self.dobjs)):
            self._harmonic.add(self._object_difficulty_of(i))

    def _get_transformed_difficulties(self, difficulties: list[float]) -> list[float]:
        difficulties = [v for v in difficulties if v > 0]

        reduced_difficulty_base_line = 0.0

        for i in range(min(len(difficulties), int(self.reduced_note_count))):
            t = min(max(i / self.reduced_note_count, 0.0), 1.0) if self.reduced_note_count != 0 else 0.0
            lerped = 1 + (10 - 1) * t
            scale = math.log10(lerped)
            difficulties[i] *= reduced_difficulty_base_line + (1.0 - reduced_difficulty_base_line) * scale

        return difficulties

    def difficulty_value(self) -> float:
        self._harmonic.get_transformed_difficulties = self._get_transformed_difficulties
        return self._harmonic.difficulty_value()

    def count_top_weighted_object_difficulties(self, difficulty_value: float) -> float:
        if not self._harmonic.object_difficulties:
            return 0.0
        if self._harmonic.object_weight_sum == 0:
            return 0.0
        consistent_top_note = difficulty_value / self._harmonic.object_weight_sum
        if consistent_top_note == 0:
            return 0.0
        from .._diffutils import logistic_full
        return sum(logistic_full(d / consistent_top_note, 1.15, 5, 1.1) for d in self._harmonic.object_difficulties)
