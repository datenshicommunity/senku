"""Minimal .osu beatmap parser for osu!taiko.

Extracts just what the difficulty engine needs: hit objects classified as
centre (don) / rim (kat) hits, or drumroll/swell (neither -- excluded
from most evaluators), plus timing/slider-velocity context needed to
compute each note's effective BPM.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from .._diffutils import apply_difficulty_mods

# TaikoModHardRock/TaikoModEasy scale SliderMultiplier (a `double` field in the
# real game, hence full-precision literals here, unlike the float32 CS/AR/OD/HP
# scaling in apply_difficulty_mods) in addition to the shared OD scaling --
# this feeds EffectiveBPM (see preprocessing.py), which the Reading skill is
# very sensitive to.
_HR_SLIDER_MULTIPLIER = 1.8666666666666665
_EZ_SLIDER_MULTIPLIER = 0.8


class TaikoObjectKind(Enum):
    CENTRE = auto()  # "don"
    RIM = auto()  # "kat"
    DRUMROLL = auto()
    SWELL = auto()


_SLIDER_FLAG = 1 << 1
_SPINNER_FLAG = 1 << 3
_WHISTLE_FLAG = 1 << 1
_CLAP_FLAG = 1 << 3


@dataclass(frozen=True)
class TaikoNote:
    start_time: float
    kind: TaikoObjectKind

    @property
    def is_hit(self) -> bool:
        return self.kind in (TaikoObjectKind.CENTRE, TaikoObjectKind.RIM)


@dataclass(frozen=True)
class TimingPoint:
    time: float
    beat_length: float  # negative value = inherited (SV multiplier), positive = uninherited (ms per beat)
    scroll_speed: float  # effect-point scroll speed multiplier (1.0 if not set by an inherited point)


@dataclass(frozen=True)
class TaikoBeatmap:
    overall_difficulty: float
    slider_multiplier: float
    notes: list[TaikoNote]
    timing_points: list[TimingPoint]  # sorted by time ascending

    def bpm_and_slider_velocity_at(self, time: float) -> tuple[float, float]:
        """Returns (BPM, effective slider-velocity multiplier) at a given time."""
        beat_length = 500.0  # 120 BPM default
        scroll_speed = 1.0
        last_uninherited_beat_length = 500.0

        for tp in self.timing_points:
            if tp.time > time:
                break
            if tp.beat_length > 0:
                last_uninherited_beat_length = tp.beat_length
                beat_length = tp.beat_length
                scroll_speed = 1.0
            else:
                beat_length = last_uninherited_beat_length
                scroll_speed = tp.scroll_speed

        bpm = 60000.0 / beat_length
        return bpm, scroll_speed


def parse_osu_file(text: str, mods: frozenset[str] = frozenset()) -> TaikoBeatmap:
    section = None
    overall_difficulty = 5.0
    slider_multiplier = 1.4
    raw_notes: list[tuple[float, int, int]] = []  # start_time, object_type, hit_sound
    timing_points: list[TimingPoint] = []

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
            if key == "OverallDifficulty":
                overall_difficulty = float(value.strip())
            elif key == "SliderMultiplier":
                slider_multiplier = float(value.strip())
            continue

        if section == "TimingPoints":
            fields = line.split(",")
            if len(fields) < 2:
                continue
            time = float(fields[0])
            beat_length = float(fields[1])
            scroll_speed = 1.0
            if beat_length < 0:
                scroll_speed = -100.0 / beat_length
            timing_points.append(TimingPoint(time=time, beat_length=beat_length, scroll_speed=scroll_speed))
            continue

        if section == "HitObjects":
            fields = line.split(",")
            if len(fields) < 4:
                continue

            start_time = float(fields[2])
            object_type = int(fields[3])
            hit_sound = int(fields[4]) if len(fields) > 4 else 0

            raw_notes.append((start_time, object_type, hit_sound))

    timing_points.sort(key=lambda tp: tp.time)

    if "HR" in mods:
        _, _, overall_difficulty, _ = apply_difficulty_mods(0.0, 0.0, overall_difficulty, 0.0, mods)
        slider_multiplier *= _HR_SLIDER_MULTIPLIER
    elif "EZ" in mods:
        _, _, overall_difficulty, _ = apply_difficulty_mods(0.0, 0.0, overall_difficulty, 0.0, mods)
        slider_multiplier *= _EZ_SLIDER_MULTIPLIER

    notes: list[TaikoNote] = []
    for start_time, object_type, hit_sound in raw_notes:
        if object_type & _SLIDER_FLAG:
            kind = TaikoObjectKind.DRUMROLL
        elif object_type & _SPINNER_FLAG:
            kind = TaikoObjectKind.SWELL
        elif hit_sound & (_WHISTLE_FLAG | _CLAP_FLAG):
            kind = TaikoObjectKind.RIM
        else:
            kind = TaikoObjectKind.CENTRE
        notes.append(TaikoNote(start_time=start_time, kind=kind))

    notes.sort(key=lambda n: n.start_time)

    return TaikoBeatmap(
        overall_difficulty=overall_difficulty,
        slider_multiplier=slider_multiplier,
        notes=notes,
        timing_points=timing_points,
    )
