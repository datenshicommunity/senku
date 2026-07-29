"""Minimal .osu beatmap parser for osu!catch, including full slider
(JuiceStream) -> fruit/droplet/tiny-droplet conversion and hyperdash
computation. Independent implementation of the documented legacy .osu
slider-conversion algorithm; not adapted from any specific codebase.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum, auto

from .._diffutils import apply_difficulty_mods
from .._legacy_beat_length import TimingPoint, beat_length_at, precision_adjusted_beat_length
from .._legacy_random import LegacyRandom
from .._slider_events import generate_slider_events
from .._slider_path import build_path, path_length, position_at

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
    # True for FRUIT-kind pieces nested inside a slider (head/tail/repeat) --
    # these get NO HR position jitter, unlike standalone top-level fruits.
    from_slider: bool = False

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
        # Mirrors Catcher.CalculateCatchWidth exactly -- no legacy rounding fudge
        # (catch calls the shared CS-scale helper with applyFudge=false, unlike
        # std). This is ALSO what hyperdash-target detection uses below; the
        # separate CS>5.5 shrink some difficulty-object construction applies is
        # NOT part of this method upstream, so it isn't applied here either --
        # see difficulty.py's movement-object half-catcher-width calculation.
        return CATCHER_BASE_SIZE * (_scale_from_circle_size(self.circle_size) * 2) * ALLOWED_CATCH_RANGE


def _scale_from_circle_size(cs: float) -> float:
    return (1.0 - 0.7 * ((cs - 5) / 5)) / 2


def parse_osu_file(text: str, mods: frozenset[str] = frozenset()) -> CatchBeatmap:
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
            raw_beat_length = float(fields[1])
            generate_ticks = not math.isnan(raw_beat_length)
            if raw_beat_length > 0:
                # See osu/beatmap.py's identical fix: TimingControlPoint.BeatLength
                # and DifficultyControlPoint.SliderVelocity are both clamped
                # BindableDoubles in the reference ([6,60000] and [0.1,10]
                # respectively), not used at face value.
                beat_length = min(max(raw_beat_length, 6.0), 60000.0)
                scroll_speed = 1.0
            else:
                beat_length = raw_beat_length
                scroll_speed = -100.0 / raw_beat_length if raw_beat_length < 0 else 1.0
                scroll_speed = min(max(scroll_speed, 0.1), 10.0)
            timing_points.append(TimingPoint(time=time, beat_length=beat_length, scroll_speed=scroll_speed, generate_ticks=generate_ticks))
            continue

        if section == "HitObjects":
            raw_objects.append(line.split(","))

    timing_points.sort(key=lambda tp: tp.time)

    # Catch only uses CS (catcher width) and AR (approach-rate-driven performance
    # bonuses downstream) out of the four BeatmapDifficulty stats -- OD/HP aren't
    # tracked at all, so 0.0 placeholders are discarded from the shared helper.
    circle_size, approach_rate, _, _ = apply_difficulty_mods(circle_size, approach_rate, 0.0, 0.0, mods)

    objects: list[CatchObject] = []

    # HR jitters standalone-fruit X positions via a seeded legacy RNG
    # (CatchBeatmapProcessor.ApplyPositionOffsets under HardRockOffsets=true).
    # The RNG walk is over TOP-LEVEL hit objects in file order, not the
    # flattened per-piece list: a JuiceStream updates last_position/last_start_time
    # ONCE (to its own last raw control point / start time) regardless of what
    # its nested pieces do, so this has to run inline during parsing rather than
    # as a separate post-process pass over the already-flattened objects.
    rng = LegacyRandom(1337) if "HR" in mods else None
    last_position: float | None = None
    last_start_time = 0.0

    for fields in raw_objects:
        if len(fields) < 4:
            continue
        x = float(fields[0])
        start_time = float(fields[2])
        object_type = int(fields[3])

        if object_type & _SPINNER_FLAG:
            # Bananas are excluded from difficulty/combo entirely, but still need
            # to exist here: under HR, the RNG stream consumes draws for every
            # banana in time order, so skipping generation would desync every
            # fruit's jitter that comes after a spinner.
            end_time = float(fields[5])
            for t in _generate_banana_times(start_time, end_time):
                if rng is not None:
                    banana_x = rng.next_double() * 512.0
                    rng.next()
                    rng.next()
                    rng.next()
                else:
                    banana_x = 0.0
                objects.append(CatchObject(start_time=t, x=banana_x, kind=CatchObjectKind.BANANA))
            continue

        if object_type & _SLIDER_FLAG:
            slider_objects, last_control_x = _convert_slider(
                fields, x, start_time, timing_points, slider_multiplier, slider_tick_rate, rng,
            )
            objects.extend(slider_objects)
            if rng is not None:
                last_position, last_start_time = last_control_x, start_time
        else:
            if rng is not None:
                xoffset, last_position, last_start_time = _apply_hard_rock_offset(
                    x, start_time, last_position, last_start_time, rng,
                )
                x += xoffset
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
                     slider_multiplier: float, slider_tick_rate: float,
                     rng: LegacyRandom | None) -> tuple[list[CatchObject], float]:
    head_y = float(fields[1])
    curve_type, extra_points = _parse_curve(fields[5])
    control_points = [(head_x, head_y)] + extra_points
    # .osu "slides" field is the total span/pass count directly (1 = no repeat,
    # 2 = one repeat) -- NOT a repeat count that needs +1.
    span_count = int(fields[6])
    # Matches the reference's Math.Max(0.0, Parsing.ParseDouble(array[7], 131072.0))
    # -- see osu/beatmap.py's identical fix.
    pixel_length = max(0.0, float(fields[7]))

    path = build_path(curve_type, control_points, pixel_length)
    # authoritative length per the .osu file, unless invalid -- see osu/beatmap.py.
    path_distance = pixel_length if pixel_length > 0 else path_length(path)

    raw_beat_length, scroll_speed, generate_ticks = beat_length_at(timing_points, start_time)
    adjusted_beat_length = precision_adjusted_beat_length(raw_beat_length, scroll_speed, ruleset="fruits")

    velocity = BASE_SCORING_DISTANCE * slider_multiplier / adjusted_beat_length
    # Deliberately uses the RAW (un-adjusted) beat length here, not the SV-adjusted
    # one used for velocity above -- matches stable's intentional floating-point
    # quirk (see JuiceStream.ApplyDefaultsToSelf upstream).
    scoring_distance = velocity * raw_beat_length
    # GenerateTicks=false (a green line with a literal NaN beatLength) means no
    # ticks/droplets at all for this slider -- see osu/beatmap.py's identical fix.
    tick_distance = (scoring_distance / slider_tick_rate) if generate_ticks else math.inf

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
                    tiny_x = head_x - (path[0][0] if path else 0) + px
                    if rng is not None:
                        offset = rng.next_range(-20.0, 20.0)
                        tiny_x += min(max(offset, -tiny_x), 512.0 - tiny_x)
                    result.append(CatchObject(start_time=t + last_event["time"], x=tiny_x, kind=CatchObjectKind.TINY_DROPLET))
                    t += time_between_tiny

        last_event = e

        px, _py = position_at(path, e["path_progress"])
        effective_x = px  # path already in absolute coordinate space (head_x baked into control_points[0])

        if e["type"] == "tick":
            if rng is not None:
                rng.next()  # consumed, discarded -- no offset applied to (large) droplets
            result.append(CatchObject(start_time=e["time"], x=effective_x, kind=CatchObjectKind.DROPLET))
        elif e["type"] in ("head", "tail", "repeat"):
            result.append(CatchObject(start_time=e["time"], x=effective_x, kind=CatchObjectKind.FRUIT, from_slider=True))

    return result, control_points[-1][0]


def _generate_banana_times(start_time: float, end_time: float) -> list[float]:
    # Mirrors BananaShower.createBananas: halve the spinner's duration until it's
    # <=100ms to get the inter-banana spacing, then step through [start, end].
    start = int(start_time)
    end = int(end_time)
    spacing = float(end_time - start_time)
    while spacing > 100.0:
        spacing /= 2.0

    times: list[float] = []
    if spacing > 0.0:
        t = float(start)
        while t <= end:
            times.append(t)
            t += spacing
    return times


def _apply_random_offset(position: float, max_offset: float, rng: LegacyRandom) -> float:
    positive = rng.next_bool()
    amount = min(20.0, rng.next_range(0.0, max(0.0, max_offset)))
    if positive:
        position = position + amount if position + amount <= 512.0 else position - amount
    else:
        position = position - amount if position - amount >= 0.0 else position + amount
    return position


def _apply_offset(position: float, amount: float) -> float:
    if amount > 0.0:
        if position + amount < 512.0:
            position += amount
    elif position + amount > 0.0:
        position += amount
    return position


def _apply_hard_rock_offset(original_x: float, start_time: float, last_position: float | None,
                             last_start_time: float, rng: LegacyRandom) -> tuple[float, float, float]:
    """Mirrors CatchBeatmapProcessor.applyHardRockOffset for one standalone
    (non-slider-derived) Fruit. Returns (x_offset, new_last_position, new_last_start_time)
    -- only called when HR is active; nomod/EZ never touch fruit positions."""
    if last_position is None or last_position == 0.0:
        return 0.0, original_x, start_time

    delta = original_x - last_position
    dt = int(start_time - last_start_time)
    if dt > 1000:
        return 0.0, original_x, start_time

    position = original_x
    if delta == 0.0:
        position = _apply_random_offset(position, dt / 4.0, rng)
        # NOTE: last_position/last_start_time intentionally NOT updated on this
        # branch -- matches the real implementation exactly (an easy bug to miss).
        return position - original_x, last_position, last_start_time

    if abs(delta) < float(dt // 3):
        position = _apply_offset(position, delta)
    return position - original_x, position, start_time


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
