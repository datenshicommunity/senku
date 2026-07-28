"""osu!std Aim skill: models the difficulty of moving the cursor between
objects, as a probability-weighted blend of "snap" (aim then click), "flow"
(continuous cursor movement through objects), and "agility" (fast small
movements) sub-difficulties. Independent implementation; not adapted from
any specific codebase.
"""

from __future__ import annotations

import math

from .._diffutils import logistic, logistic_full, milliseconds_to_bpm, norm, reverse_lerp, smootherstep, smoothstep
from .._variable_strain_skill import VariableLengthStrainSkill
from .beatmap import OsuObjectKind
from .preprocessing import NORMALISED_DIAMETER, NORMALISED_RADIUS, OsuDifficultyHitObject, previous

_RADIANS_PER_DEGREE = math.pi / 180.0


def _deg(x: float) -> float:
    return x * _RADIANS_PER_DEGREE


# ---------------------------------------------------------------------------
# SnapAimEvaluator
# ---------------------------------------------------------------------------

def calc_angle_acuteness(angle: float) -> float:
    return smoothstep(angle, _deg(140), _deg(40))


def _calc_angle_wideness(angle: float) -> float:
    return smoothstep(angle, _deg(40), _deg(140))


def _snap_high_bpm_bonus(ms: float) -> float:
    return 1 / (1 - pow(0.03, pow(ms / 1000, 0.65)))


def _vector_angle_repetition(dobjs: list[OsuDifficultyHitObject], index: int, current: OsuDifficultyHitObject, previous_obj: OsuDifficultyHitObject) -> float:
    if current.angle is None or previous_obj.angle is None:
        return 1.0

    note_limit = 6
    maximum_repetition_nerf = 0.15
    maximum_vector_influence = 0.5

    constant_angle_count = 0.0

    for i in range(note_limit):
        prev_obj = previous(dobjs, index, i)
        if prev_obj is None:
            break

        if max(current.adjusted_delta_time, prev_obj.adjusted_delta_time) > 1.1 * min(current.adjusted_delta_time, prev_obj.adjusted_delta_time):
            break

        if prev_obj.normalised_vector_angle is not None and current.normalised_vector_angle is not None:
            angle_difference = abs(current.normalised_vector_angle - prev_obj.normalised_vector_angle)
            constant_angle_count += math.cos(8 * min(_deg(11.25), angle_difference))

    # Math.Min(0.5 / constantAngleCount, 1) -- C# double division by exact 0 yields +Infinity, not an exception.
    ratio = (0.5 / constant_angle_count) if constant_angle_count != 0 else math.inf
    vector_repetition = pow(min(ratio, 1.0), 2)

    stack_factor = smootherstep(current.lazy_jump_distance, 0, NORMALISED_DIAMETER)

    curr_angle = current.angle
    last_angle = previous_obj.angle

    angle_difference_adjusted = math.cos(2 * min(_deg(45), abs(curr_angle - last_angle) * stack_factor))

    base_nerf = 1 - maximum_repetition_nerf * calc_angle_acuteness(last_angle) * angle_difference_adjusted

    return pow(base_nerf + (1 - base_nerf) * vector_repetition * maximum_vector_influence * stack_factor, 2)


