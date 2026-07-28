"""Reading difficulty for osu!taiko -- how hard fast/high slider-velocity
sections are to read on-screen, independent of the mechanical/rhythm
demand. Independent implementation of the same velocity-bucket concept
(mid-velocity and high-velocity contribution curves); not adapted from
any specific codebase.
"""

from __future__ import annotations

from .._diffutils import logistic_full
from .preprocessing import TaikoDifficultyHitObject

_MID_VELOCITY_MIN, _MID_VELOCITY_MAX = 360.0, 480.0
_HIGH_VELOCITY_MIN, _HIGH_VELOCITY_MAX = 480.0, 640.0


def evaluate_difficulty_of(note_object: TaikoDifficultyHitObject) -> float:
    mid_centre = (_MID_VELOCITY_MIN + _MID_VELOCITY_MAX) / 2
    mid_range = _MID_VELOCITY_MAX - _MID_VELOCITY_MIN
    high_centre = (_HIGH_VELOCITY_MIN + _HIGH_VELOCITY_MAX) / 2
    high_range = _HIGH_VELOCITY_MAX - _HIGH_VELOCITY_MIN

    effective_bpm = max(1.0, note_object.effective_bpm)

    mid_velocity_difficulty = 0.5 * logistic_full(effective_bpm, mid_centre, 1.0 / (mid_range / 10))

    expected_delta_time = 21000.0 / effective_bpm
    object_density = expected_delta_time / max(1.0, note_object.delta_time)

    density_penalty = logistic_full(object_density, 0.925, 15)

    high_velocity_difficulty = (1.0 - 0.33 * density_penalty) * logistic_full(
        effective_bpm, high_centre + 8 * density_penalty, (1.0 + 0.5 * density_penalty) / (high_range / 10)
    )

    return mid_velocity_difficulty + high_velocity_difficulty


class ReadingSkillState:
    def __init__(self):
        self.current_strain = 0.0

    def strain_value_at(self, hit_object: TaikoDifficultyHitObject) -> float:
        if not hit_object.is_hit:
            return 0.0

        mono_streak = hit_object.colour_data.mono_streak if hit_object.colour_data else None
        index = mono_streak.hit_objects.index(hit_object) if mono_streak is not None else 0

        self.current_strain *= logistic_full(index, 4, -1 / 25.0, 0.5) + 0.5
        self.current_strain *= 0.4  # StrainDecayBase
        self.current_strain += evaluate_difficulty_of(hit_object) * 1.0  # SkillMultiplier

        return self.current_strain
