"""Minimal .osu beatmap parser for osu!standard, including full slider
(Slider) -> head/tick/repeat/tail conversion and the legacy stacking
algorithm. Independent implementation of the documented legacy .osu
slider-conversion and stacking algorithms; not adapted from any specific
codebase.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum, auto

from .._diffutils import apply_difficulty_mods, unchecked_int32
from .._legacy_beat_length import TimingPoint, beat_length_at, precision_adjusted_beat_length
from .._slider_events import generate_slider_events
from .._slider_path import build_path, path_length, position_at

_SLIDER_FLAG = 1 << 1
_NEW_COMBO_FLAG = 1 << 2
_SPINNER_FLAG = 1 << 3

BASE_SCORING_DISTANCE = 100.0
OBJECT_RADIUS = 64.0
STACK_DISTANCE = 3.0

PREEMPT_MAX = 1800.0
PREEMPT_MID = 1200.0
PREEMPT_MIN = 450.0

PLAYFIELD_HEIGHT = 384.0

# Matches the reference decoder's Parsing.cs limits: values past these throw
# OverflowException/FormatException during line parsing, which the outer
# per-line try/catch turns into a silent whole-object drop (see parse_osu_file).
_MAX_COORDINATE_VALUE = 131072.0
_MAX_PARSE_VALUE = 2147483647.0
_MAX_SLIDER_REPEATS = 9000


class OsuObjectKind(Enum):
    CIRCLE = auto()
    SLIDER = auto()
    SPINNER = auto()


class NestedKind(Enum):
    HEAD = auto()
    TICK = auto()
    REPEAT = auto()
    TAIL = auto()


@dataclass
class NestedObject:
    kind: NestedKind
    start_time: float
    position: tuple[float, float]  # unstacked
    path_progress: float = 0.0


@dataclass
class OsuObject:
    kind: OsuObjectKind
    start_time: float
    position: tuple[float, float]  # unstacked
    end_position: tuple[float, float]  # unstacked
    end_time: float
    stack_height: int = 0
    scale: float = 0.0
    # slider-specific
    path: list | None = None
    path_distance: float = 0.0
    span_count: int = 1
    repeat_count: int = 0
    velocity: float = 0.0
    duration: float = 0.0
    nested: list = field(default_factory=list)

    @property
    def radius(self) -> float:
        return OBJECT_RADIUS * self.scale

    def stack_offset(self) -> tuple[float, float]:
        d = self.stack_height * self.scale * -6.4
        return (d, d)

    @property
    def stacked_position(self) -> tuple[float, float]:
        ox, oy = self.stack_offset()
        return (self.position[0] + ox, self.position[1] + oy)

    @property
    def stacked_end_position(self) -> tuple[float, float]:
        ox, oy = self.stack_offset()
        return (self.end_position[0] + ox, self.end_position[1] + oy)

    def nested_stacked_positions(self) -> list[tuple[float, float]]:
        ox, oy = self.stack_offset()
        return [(n.position[0] + ox, n.position[1] + oy) for n in self.nested]


@dataclass
class OsuBeatmap:
    circle_size: float
    approach_rate: float
    overall_difficulty: float
    drain_rate: float
    slider_multiplier: float
    slider_tick_rate: float
    format_version: int
    stack_leniency: float
    objects: list[OsuObject] = field(default_factory=list)
    breaks: list[tuple[float, float]] = field(default_factory=list)

    @property
    def scale(self) -> float:
        return _scale_from_circle_size(self.circle_size)

    @property
    def radius(self) -> float:
        return OBJECT_RADIUS * self.scale

    @property
    def preempt(self) -> float:
        return _difficulty_range(self.approach_rate, PREEMPT_MAX, PREEMPT_MID, PREEMPT_MIN)

    @property
    def hit_window_great(self) -> float:
        return math.floor(_difficulty_range(self.overall_difficulty, 80.0, 50.0, 20.0)) - 0.5

    def max_combo(self) -> int:
        total = 0
        for o in self.objects:
            if o.kind == OsuObjectKind.SLIDER:
                total += len(o.nested)
            else:
                total += 1
        return total


def _difficulty_range(difficulty: float, min_value: float, mid_value: float, max_value: float) -> float:
    if difficulty > 5:
        return mid_value + (max_value - mid_value) * (difficulty - 5) / 5
    if difficulty < 5:
        return mid_value - (mid_value - min_value) * (5 - difficulty) / 5
    return mid_value


def _scale_from_circle_size(cs: float, apply_fudge: bool = True) -> float:
    # Mirrors LegacyRulesetExtensions.CalculateScaleFromCircleSize.
    broken_gamefield_rounding_allowance = 1.00041
    scale = (1.0 - 0.7 * ((cs - 5) / 5)) / 2
    return scale * (broken_gamefield_rounding_allowance if apply_fudge else 1.0)


def _parse_curve(field5: str) -> tuple[str, list[tuple[float, float]]]:
    parts = field5.split("|")
    curve_type = parts[0]
    points = []
    for p in parts[1:]:
        # Troll/joke maps sometimes stuff extra non-coordinate tokens into this
        # field (e.g. spelling something out one letter per "point"); the
        # reference client doesn't reject the whole slider over it, it just
        # doesn't treat the bad token as a control point.
        if ":" not in p:
            continue
        px, py = p.split(":")
        points.append((float(px), float(py)))
    return curve_type, points


def parse_osu_file(text: str, mods: frozenset[str] = frozenset(), difficulty_adjust: dict[str, float] | None = None) -> OsuBeatmap:
    lines = text.splitlines()
    format_version = 14
    if lines and lines[0].strip().lower().startswith("osu file format v"):
        try:
            format_version = int(lines[0].strip().rsplit("v", 1)[-1])
        except ValueError:
            format_version = 14

    section = None
    circle_size = 5.0
    approach_rate = 5.0
    overall_difficulty = 5.0
    drain_rate = 5.0
    slider_multiplier = 1.4
    slider_tick_rate = 1.0
    stack_leniency = 0.7
    ar_specified = False
    timing_points: list[TimingPoint] = []
    raw_objects: list[list[str]] = []
    breaks: list[tuple[float, float]] = []

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("//"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue

        if section == "General":
            key, _, value = line.partition(":")
            if key.strip() == "StackLeniency":
                stack_leniency = float(value.strip())
            continue

        if section == "Events":
            fields = line.split(",")
            if len(fields) >= 3 and fields[0].strip() in ("2", "Break"):
                try:
                    breaks.append((float(fields[1]), float(fields[2])))
                except ValueError:
                    pass
            continue

        if section == "Difficulty":
            key, _, value = line.partition(":")
            key = key.strip()
            if key == "CircleSize":
                circle_size = float(value.strip())
            elif key == "ApproachRate":
                approach_rate = float(value.strip())
                ar_specified = True
            elif key == "OverallDifficulty":
                overall_difficulty = float(value.strip())
            elif key == "HPDrainRate":
                drain_rate = float(value.strip())
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
            raw_beat_length = float(fields[1])
            generate_ticks = not math.isnan(raw_beat_length)
            if raw_beat_length > 0:
                # TimingControlPoint.BeatLength is a BindableDouble clamped to
                # [6, 60000] (MinValue/MaxValue) in the reference -- a troll
                # timing point can declare an absurd BPM (e.g. beat_length=
                # 3.341ms -> ~18000 BPM) that silently clamps rather than
                # being used at face value.
                beat_length = min(max(raw_beat_length, 6.0), 60000.0)
                scroll_speed = 1.0
            else:
                beat_length = raw_beat_length
                scroll_speed = -100.0 / raw_beat_length if raw_beat_length < 0 else 1.0
                # DifficultyControlPoint.SliderVelocity is likewise clamped to [0.1, 10].
                scroll_speed = min(max(scroll_speed, 0.1), 10.0)
            timing_points.append(TimingPoint(time=time, beat_length=beat_length, scroll_speed=scroll_speed, generate_ticks=generate_ticks))
            continue

        if section == "HitObjects":
            raw_objects.append(line.split(","))

    if not ar_specified:
        approach_rate = overall_difficulty

    circle_size, approach_rate, overall_difficulty, drain_rate = apply_difficulty_mods(
        circle_size, approach_rate, overall_difficulty, drain_rate, mods,
    )

    if difficulty_adjust:
        # ModDifficultyAdjust ("DA"): direct override (not a multiplier), each setting independent/optional.
        # Incompatible with EZ/HR in-game, so ordering relative to _apply_difficulty_mods above doesn't matter in practice.
        if "cs" in difficulty_adjust:
            circle_size = difficulty_adjust["cs"]
        if "ar" in difficulty_adjust:
            approach_rate = difficulty_adjust["ar"]
        if "od" in difficulty_adjust:
            overall_difficulty = difficulty_adjust["od"]
        if "hp" in difficulty_adjust:
            drain_rate = difficulty_adjust["hp"]

    timing_points.sort(key=lambda tp: tp.time)

    scale = _scale_from_circle_size(circle_size, apply_fudge=True)

    objects: list[OsuObject] = []

    reflect_y = "HR" in mods

    for fields in raw_objects:
        if len(fields) < 4:
            continue
        x = float(fields[0])
        y = float(fields[1])
        start_time = float(fields[2])
        object_type = int(fields[3])

        # Reference client behaviour (LegacyDecoder wraps every .osu line in a
        # try/catch; ConvertHitObjectParser.Parse throws OverflowException via
        # Parsing.ParseDouble/ParseInt for values past these limits) -- a
        # troll beatmap can set e.g. a slider's declared pixel length to
        # hundreds of billions, which the reference silently drops the whole
        # object for rather than computing an astronomical travel distance.
        # Not a clamp: the object must be fully absent downstream.
        if (abs(x) > _MAX_COORDINATE_VALUE or abs(y) > _MAX_COORDINATE_VALUE
                or abs(start_time) > _MAX_PARSE_VALUE):
            continue
        if object_type & _SLIDER_FLAG:
            if len(fields) < 8:
                continue
            slides_ok = True
            try:
                if abs(int(fields[6])) > _MAX_SLIDER_REPEATS:
                    slides_ok = False
                if abs(float(fields[7])) > _MAX_COORDINATE_VALUE:
                    slides_ok = False
            except ValueError:
                slides_ok = False
            if not slides_ok:
                continue

        if reflect_y:
            y = PLAYFIELD_HEIGHT - y

        if object_type & _SPINNER_FLAG:
            end_time = float(fields[5])
            objects.append(OsuObject(
                kind=OsuObjectKind.SPINNER, start_time=start_time, position=(x, y), end_position=(x, y),
                end_time=end_time, scale=scale,
            ))
        elif object_type & _SLIDER_FLAG:
            objects.append(_convert_slider(fields, x, y, start_time, timing_points, slider_multiplier, slider_tick_rate, scale, reflect_y))
        else:
            objects.append(OsuObject(
                kind=OsuObjectKind.CIRCLE, start_time=start_time, position=(x, y), end_position=(x, y),
                end_time=start_time, scale=scale,
            ))

    objects.sort(key=lambda o: o.start_time)

    beatmap = OsuBeatmap(
        circle_size=circle_size, approach_rate=approach_rate, overall_difficulty=overall_difficulty,
        drain_rate=drain_rate, slider_multiplier=slider_multiplier, slider_tick_rate=slider_tick_rate,
        format_version=format_version, stack_leniency=stack_leniency, objects=objects, breaks=breaks,
    )

    _apply_stacking(beatmap)

    return beatmap


def _convert_slider(fields: list[str], head_x: float, head_y: float, start_time: float,
                     timing_points: list[TimingPoint], slider_multiplier: float, slider_tick_rate: float,
                     scale: float, reflect_y: bool = False) -> OsuObject:
    curve_type, extra_points = _parse_curve(fields[5])
    if reflect_y:
        extra_points = [(px, PLAYFIELD_HEIGHT - py) for px, py in extra_points]
    control_points = [(head_x, head_y)] + extra_points
    span_count = int(fields[6])
    # Matches the reference's Math.Max(0.0, Parsing.ParseDouble(array[7], 131072.0))
    # (ConvertHitObjectParser.cs) -- a troll map can declare a negative
    # pixel_length (e.g. "-1"), which senku previously used at face value,
    # sending path_distance/duration negative and corrupting the FOLLOWING
    # object's travel_distance computation.
    pixel_length = max(0.0, float(fields[7]))

    path = build_path(curve_type, control_points, pixel_length)
    # When the declared length is invalid (<=0), the reference falls back to
    # the path's own geometric length (SliderPath.CalculatedDistance) rather
    # than treating the slider as zero-length.
    path_distance = pixel_length if pixel_length > 0 else path_length(path)

    raw_beat_length, scroll_speed, generate_ticks = beat_length_at(timing_points, start_time)
    adjusted_beat_length = precision_adjusted_beat_length(raw_beat_length, scroll_speed, ruleset="osu")

    velocity = BASE_SCORING_DISTANCE * slider_multiplier / adjusted_beat_length
    # Deliberately uses the RAW (un-adjusted) beat length here, matching stable's
    # intentional floating-point quirk (see Slider.ApplyDefaultsToSelf upstream).
    scoring_distance = velocity * raw_beat_length
    # GenerateTicks=false (a green line with a literal NaN beatLength) means
    # no ticks at all for this slider -- TickDistance becomes Infinity, which
    # the length-clamp in generate_slider_events() already reduces to "no
    # ticks fit" without any further special-casing there.
    tick_distance = (scoring_distance / slider_tick_rate) if generate_ticks else math.inf

    span_duration = path_distance / velocity if velocity > 0 else 0.0
    duration = span_count * path_distance / velocity if velocity > 0 else 0.0

    events = generate_slider_events(start_time, span_duration, velocity, tick_distance, path_distance, span_count)

    nested: list[NestedObject] = []
    end_position = (head_x, head_y)

    for e in events:
        px, py = position_at(path, e["path_progress"])
        if e["type"] == "tick":
            nested.append(NestedObject(kind=NestedKind.TICK, start_time=e["time"], position=(px, py), path_progress=e["path_progress"]))
        elif e["type"] == "head":
            nested.append(NestedObject(kind=NestedKind.HEAD, start_time=e["time"], position=(px, py), path_progress=e["path_progress"]))
        elif e["type"] == "repeat":
            nested.append(NestedObject(kind=NestedKind.REPEAT, start_time=e["time"], position=(px, py), path_progress=e["path_progress"]))
        elif e["type"] == "tail":
            nested.append(NestedObject(kind=NestedKind.TAIL, start_time=e["time"], position=(px, py), path_progress=e["path_progress"]))
            end_position = (px, py)

    return OsuObject(
        kind=OsuObjectKind.SLIDER, start_time=start_time, position=(head_x, head_y), end_position=end_position,
        end_time=start_time + duration, scale=scale, path=path, path_distance=path_distance,
        span_count=span_count, repeat_count=span_count - 1, velocity=velocity, duration=duration, nested=nested,
    )


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _stack_threshold(beatmap: OsuBeatmap, obj: OsuObject) -> float:
    preempt = _difficulty_range(beatmap.approach_rate, PREEMPT_MAX, PREEMPT_MID, PREEMPT_MIN)
    return int(preempt) * beatmap.stack_leniency


def _apply_stacking(beatmap: OsuBeatmap) -> None:
    hit_objects = beatmap.objects
    if not hit_objects:
        return

    for h in hit_objects:
        h.stack_height = 0

    if beatmap.format_version >= 6:
        _apply_stacking_new(beatmap, hit_objects, 0, len(hit_objects) - 1)
    else:
        _apply_stacking_old(beatmap, hit_objects)


def _apply_stacking_new(beatmap: OsuBeatmap, hit_objects: list[OsuObject], start_index: int, end_index: int) -> None:
    extended_end_index = end_index

    if end_index < len(hit_objects) - 1:
        i = end_index
        while i >= start_index:
            stack_base_index = i

            n = stack_base_index + 1
            while n < len(hit_objects):
                stack_base_object = hit_objects[stack_base_index]
                if stack_base_object.kind == OsuObjectKind.SPINNER:
                    break

                object_n = hit_objects[n]
                if object_n.kind == OsuObjectKind.SPINNER:
                    n += 1
                    continue

                end_time = stack_base_object.end_time
                stack_threshold = _stack_threshold(beatmap, object_n)

                if object_n.start_time - end_time > stack_threshold:
                    break

                if (_distance(stack_base_object.position, object_n.position) < STACK_DISTANCE
                        or (stack_base_object.kind == OsuObjectKind.SLIDER
                            and _distance(stack_base_object.end_position, object_n.position) < STACK_DISTANCE)):
                    stack_base_index = n
                    object_n.stack_height = 0

                n += 1

            if stack_base_index > extended_end_index:
                extended_end_index = stack_base_index
                if extended_end_index == len(hit_objects) - 1:
                    break

            i -= 1

    extended_start_index = start_index

    i = extended_end_index
    while i > start_index:
        n = i

        object_i = hit_objects[i]
        if object_i.stack_height != 0 or object_i.kind == OsuObjectKind.SPINNER:
            i -= 1
            continue

        stack_threshold = _stack_threshold(beatmap, object_i)

        if object_i.kind == OsuObjectKind.CIRCLE:
            n -= 1
            while n >= 0:
                object_n = hit_objects[n]
                if object_n.kind == OsuObjectKind.SPINNER:
                    n -= 1
                    continue

                end_time = object_n.end_time

                if unchecked_int32(object_i.start_time) - unchecked_int32(end_time) > stack_threshold:
                    break

                if n < extended_start_index:
                    object_n.stack_height = 0
                    extended_start_index = n

                if object_n.kind == OsuObjectKind.SLIDER and _distance(object_n.end_position, object_i.position) < STACK_DISTANCE:
                    offset = object_i.stack_height - object_n.stack_height + 1
                    for j in range(n + 1, i + 1):
                        object_j = hit_objects[j]
                        if _distance(object_n.end_position, object_j.position) < STACK_DISTANCE:
                            object_j.stack_height -= offset
                    break

                if _distance(object_n.position, object_i.position) < STACK_DISTANCE:
                    object_n.stack_height = object_i.stack_height + 1
                    object_i = object_n

                n -= 1
        elif object_i.kind == OsuObjectKind.SLIDER:
            n -= 1
            while n >= start_index:
                object_n = hit_objects[n]
                if object_n.kind == OsuObjectKind.SPINNER:
                    n -= 1
                    continue

                if object_i.start_time - object_n.start_time > stack_threshold:
                    break

                if _distance(object_n.end_position, object_i.position) < STACK_DISTANCE:
                    object_n.stack_height = object_i.stack_height + 1
                    object_i = object_n

                n -= 1

        i -= 1


def _apply_stacking_old(beatmap: OsuBeatmap, hit_objects: list[OsuObject]) -> None:
    for i in range(len(hit_objects)):
        curr = hit_objects[i]

        if curr.stack_height != 0 and curr.kind != OsuObjectKind.SLIDER:
            continue

        start_time = curr.end_time
        slider_stack = 0

        for j in range(i + 1, len(hit_objects)):
            stack_threshold = _stack_threshold(beatmap, curr)

            if hit_objects[j].start_time - stack_threshold > start_time:
                break

            position2 = curr.end_position if curr.kind == OsuObjectKind.SLIDER else curr.position

            if _distance(hit_objects[j].position, curr.position) < STACK_DISTANCE:
                curr.stack_height += 1
                start_time = hit_objects[j].start_time
            elif _distance(hit_objects[j].position, position2) < STACK_DISTANCE:
                slider_stack += 1
                hit_objects[j].stack_height -= slider_stack
                start_time = hit_objects[j].start_time
