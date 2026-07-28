"""Builds the per-note difficulty context taiko's skills operate on:
delta time, effective BPM (accounting for slider-velocity changes), and
same-type ("mono") / hit-only neighbour chains. Colour and rhythm
grouping data get attached onto these objects afterwards by their
respective preprocessors (colour.py, rhythm.py).
"""

from __future__ import annotations

import math

from .beatmap import TaikoBeatmap, TaikoObjectKind


def _difficulty_range(difficulty: float, min_value: float, mid_value: float, max_value: float) -> float:
    """Standard OD/AR/CS/HP piecewise-linear scaling used across every ruleset."""
    if difficulty > 5:
        return mid_value + (max_value - mid_value) * (difficulty - 5) / 5
    if difficulty < 5:
        return mid_value - (mid_value - min_value) * (5 - difficulty) / 5
    return mid_value


def _raw_great_hit_window(overall_difficulty: float) -> float:
    return math.floor(_difficulty_range(overall_difficulty, 50, 35, 20)) - 0.5


def great_hit_window_for(overall_difficulty: float, clock_rate: float) -> float:
    """Doubled hit window used internally by the difficulty engine
    (RhythmEvaluator etc). NOT the same value the performance calculator
    uses for its accuracy/deviation estimate -- see
    performance_great_hit_window_for below."""
    return 2 * _raw_great_hit_window(overall_difficulty) / clock_rate


def performance_great_hit_window_for(overall_difficulty: float, clock_rate: float) -> float:
    """Un-doubled hit window, computed independently by the performance
    calculator for its accuracy/deviation estimate -- deliberately NOT the
    same as the difficulty engine's (doubled) great_hit_window_for above."""
    return _raw_great_hit_window(overall_difficulty) / clock_rate


class TaikoDifficultyHitObject:
    def __init__(self, index: int, start_time: float, delta_time: float, kind: TaikoObjectKind,
                 mono_index: int | None, note_index: int | None, effective_bpm: float,
                 great_hit_window: float,
                 all_objects: list["TaikoDifficultyHitObject"],
                 mono_objects: list["TaikoDifficultyHitObject"] | None,
                 note_objects: list["TaikoDifficultyHitObject"]):
        self.index = index
        self.start_time = start_time
        self.delta_time = delta_time
        self.kind = kind
        self.mono_index = mono_index
        self.note_index = note_index
        self.effective_bpm = effective_bpm
        self.great_hit_window = great_hit_window

        self._all_objects = all_objects
        self._mono_objects = mono_objects
        self._note_objects = note_objects

        # Populated later by colour.py / rhythm.py preprocessors.
        self.colour_data = None
        self.rhythm_data = None

    @property
    def is_hit(self) -> bool:
        return self.kind in (TaikoObjectKind.CENTRE, TaikoObjectKind.RIM)

    def previous(self, back: int = 0) -> "TaikoDifficultyHitObject | None":
        i = self.index - (back + 1)
        return self._all_objects[i] if 0 <= i < len(self._all_objects) else None

    def next(self, forward: int = 0) -> "TaikoDifficultyHitObject | None":
        i = self.index + (forward + 1)
        return self._all_objects[i] if 0 <= i < len(self._all_objects) else None

    def previous_mono(self, back: int = 0) -> "TaikoDifficultyHitObject | None":
        if self._mono_objects is None or self.mono_index is None:
            return None
        i = self.mono_index - (back + 1)
        return self._mono_objects[i] if 0 <= i < len(self._mono_objects) else None

    def next_mono(self, forward: int = 0) -> "TaikoDifficultyHitObject | None":
        if self._mono_objects is None or self.mono_index is None:
            return None
        i = self.mono_index + (forward + 1)
        return self._mono_objects[i] if 0 <= i < len(self._mono_objects) else None

    def previous_note(self, back: int = 0) -> "TaikoDifficultyHitObject | None":
        if self.note_index is None:
            return None
        i = self.note_index - (back + 1)
        return self._note_objects[i] if 0 <= i < len(self._note_objects) else None

    def next_note(self, forward: int = 0) -> "TaikoDifficultyHitObject | None":
        if self.note_index is None:
            return None
        i = self.note_index + (forward + 1)
        return self._note_objects[i] if 0 <= i < len(self._note_objects) else None

    @property
    def interval(self) -> float:
        return self.delta_time


def build_difficulty_hit_objects(beatmap: TaikoBeatmap, clock_rate: float = 1.0) -> list[TaikoDifficultyHitObject]:
    notes = beatmap.notes
    if len(notes) < 3:
        return []

    times = [n.start_time / clock_rate for n in notes]
    great_hit_window = great_hit_window_for(beatmap.overall_difficulty, clock_rate)

    all_objects: list[TaikoDifficultyHitObject] = []
    centre_objects: list[TaikoDifficultyHitObject] = []
    rim_objects: list[TaikoDifficultyHitObject] = []
    note_objects: list[TaikoDifficultyHitObject] = []

    # The reference calculator skips the first TWO raw hitobjects entirely --
    # they're never wrapped, only used as timing anchors for the third note.
    for i in range(2, len(notes)):
        note = notes[i]
        delta_time = times[i] - times[i - 1]

        bpm, sv = beatmap.bpm_and_slider_velocity_at(notes[i].start_time)
        effective_bpm = max(1.0, bpm * (beatmap.slider_multiplier * sv * clock_rate))

        mono_index = None
        mono_objects_ref = None
        if note.kind == TaikoObjectKind.CENTRE:
            mono_index = len(centre_objects)
            mono_objects_ref = centre_objects
        elif note.kind == TaikoObjectKind.RIM:
            mono_index = len(rim_objects)
            mono_objects_ref = rim_objects

        note_index = len(note_objects) if note.kind in (TaikoObjectKind.CENTRE, TaikoObjectKind.RIM) else None

        obj = TaikoDifficultyHitObject(
            index=len(all_objects),
            start_time=times[i],
            delta_time=delta_time,
            kind=note.kind,
            mono_index=mono_index,
            note_index=note_index,
            effective_bpm=effective_bpm,
            great_hit_window=great_hit_window,
            all_objects=all_objects,
            mono_objects=mono_objects_ref,
            note_objects=note_objects,
        )

        all_objects.append(obj)
        if note.kind == TaikoObjectKind.CENTRE:
            centre_objects.append(obj)
        elif note.kind == TaikoObjectKind.RIM:
            rim_objects.append(obj)
        if note.kind in (TaikoObjectKind.CENTRE, TaikoObjectKind.RIM):
            note_objects.append(obj)

    return all_objects
