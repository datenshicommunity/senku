"""Generic strain-decay skill engine shared by every "simple" skill across
rulesets (taiko's colour/rhythm/reading, and similar skills elsewhere):
decay a running strain value over time, track the peak strain per fixed
time window, then combine peaks into a single difficulty number via a
weighted sum of the sorted-descending peaks. Independent implementation
of this recurring pattern; not adapted from any specific codebase.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Protocol


class _HasStartTimeAndDelta(Protocol):
    start_time: float
    delta_time: float


SECTION_LENGTH_MS = 400.0
DEFAULT_DECAY_WEIGHT = 0.9


@dataclass
class StrainDecaySkill:
    skill_multiplier: float
    strain_decay_base: float
    strain_value_of: Callable[[object], float]
    decay_weight: float = DEFAULT_DECAY_WEIGHT
    section_length: float = SECTION_LENGTH_MS

    current_strain: float = field(default=0.0, init=False)
    _section_peaks: list[float] = field(default_factory=list, init=False)
    _current_section_peak: float = field(default=0.0, init=False)
    _current_section_end: float | None = field(default=None, init=False)
    _object_difficulties: list[float] = field(default_factory=list, init=False)
    _previous_object: object | None = field(default=None, init=False)

    def _strain_decay(self, ms: float) -> float:
        return pow(self.strain_decay_base, ms / 1000.0)

    def process(self, obj: _HasStartTimeAndDelta) -> None:
        if self._current_section_end is None:
            self._current_section_end = math.ceil(obj.start_time / self.section_length) * self.section_length

        while obj.start_time > self._current_section_end:
            self._section_peaks.append(self._current_section_peak)
            offset = self._current_section_end - (obj.start_time - obj.delta_time)
            self._current_section_peak = self.current_strain * self._strain_decay(offset)
            self._current_section_end += self.section_length

        self.current_strain *= self._strain_decay(obj.delta_time)
        self.current_strain += self.strain_value_of(obj) * self.skill_multiplier

        self._object_difficulties.append(self.current_strain)
        self._current_section_peak = max(self.current_strain, self._current_section_peak)
        self._previous_object = obj

    def get_object_difficulties(self) -> list[float]:
        return self._object_difficulties

    def get_current_strain_peaks(self) -> list[float]:
        return self._section_peaks + [self._current_section_peak]

    def difficulty_value(self) -> float:
        difficulty = 0.0
        weight = 1.0
        peaks = sorted((p for p in self.get_current_strain_peaks() if p > 0), reverse=True)
        for strain in peaks:
            difficulty += strain * weight
            weight *= self.decay_weight
        return difficulty

    def count_top_weighted_strains(self, difficulty_value: float) -> float:
        if not self._object_difficulties:
            return 0.0
        consistent_top_strain = difficulty_value * (1 - self.decay_weight)
        if consistent_top_strain == 0:
            return float(len(self._object_difficulties))

        from ._diffutils import logistic_full
        return sum(logistic_full(s / consistent_top_strain, 0.88, 10, 1.1) for s in self._object_difficulties)