def snap_evaluate(dobjs: list[OsuDifficultyHitObject], index: int, with_slider_travel_distance: bool) -> float:
    current = dobjs[index]
    last = previous(dobjs, index, 0)

    if current.obj.kind == OsuObjectKind.SPINNER or index <= 1 or last is None or last.obj.kind == OsuObjectKind.SPINNER:
        return 0.0

    wide_angle_multiplier = 9.67
    acute_angle_multiplier = 2.41
    slider_multiplier = 1.5
    velocity_change_multiplier = 0.9
    wiggle_multiplier = 1.02

    last2 = previous(dobjs, index, 1)

    radius = NORMALISED_RADIUS
    diameter = NORMALISED_DIAMETER

    curr_distance = current.lazy_jump_distance if with_slider_travel_distance else current.jump_distance
    curr_velocity = curr_distance / current.adjusted_delta_time

    if last.obj.kind == OsuObjectKind.SLIDER and with_slider_travel_distance:
        slider_distance = last.lazy_travel_distance + current.lazy_jump_distance
        curr_velocity = max(curr_velocity, slider_distance / current.adjusted_delta_time)

    prev_distance = last.lazy_jump_distance if with_slider_travel_distance else last.jump_distance
    prev_velocity = prev_distance / last.adjusted_delta_time

    snap_difficulty = curr_velocity

    snap_difficulty *= _vector_angle_repetition(dobjs, index, current, last)

    if current.angle is not None and last.angle is not None:
        curr_angle = current.angle
        last_angle = last.angle

        velocity_influence = min(curr_velocity, prev_velocity)

        acute_angle_bonus = 0.0

        if max(current.adjusted_delta_time, last.adjusted_delta_time) < 1.25 * min(current.adjusted_delta_time, last.adjusted_delta_time):
            acute_angle_bonus = calc_angle_acuteness(curr_angle)
            acute_angle_bonus *= 0.08 + 0.92 * (1 - min(acute_angle_bonus, pow(calc_angle_acuteness(last_angle), 3)))
            acute_angle_bonus *= (
                velocity_influence
                * smootherstep(milliseconds_to_bpm(current.adjusted_delta_time, 2), 300, 400)
                * smootherstep(curr_distance, 0, diameter * 2)
            )

        wide_angle_bonus = _calc_angle_wideness(curr_angle)
        wide_angle_bonus *= 0.25 + 0.75 * (1 - min(wide_angle_bonus, pow(_calc_angle_wideness(last_angle), 3)))

        wide_angle_time_scale = 1.45
        wide_angle_curr_velocity = curr_distance / pow(current.adjusted_delta_time, wide_angle_time_scale)
        wide_angle_prev_velocity = prev_distance / pow(last.adjusted_delta_time, wide_angle_time_scale)

        if last.obj.kind == OsuObjectKind.SLIDER and with_slider_travel_distance:
            slider_distance = last.lazy_travel_distance + current.lazy_jump_distance
            wide_angle_curr_velocity = max(wide_angle_curr_velocity, slider_distance / pow(current.adjusted_delta_time, wide_angle_time_scale))

        wide_angle_bonus *= min(wide_angle_curr_velocity, wide_angle_prev_velocity)

        if last2 is not None:
            distance = math.hypot(
                last2.obj.stacked_position[0] - last.obj.stacked_position[0],
                last2.obj.stacked_position[1] - last.obj.stacked_position[1],
            )
            if distance < 1:
                wide_angle_bonus *= 1 - 0.55 * (1 - distance)

        snap_difficulty += max(acute_angle_bonus * acute_angle_multiplier, wide_angle_bonus * wide_angle_multiplier)

        wiggle_bonus = (
            velocity_influence
            * smootherstep(curr_distance, radius, diameter)
            * pow(reverse_lerp(curr_distance, diameter * 3, diameter), 1.8)
            * smootherstep(curr_angle, _deg(110), _deg(60))
            * smootherstep(prev_distance, radius, diameter)
            * pow(reverse_lerp(prev_distance, diameter * 3, diameter), 1.8)
            * smootherstep(last_angle, _deg(110), _deg(60))
        )

        snap_difficulty += wiggle_bonus * wiggle_multiplier

    if max(prev_velocity, curr_velocity) != 0:
        if with_slider_travel_distance:
            curr_velocity = curr_distance / current.adjusted_delta_time

        dist_ratio = smoothstep(abs(prev_velocity - curr_velocity) / max(prev_velocity, curr_velocity), 0, 1)
        overlap_velocity_buff = min(diameter * 1.25 / min(current.adjusted_delta_time, last.adjusted_delta_time), abs(prev_velocity - curr_velocity))
        velocity_change_bonus = overlap_velocity_buff * dist_ratio
        velocity_change_bonus *= pow(min(current.adjusted_delta_time, last.adjusted_delta_time) / max(current.adjusted_delta_time, last.adjusted_delta_time), 2)

        snap_difficulty += velocity_change_bonus * velocity_change_multiplier

    if current.obj.kind == OsuObjectKind.SLIDER and with_slider_travel_distance:
        slider_bonus = current.travel_distance / current.travel_time
        snap_difficulty += (slider_bonus if slider_bonus < 1 else pow(slider_bonus, 0.75)) * slider_multiplier

    snap_difficulty *= current.small_circle_bonus
    snap_difficulty *= _snap_high_bpm_bonus(current.adjusted_delta_time)

    return snap_difficulty


