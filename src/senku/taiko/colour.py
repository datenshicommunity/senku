"""Colour ("don"/"kat" pattern) difficulty for osu!taiko.

Encodes the note sequence into a 3-level hierarchy -- runs of same-type
hits (MonoStreak), same-length runs grouped together (AlternatingMonoPattern),
and repeated groupings of those (RepeatingHitPatterns) -- then scores the
first note of each level based on how deep/long the pattern is and how
often it repeats. Independent implementation of the same tiered-pattern
concept; not adapted from any specific codebase.
"""

from __future__ import annotations

import math

from .._diffutils import logistic
from .beatmap import TaikoObjectKind
from .preprocessing import TaikoDifficultyHitObject

_MAX_REPETITION_INTERVAL = 16


class MonoStreak:
    def __init__(self):
        self.hit_objects: list[TaikoDifficultyHitObject] = []
        self.parent: "AlternatingMonoPattern | None" = None
        self.index: int = 0

    @property
    def first_hit_object(self) -> TaikoDifficultyHitObject:
        return self.hit_objects[0]

    @property
    def last_hit_object(self) -> TaikoDifficultyHitObject:
        return self.hit_objects[-1]

    @property
    def hit_type(self) -> TaikoObjectKind:
        return self.hit_objects[0].kind

    @property
    def run_length(self) -> int:
        return len(self.hit_objects)


class AlternatingMonoPattern:
    def __init__(self):
        self.mono_streaks: list[MonoStreak] = []
        self.parent: "RepeatingHitPatterns | None" = None
        self.index: int = 0

    @property
    def first_hit_object(self) -> TaikoDifficultyHitObject:
        return self.mono_streaks[0].first_hit_object

    def has_identical_mono_length(self, other: "AlternatingMonoPattern") -> bool:
        return other.mono_streaks[0].run_length == self.mono_streaks[0].run_length

    def is_repetition_of(self, other: "AlternatingMonoPattern") -> bool:
        return (
            self.has_identical_mono_length(other)
            and len(other.mono_streaks) == len(self.mono_streaks)
            and other.mono_streaks[0].hit_type == self.mono_streaks[0].hit_type
        )


class RepeatingHitPatterns:
    def __init__(self, previous: "RepeatingHitPatterns | None"):
        self.alternating_mono_patterns: list[AlternatingMonoPattern] = []
        self.previous = previous
        self.repetition_interval = _MAX_REPETITION_INTERVAL + 1

    @property
    def first_hit_object(self) -> TaikoDifficultyHitObject:
        return self.alternating_mono_patterns[0].first_hit_object

    def _is_repetition_of(self, other: "RepeatingHitPatterns") -> bool:
        if len(self.alternating_mono_patterns) != len(other.alternating_mono_patterns):
            return False
        for i in range(min(len(self.alternating_mono_patterns), 2)):
            if not self.alternating_mono_patterns[i].has_identical_mono_length(other.alternating_mono_patterns[i]):
                return False
        return True

    def find_repetition_interval(self) -> None:
        if self.previous is None:
            self.repetition_interval = _MAX_REPETITION_INTERVAL + 1
            return

        other = self.previous
        interval = 1
        while interval < _MAX_REPETITION_INTERVAL:
            if self._is_repetition_of(other):
                self.repetition_interval = min(interval, _MAX_REPETITION_INTERVAL)
                return
            other = other.previous
            if other is None:
                break
            interval += 1

        self.repetition_interval = _MAX_REPETITION_INTERVAL + 1


class ColourData:
    __slots__ = ("mono_streak", "alternating_mono_pattern", "repeating_hit_pattern")

    def __init__(self):
        self.mono_streak: MonoStreak | None = None
        self.alternating_mono_pattern: AlternatingMonoPattern | None = None
        self.repeating_hit_pattern: RepeatingHitPatterns | None = None

    def previous_colour_change(self) -> TaikoDifficultyHitObject | None:
        if self.mono_streak is None:
            return None
        return self.mono_streak.first_hit_object.previous_note(0)

    def next_colour_change(self) -> TaikoDifficultyHitObject | None:
        if self.mono_streak is None:
            return None
        return self.mono_streak.last_hit_object.next_note(0)


def _hit_type_or_none(obj: TaikoDifficultyHitObject) -> TaikoObjectKind | None:
    """CENTRE/RIM are real hit types; drumroll/swell both map to "no type"
    (matching the reference's `(BaseObject as Hit)?.Type` -- both are null,
    so two consecutive non-hits never start a new streak between them)."""
    return obj.kind if obj.kind in (TaikoObjectKind.CENTRE, TaikoObjectKind.RIM) else None


def _encode_mono_streaks(objects: list[TaikoDifficultyHitObject]) -> list[MonoStreak]:
    streaks: list[MonoStreak] = []
    current: MonoStreak | None = None

    for obj in objects:
        previous = obj.previous_note(0)
        if current is None or previous is None or _hit_type_or_none(obj) != _hit_type_or_none(previous):
            current = MonoStreak()
            streaks.append(current)
        current.hit_objects.append(obj)

    return streaks


