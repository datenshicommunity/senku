"""Rhythm-change difficulty for osu!taiko.

Groups consecutive notes with a stable interval together, then groups
*those* groups together by their own interval pattern, and scores
rhythm changes based on how unusual the ratio between successive
intervals is (ratios near simple fractions like 1:1, 2:1, 3:2 are
easier; ratios near-but-not-exactly 1 are hardest). Independent
implementation; not adapted from any specific codebase.
"""

from __future__ import annotations

import math

from .._diffutils import bell_curve, logistic_full, reverse_lerp, almost_equal
from .preprocessing import TaikoDifficultyHitObject
from .stamina import evaluate_stamina_difficulty_of

_MARGIN_OF_ERROR = 5.0

_COMMON_RATIOS = [
    1.0 / 1, 2.0 / 1, 1.0 / 2, 3.0 / 1, 1.0 / 3, 3.0 / 2, 2.0 / 3, 5.0 / 4, 4.0 / 5,
]


def _closest_common_ratio(actual_ratio: float) -> float:
    return min(_COMMON_RATIOS, key=lambda r: abs(r - actual_ratio))


class SameRhythmGrouping:
    def __init__(self, previous: "SameRhythmGrouping | None", hit_objects: list[TaikoDifficultyHitObject]):
        self.previous = previous
        self.hit_objects = hit_objects

        # DeltaTimeNormaliser.Normalise: cluster delta times within margin of
        # error and replace each with its group's median, to smooth out
        # off-snap timing noise before computing the modal interval.
        deltas = sorted(set(h.delta_time for h in hit_objects))
        sets: list[list[float]] = []
        current_set: list[float] | None = None
        for value in deltas:
            if current_set is not None and abs(value - current_set[0]) <= _MARGIN_OF_ERROR:
                current_set.append(value)
                continue
            current_set = [value]
            sets.append(current_set)

        median_lookup: dict[float, float] = {}
        for s in sets:
            s.sort()
            mid = len(s) // 2
            median = s[mid] if len(s) % 2 == 1 else (s[mid - 1] + s[mid]) / 2
            for v in s:
                median_lookup[v] = median

        normalised_deltas = [median_lookup.get(h.delta_time, h.delta_time) for h in hit_objects[1:]]

        modal_delta = round(normalised_deltas[0]) if normalised_deltas else 0.0

        self.hit_object_interval: float | None = None
        if normalised_deltas:
            prev_interval = previous.hit_object_interval if previous else None
            if prev_interval is not None and abs(modal_delta - prev_interval) <= _MARGIN_OF_ERROR:
                self.hit_object_interval = prev_interval
            else:
                self.hit_object_interval = modal_delta

        prev_interval = previous.hit_object_interval if previous else None
        if prev_interval is not None and self.hit_object_interval is not None:
            self.hit_object_interval_ratio = self.hit_object_interval / prev_interval
        else:
            self.hit_object_interval_ratio = 1.0

        self.interval = math.inf
        if previous is not None:
            if almost_equal(self.start_time, previous.start_time, _MARGIN_OF_ERROR):
                self.interval = 0.0
            else:
                self.interval = self.start_time - previous.start_time

    @property
    def first_hit_object(self) -> TaikoDifficultyHitObject:
        return self.hit_objects[0]

    @property
    def start_time(self) -> float:
        return self.hit_objects[0].start_time

    @property
    def duration(self) -> float:
        return self.hit_objects[-1].start_time - self.hit_objects[0].start_time


class SamePatternGrouping:
    def __init__(self, previous: "SamePatternGrouping | None", groups: list[SameRhythmGrouping]):
        self.previous = previous
        self.groups = groups

    @property
    def group_interval(self) -> float:
        return self.groups[1].interval if len(self.groups) > 1 else self.groups[0].interval

    @property
    def interval_ratio(self) -> float:
        prev = self.previous.group_interval if self.previous else 1.0
        return self.group_interval / prev

    @property
    def first_hit_object(self) -> TaikoDifficultyHitObject:
        return self.groups[0].first_hit_object

    def all_hit_objects(self) -> list[TaikoDifficultyHitObject]:
        result = []
        for g in self.groups:
            result.extend(g.hit_objects)
        return result


class RhythmData:
    __slots__ = ("same_rhythm_group", "same_pattern_group", "ratio")

    def __init__(self, ratio: float):
        self.same_rhythm_group: SameRhythmGrouping | None = None
        self.same_pattern_group: SamePatternGrouping | None = None
        self.ratio = ratio


def _group_by_interval(objects: list) -> list[list]:
    groups: list[list] = []
    i = 0
    n = len(objects)
    while i < n:
        group = [objects[i]]
        i += 1
        advanced_for_increase = False
        while i < n - 1:
            if not almost_equal(objects[i].interval, objects[i + 1].interval, _MARGIN_OF_ERROR):
                if objects[i + 1].interval > objects[i].interval + _MARGIN_OF_ERROR:
                    group.append(objects[i])
                    i += 1
                break
            group.append(objects[i])
            i += 1
        else:
            if n > 2 and i < n and almost_equal(objects[-1].interval, objects[-2].interval, _MARGIN_OF_ERROR):
                group.append(objects[i])
                i += 1
        groups.append(group)
    return groups