# ---------------------------------------------------------------------------
# AgilityEvaluator
# ---------------------------------------------------------------------------

def _agility_high_bpm_bonus(ms: float) -> float:
    return 1 / (1 - pow(0.2, ms / 1000))


def agility_evaluate(dobjs: list[OsuDifficultyHitObject], index: int) -> float:
    current = dobjs[index]
    if current.obj.kind == OsuObjectKind.SPINNER:
        return 0.0

    distance_cap = NORMALISED_DIAMETER * 1.2

    prev = previous(dobjs, index, 0) if index > 0 else None

    travel_distance = prev.lazy_travel_distance if prev is not None else 0.0
    distance = travel_distance + current.lazy_jump_distance

    distance_scaled = min(distance, distance_cap) / distance_cap

    agility_difficulty = distance_scaled * 1000 / current.adjusted_delta_time
    agility_difficulty *= pow(current.small_circle_bonus, 1.5)
    agility_difficulty *= _agility_high_bpm_bonus(current.adjusted_delta_time)

    return agility_difficulty


# ---------------------------------------------------------------------------
# FlowAimEvaluator
# ---------------------------------------------------------------------------

def _calculate_overlap_factor(first: OsuDifficultyHitObject, second: OsuDifficultyHitObject) -> float:
    object_radius = first.obj.radius
    distance = math.hypot(
        first.obj.stacked_position[0] - second.obj.stacked_position[0],
        first.obj.stacked_position[1] - second.obj.stacked_position[1],
    )
    return min(max(1 - pow(max(distance - object_radius, 0) / object_radius, 2), 0.0), 1.0)


def flow_evaluate(dobjs: list[OsuDifficultyHitObject], index: int, with_slider_travel_distance: bool) -> float:
    current = dobjs[index]
    last = previous(dobjs, index, 0)

    if current.obj.kind == OsuObjectKind.SPINNER or index <= 1 or last is None or last.obj.kind == OsuObjectKind.SPINNER:
        return 0.0

    velocity_change_multiplier = 0.52

    last_last = previous(dobjs, index, 1)

    curr_distance = current.lazy_jump_distance if with_slider_travel_distance else current.jump_distance
    prev_distance = last.lazy_jump_distance if with_slider_travel_distance else last.jump_distance

    curr_velocity = curr_distance / current.adjusted_delta_time

    if last.obj.kind == OsuObjectKind.SLIDER and with_slider_travel_distance:
        slider_distance = last.lazy_travel_distance + current.lazy_jump_distance
        curr_velocity = max(curr_velocity, slider_distance / current.adjusted_delta_time)

    prev_velocity = prev_distance / last.adjusted_delta_time

    flow_difficulty = curr_velocity
    flow_difficulty *= math.sqrt(current.small_circle_bonus)

    flow_difficulty *= 1 + min(0.25, pow((max(current.adjusted_delta_time, last.adjusted_delta_time) - min(current.adjusted_delta_time, last.adjusted_delta_time)) / 50, 4))

    if current.angle is not None and last.angle is not None:
        angle_difference = abs(current.angle - last.angle)
        angle_difference_adjusted = math.sin(angle_difference / 2) * 180.0
        angular_velocity = angle_difference_adjusted / (current.adjusted_delta_time * 0.1)
        flow_difficulty *= 0.8 + math.sqrt(angular_velocity / 270.0)

    overlapped_notes_weight = 1.0
    if index > 2 and last_last is not None:
        o1 = _calculate_overlap_factor(current, last)
        o2 = _calculate_overlap_factor(current, last_last)
        o3 = _calculate_overlap_factor(last, last_last)
        overlapped_notes_weight = 1 - o1 * o2 * o3

    if current.angle is not None:
        flow_difficulty += curr_velocity * calc_angle_acuteness(current.angle) * overlapped_notes_weight

    if max(prev_velocity, curr_velocity) != 0:
        if with_slider_travel_distance:
            curr_velocity = curr_distance / current.adjusted_delta_time

        dist_ratio = smoothstep(abs(prev_velocity - curr_velocity) / max(prev_velocity, curr_velocity), 0, 1)
        overlap_velocity_buff = min(NORMALISED_DIAMETER * 1.25 / min(current.adjusted_delta_time, last.adjusted_delta_time), abs(prev_velocity - curr_velocity))

        flow_difficulty += overlap_velocity_buff * dist_ratio * overlapped_notes_weight * velocity_change_multiplier

    if current.obj.kind == OsuObjectKind.SLIDER and with_slider_travel_distance:
        flow_difficulty += current.travel_distance / current.travel_time

    flow_difficulty = pow(flow_difficulty, 1.45)

    return flow_difficulty * smootherstep(curr_distance, 0, NORMALISED_RADIUS)


