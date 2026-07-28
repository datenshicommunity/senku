"""Minimal .osu beatmap parser for osu!mania.

Only extracts what the difficulty/performance engine needs: column count,
overall difficulty, and the note list (start time, column, end time for
long notes). Not a general-purpose beatmap editor/parser.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .._legacy_sort import unstable_sort


@dataclass(frozen=True)
class ManiaNote:
    start_time: float
    end_time: float  # equals start_time for a regular note (non-hold)
    column: int

    @property
    def is_hold(self) -> bool:
        return self.end_time > self.start_time


@dataclass(frozen=True)
class ManiaBeatmap:
    column_count: int
    overall_difficulty: float
    notes: list[ManiaNote]  # sorted by start_time ascending


_HOLD_NOTE_FLAG = 1 << 7  # bit 7 of the hitobject "type" byte marks a long note


def _x_to_column(x: float, column_count: int) -> int:
    """Map a hitobject's x-position (0-512 playfield width) to a column index.

    The reference client does this arithmetic in single-precision float, so
    we deliberately narrow to float32 at each step -- a note landing exactly
    on (or a hair's width from) a column boundary can round differently in
    double precision, silently misclassifying it into the neighbouring
    column for a tiny fraction of notes on any given map.
    """
    divisor = np.float32(512.0) / np.float32(column_count)
    col = int(np.floor(np.float32(x) / divisor))
    return min(max(col, 0), column_count - 1)


def parse_osu_file(text: str) -> ManiaBeatmap:
    section = None
    circle_size = 4.0
    overall_difficulty = 5.0
    raw_notes: list[tuple[float, int, float]] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("//"):
            continue

        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue

        if section == "Difficulty":
            key, _, value = line.partition(":")
            key = key.strip()
            if key == "CircleSize":
                circle_size = float(value.strip())
            elif key == "OverallDifficulty":
                overall_difficulty = float(value.strip())
            continue

        if section == "HitObjects":
            fields = line.split(",")
            if len(fields) < 4:
                continue

            x = float(fields[0])
            start_time = float(fields[2])
            object_type = int(fields[3])

            end_time = start_time
            if object_type & _HOLD_NOTE_FLAG:
                # Mania hold-note extra params: "endTime:sampleSet:sampleIndex:volume:filename"
                extra = fields[5] if len(fields) > 5 else ""
                end_time_str = extra.split(":")[0]
                if end_time_str:
                    end_time = float(end_time_str)

            column_count = max(1, round(circle_size))
            column = _x_to_column(x, column_count)

            raw_notes.append((start_time, column, end_time))

    # Unstable sort keyed on *rounded* start time -- matches the reference
    # client's tie-breaking behaviour for chords/near-simultaneous notes.
    # A stable sort silently orders ties differently, which changes
    # per-column history construction for every note sharing a rounded
    # timestamp with another (chords -- more common on hold-heavy maps).
    def _compare(a: tuple, b: tuple) -> int:
        return round(a[0]) - round(b[0])

    unstable_sort(raw_notes, _compare)
    notes = [ManiaNote(start_time=s, column=c, end_time=e) for s, c, e in raw_notes]

    return ManiaBeatmap(
        column_count=max(1, round(circle_size)),
        overall_difficulty=overall_difficulty,
        notes=notes,
    )