def process_and_assign(note_objects: list[TaikoDifficultyHitObject]) -> None:
    for obj in note_objects:
        previous = obj.previous(0)
        if previous is None:
            ratio = 1.0
        else:
            actual_ratio = obj.delta_time / previous.delta_time
            ratio = _closest_common_ratio(actual_ratio)
        obj.rhythm_data = RhythmData(ratio)

    rhythm_groups: list[SameRhythmGrouping] = []
    for grouped in _group_by_interval(note_objects):
        rhythm_groups.append(SameRhythmGrouping(rhythm_groups[-1] if rhythm_groups else None, grouped))

    for group in rhythm_groups:
        for obj in group.hit_objects:
            obj.rhythm_data.same_rhythm_group = group

    pattern_groups: list[SamePatternGrouping] = []
    for grouped in _group_by_interval(rhythm_groups):
        pattern_groups.append(SamePatternGrouping(pattern_groups[-1] if pattern_groups else None, grouped))

    for pgroup in pattern_groups:
        for obj in pgroup.all_hit_objects():
            obj.rhythm_data.same_pattern_group = pgroup


def _ratio_difficulty(ratio: float, terms: int = 8) -> float:
    if not math.isfinite(ratio):
        ratio = 0.0

    difficulty = 0.0
    for i in range(1, terms + 1):
        difficulty += -1.0 * pow(math.cos(i * math.pi * ratio), 4)

    difficulty += terms / (1 + ratio)
    difficulty += bell_curve(ratio, 1, 0.5)
    difficulty -= bell_curve(ratio, 1, 0.3)
    difficulty = max(difficulty, 0.0)
    difficulty /= math.sqrt(8)
    return difficulty


def _repeated_interval_penalty(group: SameRhythmGrouping, hit_window: float, threshold: float = 0.1) -> float:
    def same_interval(start: SameRhythmGrouping, interval_count: int) -> float:
        intervals: list[float] = []
        current = start
        for _ in range(interval_count):
            if current is None:
                break
            if current.hit_object_interval is not None:
                intervals.append(current.hit_object_interval)
            current = current.previous

        if len(intervals) < interval_count:
            return 1.0

        for i in range(len(intervals)):
            for j in range(i + 1, len(intervals)):
                ratio = intervals[i] / intervals[j]
                if abs(1 - ratio) <= threshold:
                    return 0.80
        return 1.0

    long_interval_penalty = same_interval(group, 3)
    short_interval_penalty = same_interval(group, 4) if len(group.hit_objects) < 6 else 1.0
    duration_penalty = max(1 - group.duration * 2 / hit_window, 0.5)

    return min(long_interval_penalty, short_interval_penalty) * duration_penalty


def _long_gap_penalty(previous: SameRhythmGrouping | None) -> float:
    if previous is None:
        return 1.0

    gap_interval = previous.first_hit_object.delta_time
    rhythm_interval = previous.hit_object_interval if previous.hit_object_interval is not None else gap_interval
    rhythm_length = len(previous.hit_objects)

    gap_ratio = gap_interval / max(rhythm_interval, 1)
    gap_factor = logistic_full(gap_ratio, 1.75, 20)
    length_factor = reverse_lerp(rhythm_length, 8, 2)

    return 1.0 - 0.75 * gap_factor * length_factor


def _evaluate_same_rhythm_difficulty(group: SameRhythmGrouping, hit_window: float) -> float:
    interval_difficulty = _ratio_difficulty(group.hit_object_interval_ratio)
    previous_interval = group.previous.hit_object_interval if group.previous else None

    interval_difficulty *= _repeated_interval_penalty(group, hit_window)

    if previous_interval is not None and len(group.hit_objects) > 1:
        expected_duration = previous_interval * len(group.hit_objects)
        duration_difference = group.duration - expected_duration
        if duration_difference > 0:
            interval_difficulty *= logistic_full(duration_difference / hit_window, 0.35, 2, 1)

    interval_difficulty *= logistic_full(group.duration / hit_window, 0.3, 2, 1)

    return pow(interval_difficulty, 0.75)


def evaluate_difficulty_of(hit_object: TaikoDifficultyHitObject) -> float:
    if not hit_object.is_hit:
        return 0.0

    rhythm_data = hit_object.rhythm_data
    hit_window = hit_object.great_hit_window

    same_rhythm = 0.0
    same_pattern = 0.0
    interval_penalty = 0.0
    gap_penalty = 0.0

    if rhythm_data.same_rhythm_group is not None and rhythm_data.same_rhythm_group.first_hit_object is hit_object:
        same_rhythm += 10.0 * _evaluate_same_rhythm_difficulty(rhythm_data.same_rhythm_group, hit_window)
        interval_penalty = _repeated_interval_penalty(rhythm_data.same_rhythm_group, hit_window)
        gap_penalty = _long_gap_penalty(rhythm_data.same_rhythm_group.previous)

    if rhythm_data.same_pattern_group is not None and rhythm_data.same_pattern_group.first_hit_object is hit_object:
        same_pattern += 1.15 * _ratio_difficulty(rhythm_data.same_pattern_group.interval_ratio)

    return max(same_rhythm, same_pattern) * interval_penalty * gap_penalty


def evaluate_strain_value(hit_object: TaikoDifficultyHitObject) -> float:
    difficulty = evaluate_difficulty_of(hit_object)
    stamina_difficulty = evaluate_stamina_difficulty_of(hit_object) - 0.5
    return difficulty * logistic_full(stamina_difficulty, 1 / 15.0, 50.0)