# ---------------------------------------------------------------------------
# Aim skill
# ---------------------------------------------------------------------------

_SKILL_MULTIPLIER_SNAP = 70.9
_SKILL_MULTIPLIER_AGILITY = 2.35
_SKILL_MULTIPLIER_FLOW = 242.0
_SKILL_MULTIPLIER_TOTAL = 1.12
_COMBINED_SNAP_NORM_EXPONENT = 1.2


def _calculate_snap_flow_probability(ratio: float) -> float:
    k = 7.27
    if ratio == 0:
        return 0.0
    if math.isnan(ratio):
        return 1.0
    return logistic(-k * math.log(ratio))


def _calculate_total_value(snap_difficulty: float, agility_difficulty: float, flow_difficulty: float,
                            touch_device: bool = False, relax: bool = False) -> float:
    combined_snap_difficulty = norm(_COMBINED_SNAP_NORM_EXPONENT, snap_difficulty, agility_difficulty)

    # C# double division by exact zero silently yields Infinity/NaN; Python raises.
    # Replicate IEEE754 semantics rather than crashing (both branches already
    # handled correctly downstream by _calculate_snap_flow_probability).
    if combined_snap_difficulty == 0:
        ratio = math.inf if flow_difficulty > 0 else (math.nan if flow_difficulty == 0 else -math.inf)
    else:
        ratio = flow_difficulty / combined_snap_difficulty
    p_snap = _calculate_snap_flow_probability(ratio)
    p_flow = 1 - p_snap

    if touch_device:
        # We don't adjust agility here since agility represents TD difficulty in a decent enough way.
        snap_difficulty = pow(snap_difficulty, 0.89)
        combined_snap_difficulty = norm(_COMBINED_SNAP_NORM_EXPONENT, snap_difficulty, agility_difficulty)

    if relax:
        combined_snap_difficulty *= 0.75
        flow_difficulty *= 0.6

    total_difficulty = combined_snap_difficulty * p_snap + flow_difficulty * p_flow
    return total_difficulty * _SKILL_MULTIPLIER_TOTAL


