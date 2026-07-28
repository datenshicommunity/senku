"""osu!std Speed skill: models the difficulty of tapping/pressing keys in
time, combining a base tapping-speed evaluator with a rhythm-complexity
evaluator that rewards irregular but structured rhythms ("islands" of
consistent delta-time) and penalizes doubletappable patterns. Independent
implementation; not adapted from any specific codebase.
"""

from __future__ import annotations

import math

from .._diffutils import logistic_full, milliseconds_to_bpm, reverse_lerp, safe_truncate, smoothstep_bell_curve
from ._harmonic_skill import HarmonicSkill
from .beatmap import OsuObjectKind
from .preprocessing import MIN_DELTA_TIME as _MIN_DELTA_TIME
from .preprocessing import OsuDifficultyHitObject, next_obj, previous

# ---------------------------------------------------------------------------
# SpeedEvaluator
# ---------------------------------------------------------------------------

def _speed_high_bpm_bonus(ms: float) -> float:
    return 1 / (1 - pow(0.3, ms / 1000))


def speed_evaluate(dobjs: list[OsuDifficultyHitObject], index: int) -> float:
    current = dobjs[index]
    if current.obj.kind == OsuObjectKind.SPINNER:
        return 0.0

    min_speed_bonus = 200.0
    speed_balancing_factor = 40.0

    strain_time = current.adjusted_delta_time
    double_tap_feasibility = 1.0 - current.calculate_double_tap_feasibility(next_obj(dobjs, index, 0))

    strain_time /= min(max((strain_time / current.hit_window_great) / 0.93, 0.92), 1.0)

    speed_bonus = 0.0
    if milliseconds_to_bpm(strain_time) > min_speed_bonus:
        speed_bonus = 0.75 * pow((60000.0 / 4 / min_speed_bonus - strain_time) / speed_balancing_factor, 2)

    speed_difficulty = (1 + speed_bonus) * 1000 / strain_time
    speed_difficulty *= _speed_high_bpm_bonus(current.adjusted_delta_time)

    return speed_difficulty * double_tap_feasibility


# ---------------------------------------------------------------------------
# RhythmEvaluator
# ---------------------------------------------------------------------------

_INT_MAX = 2_147_483_647


class _Island:
    def __init__(self, delta: int):
        self.delta = max(delta, int(_MIN_DELTA_TIME))
        self.delta_count = 1
        self.occurrences = 1

    def add_delta(self, delta: int) -> None:
        if self.delta == _INT_MAX:
            self.delta = max(delta, int(_MIN_DELTA_TIME))
        self.delta_count += 1

    def is_similar_polarity(self, other: "_Island", epsilon: float) -> bool:
        if self.delta_count <= 1 or other.delta_count <= 1:
            return False
        return abs(self.delta - other.delta) < epsilon and self.delta_count % 2 == other.delta_count % 2

    def almost_equals(self, other: "_Island", epsilon: float) -> bool:
        return abs(self.delta - other.delta) < epsilon and self.delta_count == other.delta_count


def _get_effective_difficulty(delta_difference_ratio: float) -> float:
    rhythm_ratio_difficulty_multiplier = 26.0
    delta_difference_fraction = delta_difference_ratio - safe_truncate(delta_difference_ratio)
    return 1.0 + rhythm_ratio_difficulty_multiplier * min(0.5, smoothstep_bell_curve(delta_difference_fraction))


