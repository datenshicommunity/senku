"""osu!mania performance (pp) calculation.

Takes a star rating (from difficulty.py) plus a score's judgement counts
and produces a pp value. Independent implementation of the same
publicly-documented formula shape: a star-rating-to-pp curve scaled by a
custom accuracy weighting and a note-count length bonus.
"""

from __future__ import annotations

from dataclasses import dataclass

PERFECT_WEIGHT = 320
GREAT_WEIGHT = 300
GOOD_WEIGHT = 200
OK_WEIGHT = 100
MEH_WEIGHT = 50

LENGTH_BONUS_CAP_HITS = 1500


@dataclass(frozen=True)
class ManiaJudgements:
    n_perfect: int = 0  # MAX / rainbow 300
    n_great: int = 0  # 300
    n_good: int = 0  # 200
    n_ok: int = 0  # 100
    n_meh: int = 0  # 50
    n_miss: int = 0

    @property
    def total_hits(self) -> int:
        return self.n_perfect + self.n_great + self.n_good + self.n_ok + self.n_meh + self.n_miss

    @property
    def custom_accuracy(self) -> float:
        total = self.total_hits
        if total == 0:
            return 0.0
        weighted = (
            self.n_perfect * PERFECT_WEIGHT
            + self.n_great * GREAT_WEIGHT
            + self.n_good * GOOD_WEIGHT
            + self.n_ok * OK_WEIGHT
            + self.n_meh * MEH_WEIGHT
        )
        return weighted / (total * PERFECT_WEIGHT)


def calculate_pp(
    star_rating: float,
    judgements: ManiaJudgements,
    no_fail: bool = False,
    easy: bool = False,
) -> float:
    accuracy = min(1.0, max(0.0, judgements.custom_accuracy))

    difficulty_value = (
        8.0
        * pow(max(star_rating - 0.15, 0.05), 2.2)
        * max(0.0, 5 * accuracy - 4)
        * (1 + 0.1 * min(1.0, judgements.total_hits / LENGTH_BONUS_CAP_HITS))
    )

    multiplier = 1.0
    if no_fail:
        multiplier *= 0.75
    if easy:
        multiplier *= 0.5

    return difficulty_value * multiplier