def _encode_alternating_mono_patterns(streaks: list[MonoStreak]) -> list[AlternatingMonoPattern]:
    patterns: list[AlternatingMonoPattern] = []
    current: AlternatingMonoPattern | None = None

    for i, streak in enumerate(streaks):
        if current is None or streak.run_length != streaks[i - 1].run_length:
            current = AlternatingMonoPattern()
            patterns.append(current)
        current.mono_streaks.append(streak)

    return patterns


def _encode_repeating_hit_patterns(patterns: list[AlternatingMonoPattern]) -> list[RepeatingHitPatterns]:
    hit_patterns: list[RepeatingHitPatterns] = []
    current: RepeatingHitPatterns | None = None

    i = 0
    while i < len(patterns):
        current = RepeatingHitPatterns(current)

        is_coupled = i < len(patterns) - 2 and patterns[i].is_repetition_of(patterns[i + 2])

        if not is_coupled:
            current.alternating_mono_patterns.append(patterns[i])
        else:
            while is_coupled:
                current.alternating_mono_patterns.append(patterns[i])
                i += 1
                is_coupled = i < len(patterns) - 2 and patterns[i].is_repetition_of(patterns[i + 2])

            current.alternating_mono_patterns.append(patterns[i])
            current.alternating_mono_patterns.append(patterns[i + 1])
            i += 1

        hit_patterns.append(current)
        i += 1

    for hp in hit_patterns:
        hp.find_repetition_interval()

    return hit_patterns


def process_and_assign(objects: list[TaikoDifficultyHitObject]) -> None:
    streaks = _encode_mono_streaks(objects)
    patterns = _encode_alternating_mono_patterns(streaks)
    hit_patterns = _encode_repeating_hit_patterns(patterns)

    for hp in hit_patterns:
        for i, pattern in enumerate(hp.alternating_mono_patterns):
            pattern.parent = hp
            pattern.index = i
            for j, streak in enumerate(pattern.mono_streaks):
                streak.parent = pattern
                streak.index = j
                for obj in streak.hit_objects:
                    obj.colour_data = ColourData()
                    obj.colour_data.repeating_hit_pattern = hp
                    obj.colour_data.alternating_mono_pattern = pattern
                    obj.colour_data.mono_streak = streak


def _consistent_ratio_penalty(hit_object: TaikoDifficultyHitObject, threshold: float = 0.01, max_objects_to_check: int = 64) -> float:
    consistent_ratio_count = 0
    total_ratio_count = 0.0
    recent_ratios: list[float] = []

    current = hit_object
    previous_hit_object = current.previous(1)

    for _ in range(max_objects_to_check):
        if current.index <= 1:
            break

        current_ratio = current.rhythm_data.ratio
        previous_ratio = previous_hit_object.rhythm_data.ratio
        recent_ratios.append(current_ratio)

        if abs(1 - current_ratio / previous_ratio) <= threshold:
            consistent_ratio_count += 1
            total_ratio_count += current_ratio
            break

        # NOTE: previous_hit_object is deliberately NOT reassigned here --
        # the reference implementation only walks `current` backwards each
        # iteration, comparing against the same fixed previous_hit_object
        # throughout. Reproduced exactly rather than "corrected".
        current = previous_hit_object

    if consistent_ratio_count > 0:
        return 1 - total_ratio_count / (consistent_ratio_count + 1) * 0.80

    if len(recent_ratios) <= 1:
        return 1.0

    mean = sum(recent_ratios) / len(recent_ratios)
    max_deviation = max(abs(r - mean) for r in recent_ratios)

    from .._diffutils import smootherstep
    return 0.7 + 0.3 * smootherstep(max_deviation, 0.0, 1.0)


def _evaluate_mono_streak_difficulty(streak: MonoStreak) -> float:
    return logistic(math.e * streak.index - 2 * math.e) * _evaluate_alternating_mono_pattern_difficulty(streak.parent) * 0.5


def _evaluate_alternating_mono_pattern_difficulty(pattern: AlternatingMonoPattern) -> float:
    return logistic(math.e * pattern.index - 2 * math.e) * _evaluate_repeating_hit_pattern_difficulty(pattern.parent)


def _evaluate_repeating_hit_pattern_difficulty(pattern: RepeatingHitPatterns) -> float:
    return 2 * (1 - logistic(math.e * pattern.repetition_interval - 2 * math.e))


def evaluate_difficulty_of(hit_object: TaikoDifficultyHitObject) -> float:
    colour_data = hit_object.colour_data
    difficulty = 0.0

    if colour_data.mono_streak is not None and colour_data.mono_streak.first_hit_object is hit_object:
        difficulty += _evaluate_mono_streak_difficulty(colour_data.mono_streak)

    if colour_data.alternating_mono_pattern is not None and colour_data.alternating_mono_pattern.first_hit_object is hit_object:
        difficulty += _evaluate_alternating_mono_pattern_difficulty(colour_data.alternating_mono_pattern)

    if colour_data.repeating_hit_pattern is not None and colour_data.repeating_hit_pattern.first_hit_object is hit_object:
        difficulty += _evaluate_repeating_hit_pattern_difficulty(colour_data.repeating_hit_pattern)

    difficulty *= _consistent_ratio_penalty(hit_object)
    return difficulty
