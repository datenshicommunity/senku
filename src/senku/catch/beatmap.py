"""Minimal .osu beatmap parser for osu!catch, including full slider
(JuiceStream) -> fruit/droplet/tiny-droplet conversion and hyperdash
computation. Independent implementation of the documented legacy .osu
slider-conversion algorithm; not adapted from any specific codebase.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum, auto

from .._legacy_beat_length import TimingPoint, beat_length_at, precision_adjusted_beat_length
from .._slider_events import generate_slider_events
from .._slider_path import build_path, position_at

_SLIDER_FLAG = 1 << 1
_SPINNER_FLAG = 1 << 3

BASE_SCORING_DISTANCE = 100.0
CATCHER_BASE_SIZE = 106.75
ALLOWED_CATCH_RANGE = 0.8
BASE_DASH_SPEED = 1.0


class CatchObjectKind(Enum):
    FRUIT = auto()
    DROPLET = auto()
    TINY_DROPLET = auto()
    BANANA = auto()  # excluded from difficulty entirely


@dataclass
class CatchObject:
    start_time: float
    x: float  # OriginalX + XOffset (nomod: == OriginalX)
    kind: CatchObjectKind
    hyper_dash_target: object = None
    distance_to_hyper_dash: float = 0.0

    @property
    def hyper_dash(self) -> bool:
        return self.hyper_dash_target is not None


@dataclass
class CatchBeatmap:
    circle_size: float
    approach_rate: float
    slider_multiplier: float
    slider_tick_rate: float
    objects: list[CatchObject] = field(default_factory=list)  # sorted, palpable, non-banana/tiny excluded already handled by caller as needed

    def catch_width(self) -> float:
        scale = _scale_from_circle_size(self.circle_size) * 2
        return CATCHER_BASE_SIZE * scale * ALLOWED_CATCH_RANGE


def _scale_from_circle_size(cs: float) -> float:
    return (1.0 - 0.7 * ((cs - 5) / 5)) / 2


def parse_osu_file(text: str) -> CatchBeatmap:
    section = None
    circle_size = 4.0
    approach_rate = 5.0
    slider_multiplier = 1.4
    slider_tick_rate = 1.0
    timing_points: list[TimingPoint] = []
    raw_objects: list[list[str]] = []

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
            elif key == "ApproachRate":
                approach_rate = float(value.strip())
            elif key == "SliderMultiplier":
                slider_multiplier = float(value.strip())
            elif key == "SliderTickRate":
                slider_tick_rate = float(value.strip())
            continue

        if section == "TimingPoints":
            fields = line.split(",")
            if len(fields) < 2:
                continue
            time = float(fields[0])
            beat_length = float(fields[1])
            scroll_speed = -100.0 / beat_length if beat_length < 0 else 1.0
            timing_points.append(TimingPoint(time=time, beat_length=beat_length, scroll_speed=scroll_speed))
            continue

        if section == "HitObjects":
            raw_objects.append(line.split(","))

    timing_points.sort(key=lambda tp: tp.time)

    objects: list[CatchObject] = []

    for fields in raw_objects:
        if len(fields) < 4:
            continue
        x = float(fields[0])
        start_time = float(fields[2])
        object_type = int(fields[3])

        if object_type & _SPINNER_FLAG:
            continue  # banana showers: excluded from difficulty entirely, skip generating bananas

        if object_type & _SLIDER_FLAG:
            objects.extend(_convert_slider(fields, x, start_time, timing_points, slider_multiplier, slider_tick_rate))
        else:
            objects.append(CatchObject(start_time=start_time, x=x, kind=CatchObjectKind.FRUIT))

    objects.sort(key=lambda o: o.start_time)

    _compute_hyperdash(objects, circle_size)

    return CatchBeatmap(
        circle_size=circle_size,
        approach_rate=approach_rate,
        slider_multiplier=slider_multiplier,
        slider_tick_rate=slider_tick_rate,
        objects=objects,
    )


def _parse_curve(field5: str) -> tuple[str, list[tuple[float, float]]]:
    parts = field5.split("|")
    curve_type = parts[0]
    points = []
    for p in parts[1:]:
        px, py = p.split(":")
        points.append((float(px), float(py)))
    return curve_type, points


def _convert_slider(fields: list[str], head_x: float, start_time: float, timing_points: list[TimingPoint],
                     slider_multiplier: float, slider_tick_rate: float) -> list[CatchObject]:
    head_y = float(fields[1])
    curve_type, extra_points = _parse_curve(fields[5])
    control_points = [(head_x, head_y)] + extra_points
    # .osu "slides" field is the total span/pass count directly (1 = no repeat,
    # 2 = one repeat) -- NOT a repeat count that needs +1.
    span_count = int(fields[6])
    pixel_length = float(fields[7])

    path = build_path(curve_type, control_points, pixel_length)
    path_distance = pixel_length  # authoritative length per the .osu file

    raw_beat_length, scroll_speed = beat_length_at(timing_points, start_time)
    adjusted_beat_length = precision_adjusted_beat_length(raw_beat_length, scroll_speed, ruleset="fruits")

    velocity = BASE_SCORING_DISTANCE * slider_multiplier / adjusted_beat_length
    # Deliberately uses the RAW (un-adjusted) beat length here, not the SV-adjusted
    # one used for velocity above -- matches stable's intentional floating-point
    # quirk (see JuiceStream.ApplyDefaultsToSelf upstream).
    scoring_distance = velocity * raw_beat_length
    tick_distance = scoring_distance / slider_tick_rate

    span_duration = path_distance / velocity if velocity > 0 else 0.0

    events = generate_slider_events(start_time, span_duration, velocity, tick_distance, path_distance, span_count)

    result: list[CatchObject] = []
    last_event = None

    for e in events:
        if last_event is not None:
            since_last_tick = int(e["time"]) - int(last_event["time"])
            if since_last_tick > 80:
                time_between_tiny = since_last_tick
                while time_between_tiny > 100:
                    time_between_tiny /= 2
                t = time_between_tiny
                while t < since_last_tick:
                    progress = last_event["path_progress"] + (t / since_last_tick) * (e["path_progress"] - last_event["path_progress"])
                    px, _py = position_at(path, progress)
                    result.append(CatchObject(start_time=t + last_event["time"], x=head_x - (path[0][0] if path else 0) + px, kind=CatchObjectKind.TINY_DROPLET))
                    t += time_between_tiny

        last_event = e

        px, _py = position_at(path, e["path_progress"])
        effective_x = px  # path already in absolute coordinate space (head_x baked into control_points[0])

        if e["type"] == "tick":
            result.append(CatchObject(start_time=e["time"], x=effective_x, kind=CatchObjectKind.DROPLET))
        elif e["type"] in ("head", "tail", "repeat"):
            result.append(CatchObject(start_time=e["time"], x=effective_x, kind=CatchObjectKind.FRUIT))

    return result


def _compute_hyperdash(objects: list[CatchObject], circle_size: float) -> None:
    palpable = [o for o in objects if o.kind in (CatchObjectKind.FRUIT, CatchObjectKind.DROPLET)]

    half_catcher_width = (CATCHER_BASE_SIZE * (_scale_from_circle_size(circle_size) * 2) * ALLOWED_CATCH_RANGE) / 2
    half_catcher_width /= ALLOWED_CATCH_RANGE

    last_direction = 0
    last_excess = half_catcher_width

    for i in range(len(palpable) - 1):
        current = palpable[i]
        nxt = palpable[i + 1]

        current.hyper_dash_target = None
        current.distance_to_hyper_dash = 0.0

        this_direction = 1 if nxt.x > current.x else -1
        time_to_next = int(nxt.start_time) - int(current.start_time) - 1000.0 / 60.0 / 4
        distance_to_next = abs(nxt.x - current.x) - (last_excess if last_direction == this_direction else half_catcher_width)
        distance_to_hyper = time_to_next * BASE_DASH_SPEED - distance_to_next

        if distance_to_hyper < 0:
            current.hyper_dash_target = nxt
            last_excess = half_catcher_width
        else:
            current.distance_to_hyper_dash = distance_to_hyper
            last_excess = min(max(distance_to_hyper, 0.0), half_catcher_width)

        last_direction = this_direction
