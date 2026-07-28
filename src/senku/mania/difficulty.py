"""osu!mania difficulty (star rating) engine.

Independent from-scratch implementation of the same publicly-documented
strain model osu!'s own mania difficulty calculator uses: a two-channel
(per-column "individual" + global "overall") exponential-decay strain
accumulator, aggregated into star rating via a weighted sum of
per-section peak strains.

Not a line-by-line port of any specific codebase -- written from
first-principles understanding of the algorithm shape (decay-based
strain, chord handling, hold-note overlap bonuses, section-peak
weighting) plus empirical calibration against known-correct star
rating values.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .beatmap import ManiaBeatmap

INDIVIDUAL_DECAY_BASE = 0.125
OVERALL_DECAY_BASE = 0.30
SECTION_LENGTH_MS = 400
SECTION_DECAY_WEIGHT = 0.9
STAR_RATING_SCALE = 0.018
RELEASE_THRESHOLD_MS = 30
RELEASE_LOGISTIC_MULTIPLIER = 0.27
OVERLAP_EPSILON_MS = 1.0  # tolerance for "definitely bigger" style comparisons


def _decay(value: float, elapsed_ms: float, base: float) -> float:
    return value * math.pow(base, elapsed_ms / 1000.0)


def _logistic(x: float, midpoint_offset: float, multiplier: float, max_value: float = 1.0) -> float:
    return max_value / (1.0 + math.exp(multiplier * (midpoint_offset - x)))


@dataclass
class _NoteEvent:
    start: float
    end: float
    column: int
    delta_time: float  # vs previous note overall (time order)
    column_gap: float  # vs previous note in the same column
    overlapping_columns: list[tuple[float, float]] = field(default_factory=list)
    # (start, end) of the most recent note seen in each *other* column, as of
    # just before this note is processed -- mirrors what the reference
    # implementation calls "the previous hit object per column".


def _build_note_events(beatmap: ManiaBeatmap, clock_rate: float) -> list[_NoteEvent]:
    notes = beatmap.notes
    if len(notes) < 2:
        return []

    starts = [n.start_time / clock_rate for n in notes]
    ends = [n.end_time / clock_rate for n in notes]
    columns = [n.column for n in notes]

    # The very first note in the map never generates a strain event itself,
    # and is never recorded into the per-column history either -- it only
    # serves as the timing anchor for the second note's delta time.
    last_seen: list[tuple[float, float] | None] = [None] * beatmap.column_count
    last_column_index: list[int | None] = [None] * beatmap.column_count

    events: list[_NoteEvent] = []
    for i in range(1, len(notes)):
        col = columns[i]
        prev_col_idx = last_column_index[col]
        column_gap = starts[i] - starts[prev_col_idx] if prev_col_idx is not None else starts[i]

        events.append(
            _NoteEvent(
                start=starts[i],
                end=ends[i],
                column=col,
                delta_time=starts[i] - starts[i - 1],
                column_gap=column_gap,
                overlapping_columns=[v for v in last_seen if v is not None],
            )
        )

        last_seen[col] = (starts[i], ends[i])
        last_column_index[col] = i

    return events


def _individual_strain_value(event: _NoteEvent) -> float:
    hold_factor = 1.0
    for (other_start, other_end) in event.overlapping_columns:
        if other_end - event.end > OVERLAP_EPSILON_MS and event.start - other_start > OVERLAP_EPSILON_MS:
            hold_factor = 1.25
            break
    return 2.0 * hold_factor


def _overall_strain_value(event: _NoteEvent) -> float:
    is_overlapping = False
    closest_end_gap = abs(event.end - event.start)
    hold_factor = 1.0

    for (other_start, other_end) in event.overlapping_columns:
        if (
            other_end - event.start > OVERLAP_EPSILON_MS
            and event.end - other_end > OVERLAP_EPSILON_MS
            and event.start - other_start > OVERLAP_EPSILON_MS
        ):
            is_overlapping = True

        if other_end - event.end > OVERLAP_EPSILON_MS and event.start - other_start > OVERLAP_EPSILON_MS:
            hold_factor = 1.25

        closest_end_gap = min(closest_end_gap, abs(event.end - other_end))

    hold_addition = 0.0
    if is_overlapping:
        hold_addition = _logistic(closest_end_gap, RELEASE_THRESHOLD_MS, RELEASE_LOGISTIC_MULTIPLIER)

    return (1.0 + hold_addition) * hold_factor


def star_rating(beatmap: ManiaBeatmap, clock_rate: float = 1.0) -> float:
    events = _build_note_events(beatmap, clock_rate)
    if not events:
        return 0.0

    individual_strains = [0.0] * beatmap.column_count
    highest_individual = 0.0
    overall_strain = 1.0

    section_peaks: list[float] = []
    current_section_peak = 0.0
    current_section_end = math.ceil(events[0].start / SECTION_LENGTH_MS) * SECTION_LENGTH_MS

    prev_delta_time_for_chord_check = None

    for event in events:
        # Roll section boundaries forward, snapshotting the peak of each
        # completed section before starting the next.
        while event.start > current_section_end:
            section_peaks.append(current_section_peak)
            # Initial strain of the new section = decayed value of whatever
            # was carried over from before the boundary.
            offset = current_section_end - (event.start - event.delta_time)
            current_section_peak = _decay(highest_individual, offset, INDIVIDUAL_DECAY_BASE) + _decay(
                overall_strain, offset, OVERALL_DECAY_BASE
            )
            current_section_end += SECTION_LENGTH_MS

        individual_strains[event.column] = _decay(
            individual_strains[event.column], event.column_gap, INDIVIDUAL_DECAY_BASE
        )
        individual_strains[event.column] += _individual_strain_value(event)

        if event.delta_time <= 1:
            highest_individual = max(highest_individual, individual_strains[event.column])
        else:
            highest_individual = individual_strains[event.column]

        overall_strain = _decay(overall_strain, event.delta_time, OVERALL_DECAY_BASE)
        overall_strain += _overall_strain_value(event)

        current_strain = highest_individual + overall_strain
        current_section_peak = max(current_strain, current_section_peak)

    section_peaks.append(current_section_peak)

    difficulty = 0.0
    weight = 1.0
    for peak in sorted((p for p in section_peaks if p > 0), reverse=True):
        difficulty += peak * weight
        weight *= SECTION_DECAY_WEIGHT

    return difficulty * STAR_RATING_SCALE


def max_combo(beatmap: ManiaBeatmap) -> int:
    total = 0
    for note in beatmap.notes:
        if note.is_hold:
            total += 1 + int((note.end_time - note.start_time) / 100)
        else:
            total += 1
    return total
