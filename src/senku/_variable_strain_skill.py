"""Variable-length strain aggregation (as opposed to the fixed-400ms
sections used by _strain_skill.StrainDecaySkill). A new candidate "peak" is
opened for every object; when a lower-strain run follows a higher peak, the
lower values are queued rather than immediately closing the section, so a
single higher-difficulty object isn't diluted by an immediately-following
easier one. Independent implementation; not adapted from any specific
codebase.
"""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass, field


@dataclass
class StrainPeak:
    value: float
    section_length: float

    def __post_init__(self):
        self.section_length = round(self.section_length)


@dataclass
class VariableLengthStrainSkill:
    strain_value_of: callable  # (index, obj) -> float
    calculate_initial_strain: callable  # (time, index, obj, history) -> float
    decay_weight: float = 0.9
    max_section_length: int = 400

    _current_section_peak: float = 0.0
    _current_section_begin: float = 0.0
    _current_section_end: float = 0.0
    _max_stored_length: float = field(init=False, default=0.0)
    _strain_peaks: list = field(default_factory=list)
    _total_length: float = 0.0
    _queued_strains: list = field(default_factory=list)  # list of (strain_value, start_time)
    _final_peak: StrainPeak | None = None
    _object_difficulties: list = field(default_factory=list)
    _history: list = field(default_factory=list)

    def __post_init__(self):
        self._max_stored_length = 11 / (1 - self.decay_weight)

    def process(self, index: int, obj) -> float:
        self._history.append(obj)

        if index == 0:
            self._current_section_begin = obj.start_time
            self._current_section_end = self._current_section_begin + self.max_section_length
            self._current_section_peak = self.strain_value_of(index, obj)
            self._object_difficulties.append(self._current_section_peak)
            return self._current_section_peak

        self._backfill_peaks(index, obj)

        current_strain = self.strain_value_of(index, obj)
        self._object_difficulties.append(current_strain)

        if current_strain > self._current_section_peak:
            self._queued_strains.clear()
            self._save_current_peak(obj.start_time - self._current_section_begin)
            self._current_section_begin = obj.start_time
            self._current_section_end = self._current_section_begin + self.max_section_length
            self._current_section_peak = current_strain
        else:
            while self._queued_strains and self._queued_strains[-1][0] < current_strain:
                self._queued_strains.pop()
            self._queued_strains.append((current_strain, obj.start_time))

        return current_strain

    def _backfill_peaks(self, index: int, obj) -> None:
        while obj.start_time > self._current_section_end:
            self._save_current_peak(self._current_section_end - self._current_section_begin)
            self._current_section_begin = self._current_section_end

            if self._queued_strains:
                strain, start_time = self._queued_strains.pop(0)
                self._current_section_end = start_time + self.max_section_length
                self._start_new_section_from(self._current_section_begin, index, obj)
                self._current_section_peak = max(self._current_section_peak, strain)
            else:
                self._current_section_end = self._current_section_begin + self.max_section_length
                self._start_new_section_from(self._current_section_begin, index, obj)

    def _start_new_section_from(self, time: float, index: int, obj) -> None:
        self._current_section_peak = self.calculate_initial_strain(time, index, obj, self._history)

    def _save_current_peak(self, section_length: float) -> None:
        if self._final_peak is not None:
            if self._final_peak in self._strain_peaks:
                self._strain_peaks.remove(self._final_peak)
            self._final_peak = None

        peak = StrainPeak(self._current_section_peak, section_length)
        # Maintains descending-by-value sort order (matches List.AddInPlace + StrainPeak.CompareTo).
        insert_at = bisect.bisect_left([-p.value for p in self._strain_peaks], -peak.value)
        self._strain_peaks.insert(insert_at, peak)
        self._total_length += peak.section_length

        while self._total_length > self._max_stored_length * self.max_section_length:
            last = self._strain_peaks.pop()
            self._total_length -= last.section_length

    def get_current_strain_peaks(self) -> list[StrainPeak]:
        if self._final_peak is None:
            self._final_peak = StrainPeak(self._current_section_peak, self._current_section_end - self._current_section_begin)
            insert_at = bisect.bisect_left([-p.value for p in self._strain_peaks], -self._final_peak.value)
            self._strain_peaks.insert(insert_at, self._final_peak)
        return list(self._strain_peaks)

    def count_top_weighted_strains(self, difficulty_value: float) -> float:
        if not self._object_difficulties:
            return 0.0

        consistent_top_strain = difficulty_value * (1 - self.decay_weight)
        if consistent_top_strain == 0:
            return float(len(self._object_difficulties))

        from ._diffutils import logistic_full
        return sum(logistic_full(s / consistent_top_strain, 0.88, 10, 1.1) for s in self._object_difficulties)