def rhythm_evaluate(dobjs: list[OsuDifficultyHitObject], index: int) -> float:
    current = dobjs[index]
    if current.obj.kind == OsuObjectKind.SPINNER:
        return 0.0

    history_time_max = 5 * 1000
    history_objects_max = 32
    rhythm_overall_multiplier = 0.95

    rhythm_complexity_sum = 0.0

    delta_difference_epsilon = current.hit_window_great * 0.3

    island = _Island(_INT_MAX)
    previous_island = _Island(_INT_MAX)

    islands: list[_Island] = []

    start_difficulty = 0.0
    first_delta_switch = False

    historical_note_count = min(index, history_objects_max)

    rhythm_start = 0
    while rhythm_start < historical_note_count - 2 and current.start_time - previous(dobjs, index, rhythm_start).start_time < history_time_max:
        rhythm_start += 1

    prev_obj = previous(dobjs, index, rhythm_start)
    prev_prev_obj = previous(dobjs, index, rhythm_start + 1)

    for i in range(rhythm_start, 0, -1):
        curr_obj = previous(dobjs, index, i - 1)

        if curr_obj.obj.kind == OsuObjectKind.SPINNER:
            continue

        time_decay = (history_time_max - (current.start_time - curr_obj.start_time)) / history_time_max
        note_decay = float(historical_note_count - i) / historical_note_count if historical_note_count > 0 else 0.0

        curr_historical_decay = min(note_decay, time_decay)

        delta_min_value = 1e-7

        curr_delta = max(curr_obj.delta_time, delta_min_value)
        prev_delta = max(prev_obj.delta_time, delta_min_value)

        delta_difference = abs(prev_delta - curr_delta)

        if island.delta == _INT_MAX:
            island = _Island(int(curr_delta))

        delta_difference_ratio = max(prev_delta, curr_delta) / min(prev_delta, curr_delta)
        difference_multiplier = min(max(2.0 - delta_difference_ratio / 8.0, 0.0), 1.0)
        window_penalty = min(max((delta_difference - delta_difference_epsilon) / delta_difference_epsilon, 0.0), 1.0)

        effective_difficulty = _get_effective_difficulty(delta_difference_ratio) * window_penalty * difference_multiplier

        if prev_obj.obj.kind == OsuObjectKind.SLIDER:
            slider_lazy_end_delta = curr_obj.minimum_jump_time
            slider_lazy_delta_difference_ratio = max(slider_lazy_end_delta, curr_delta) / min(slider_lazy_end_delta, curr_delta)

            slider_real_end_delta = curr_obj.last_object_end_delta_time
            slider_real_delta_difference_ratio = max(slider_real_end_delta, curr_delta) / min(slider_real_end_delta, curr_delta)

            slider_effective_difficulty = min(_get_effective_difficulty(slider_lazy_delta_difference_ratio), _get_effective_difficulty(slider_real_delta_difference_ratio))
            effective_difficulty = min(slider_effective_difficulty, effective_difficulty)

        if delta_difference < delta_difference_epsilon:
            island.add_delta(int(curr_delta))

        if first_delta_switch:
            if delta_difference > delta_difference_epsilon:
                if curr_obj.obj.kind == OsuObjectKind.SLIDER:
                    effective_difficulty *= 0.5

                if island.is_similar_polarity(previous_island, delta_difference_epsilon):
                    effective_difficulty *= 0.5

                if max(prev_prev_obj.delta_time, delta_min_value) > prev_delta + delta_difference_epsilon and prev_delta > curr_delta + delta_difference_epsilon:
                    effective_difficulty *= 0.125

                if previous_island.delta_count == island.delta_count:
                    effective_difficulty *= 0.5

                is_speeding_up = prev_delta > curr_delta + delta_difference_epsilon
                if is_speeding_up:
                    effective_difficulty *= 0.65

                found = False
                for existing_island in islands:
                    if existing_island.almost_equals(island, delta_difference_epsilon):
                        if previous_island.almost_equals(island, delta_difference_epsilon):
                            existing_island.occurrences += 1

                        power = logistic_full(island.delta, 58.33, 0.24, 2.75)
                        effective_difficulty *= min(3.0 / existing_island.occurrences, pow(1.0 / existing_island.occurrences, power))

                        found = True
                        break

                if not found and island.delta_count > 0:
                    islands.append(island)

                effective_difficulty *= 1 - prev_obj.calculate_double_tap_feasibility(curr_obj) * 0.75

                if island.delta_count > 1:
                    rhythm_complexity_sum += math.sqrt(effective_difficulty * start_difficulty) * curr_historical_decay
                else:
                    rhythm_complexity_sum += 0.7 * curr_historical_decay

                start_difficulty = effective_difficulty

                if prev_delta + delta_difference_epsilon < curr_delta:
                    first_delta_switch = False

                previous_island = island
                island = _Island(int(curr_delta))
        elif prev_delta > curr_delta + delta_difference_epsilon:
            first_delta_switch = True

            if curr_obj.obj.kind == OsuObjectKind.SLIDER:
                effective_difficulty *= 0.6
            if prev_obj.obj.kind == OsuObjectKind.SLIDER:
                effective_difficulty *= 0.6

            start_difficulty = effective_difficulty
            island = _Island(int(curr_delta))

        prev_prev_obj = prev_obj
        prev_obj = curr_obj

    rhythm_complexity_sum *= reverse_lerp(island.delta_count, 22, 3)

    return math.sqrt(4 + rhythm_complexity_sum * rhythm_overall_multiplier) / 2.0


# ---------------------------------------------------------------------------
# Speed skill
# ---------------------------------------------------------------------------

class SpeedSkill:
    def __init__(self, dobjs: list[OsuDifficultyHitObject], mods: frozenset[str] = frozenset()):
        self.dobjs = dobjs
        self.current_strain = 0.0
        self.slider_strains: list[float] = []
        self.mods = mods
        self._harmonic = HarmonicSkill(harmonic_scale=20.0, decay_exponent=0.9)

    @staticmethod
    def _strain_decay(ms: float) -> float:
        return pow(0.3, ms / 1000)

    def _calculate_adjusted_difficulty(self, index: int) -> float:
        difficulty = speed_evaluate(self.dobjs, index)
        if "AP" in self.mods:
            difficulty *= 0.5
        return difficulty

    def _object_difficulty_of(self, index: int) -> float:
        if "RX" in self.mods:
            return 0.0

        skill_multiplier = 1.16
        do = self.dobjs[index]

        decay = self._strain_decay(do.adjusted_delta_time)
        self.current_strain *= decay
        self.current_strain += self._calculate_adjusted_difficulty(index) * (1 - decay) * skill_multiplier

        current_rhythm = rhythm_evaluate(self.dobjs, index)
        total_strain = self.current_strain * current_rhythm

        if do.obj.kind == OsuObjectKind.SLIDER:
            self.slider_strains.append(total_strain)

        return total_strain

    def process_all(self) -> None:
        for i in range(len(self.dobjs)):
            self._harmonic.add(self._object_difficulty_of(i))

    def difficulty_value(self) -> float:
        return self._harmonic.difficulty_value()

    def relevant_object_count(self) -> float:
        if not self._harmonic.object_difficulties:
            return 0.0
        max_strain = max(self._harmonic.object_difficulties)
        if max_strain == 0:
            return 0.0
        return sum(logistic_full(s / max_strain, 0.5, 12.0) for s in self._harmonic.object_difficulties)

    def count_top_weighted_object_difficulties(self, difficulty_value: float) -> float:
        return self._harmonic.count_top_weighted_object_difficulties(difficulty_value)

    def count_top_weighted_sliders(self, difficulty_value: float) -> float:
        if not self.slider_strains:
            return 0.0
        if self._harmonic.object_weight_sum == 0:
            return 0.0
        consistent_top_object = difficulty_value / self._harmonic.object_weight_sum
        if consistent_top_object == 0:
            return 0.0
        return sum(logistic_full(s / consistent_top_object, 0.88, 10, 1.1) for s in self.slider_strains)