class AimSkill:
    def __init__(self, dobjs: list[OsuDifficultyHitObject], include_sliders: bool, decay_weight: float = 0.9, max_section_length: int = 400,
                 mods: frozenset[str] = frozenset(), magnetised_strength: float = 0.5):
        self.dobjs = dobjs
        self.include_sliders = include_sliders
        self.current_strain = 0.0
        self.slider_strains: list[float] = []
        self.decay_weight = decay_weight
        self.mods = mods
        self.magnetised_strength = magnetised_strength

        self._skill = VariableLengthStrainSkill(
            strain_value_of=self._strain_value_of,
            calculate_initial_strain=self._calculate_initial_strain,
            decay_weight=decay_weight,
            max_section_length=max_section_length,
        )

    @staticmethod
    def _strain_decay(ms: float) -> float:
        return pow(0.2, ms / 1000)

    def _calculate_adjusted_difficulty(self, index: int) -> float:
        snap_difficulty = snap_evaluate(self.dobjs, index, self.include_sliders) * _SKILL_MULTIPLIER_SNAP
        agility_difficulty = agility_evaluate(self.dobjs, index) * _SKILL_MULTIPLIER_AGILITY
        flow_difficulty = flow_evaluate(self.dobjs, index, self.include_sliders) * _SKILL_MULTIPLIER_FLOW

        total_difficulty = _calculate_total_value(
            snap_difficulty, agility_difficulty, flow_difficulty,
            touch_device="TD" in self.mods, relax="RX" in self.mods,
        )

        if "MG" in self.mods:
            total_difficulty *= 1.0 - self.magnetised_strength

        current = self.dobjs[index]
        total_difficulty *= 0.985 + pow(max(0.0, current.overall_difficulty), 2) / 4000

        return total_difficulty

    def _strain_value_of(self, index: int, do: OsuDifficultyHitObject) -> float:
        if "AP" in self.mods:
            return 0.0

        decay = self._strain_decay(do.adjusted_delta_time)
        self.current_strain *= decay
        self.current_strain += self._calculate_adjusted_difficulty(index) * (1 - decay)

        if do.obj.kind == OsuObjectKind.SLIDER:
            self.slider_strains.append(self.current_strain)

        return self.current_strain

    def _calculate_initial_strain(self, time: float, index: int, do: OsuDifficultyHitObject, history) -> float:
        prev = previous(self.dobjs, index, 0)
        return self.current_strain * self._strain_decay(time - prev.start_time)

    def process_all(self) -> None:
        for i, do in enumerate(self.dobjs):
            self._skill.process(i, do)

    def get_difficult_sliders(self) -> float:
        if not self.slider_strains:
            return 0.0
        max_slider_strain = max(self.slider_strains)
        if max_slider_strain == 0:
            return 0.0
        return sum(logistic_full(s / max_slider_strain, 0.5, 12.0) for s in self.slider_strains)

    def count_top_weighted_sliders(self, difficulty_value: float) -> float:
        if not self.slider_strains:
            return 0.0
        consistent_top_strain = difficulty_value * (1 - self.decay_weight)
        if consistent_top_strain == 0:
            return 0.0
        return sum(logistic_full(s / consistent_top_strain, 0.88, 10, 1.1) for s in self.slider_strains)

    def count_top_weighted_strains(self, difficulty_value: float) -> float:
        return self._skill.count_top_weighted_strains(difficulty_value)

    def difficulty_value(self) -> float:
        max_section_length = self._skill.max_section_length
        decay_weight = self.decay_weight

        reduced_section_time = 4000
        reduced_strain_baseline = 0.727
        chunk_size = 20

        strains = [p for p in self._skill.get_current_strain_peaks() if p.value > 0]

        time = 0.0
        skip_count = 0

        while len(strains) > skip_count and time < reduced_section_time:
            strain = strains[skip_count]

            added_time = 0.0
            while added_time < strain.section_length:
                t = min(1.0, max(0.0, (time + added_time) / reduced_section_time))
                lerped = 1 + (10 - 1) * t
                scale = math.log10(lerped)
                from .._variable_strain_skill import StrainPeak
                strains.append(StrainPeak(
                    strain.value * (reduced_strain_baseline + (1.0 - reduced_strain_baseline) * scale),
                    min(chunk_size, strain.section_length - added_time),
                ))
                added_time += chunk_size

            time += strain.section_length
            skip_count += 1

        remaining = sorted(strains[skip_count:], key=lambda p: -p.value)

        difficulty = 0.0
        t = 0.0
        for strain in remaining:
            start_time = t
            end_time = t + strain.section_length / max_section_length

            weight = pow(decay_weight, start_time) - pow(decay_weight, end_time)
            difficulty += strain.value * weight
            t = end_time

        return difficulty / (1 - decay_weight)
