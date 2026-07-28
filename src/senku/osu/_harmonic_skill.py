"""Harmonic-weighted difficulty summation, shared by osu!std's Speed and
Reading skills: object difficulties are summed with a weight that decays
per descending-sorted rank, using a harmonic term that boosts the influence
of the hardest objects. Independent implementation; not adapted from any
specific codebase.
"""

from __future__ import annotations

from .._diffutils import logistic_full


class HarmonicSkill:
    def __init__(self, harmonic_scale: float = 1.0, decay_exponent: float = 0.9):
        self.harmonic_scale = harmonic_scale
        self.decay_exponent = decay_exponent
        self.object_difficulties: list[float] = []
        self.object_weight_sum: float = 0.0

    def add(self, difficulty: float) -> None:
        self.object_difficulties.append(difficulty)

    def get_transformed_difficulties(self, difficulties: list[float]) -> list[float]:
        return difficulties

    def difficulty_value(self) -> float:
        self.object_weight_sum = 0.0

        if not self.object_difficulties:
            return 0.0

        difficulties = self.get_transformed_difficulties(self.object_difficulties)

        difficulty = 0.0
        index = 0

        for obj in sorted((d for d in difficulties if d > 0), reverse=True):
            weight = (1 + (self.harmonic_scale / (1 + index))) / (pow(index, self.decay_exponent) + 1 + (self.harmonic_scale / (1 + index)))
            self.object_weight_sum += weight
            difficulty += obj * weight
            index += 1

        return difficulty

    def count_top_weighted_object_difficulties(self, difficulty_value: float) -> float:
        if not self.object_difficulties:
            return 0.0
        if self.object_weight_sum == 0:
            return 0.0

        consistent_top_object = difficulty_value / self.object_weight_sum
        if consistent_top_object == 0:
            return 0.0

        return sum(logistic_full(d / consistent_top_object, 0.88, 10, 1.1) for d in self.object_difficulties)

    @staticmethod
    def difficulty_to_performance(difficulty: float) -> float:
        return 4.0 * pow(difficulty, 3)
