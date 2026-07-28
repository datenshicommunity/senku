"""osu!std per-object difficulty preprocessing: jump/travel distances, lazy
slider-cursor tracking, and angles between consecutive objects. Independent
implementation; not adapted from any specific codebase.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .beatmap import PREEMPT_MIN, NestedKind, OsuBeatmap, OsuObject, OsuObjectKind

NORMALISED_RADIUS = 50.0
NORMALISED_DIAMETER = NORMALISED_RADIUS * 2
MIN_DELTA_TIME = 25.0
MAXIMUM_SLIDER_RADIUS = NORMALISED_RADIUS * 2.4
ASSUMED_SLIDER_RADIUS = NORMALISED_RADIUS * 1.8

TAIL_LENIENCY = -36.0


@dataclass
class OsuDifficultyHitObject:
    obj: OsuObject
    last_obj: OsuObject
    index: int
    clock_rate: float
    start_time: float
    delta_time: float
    adjusted_delta_time: float
    last_object_end_delta_time: float
    preempt: float
    overall_difficulty: float
    hit_window_great: float
    raw_preempt: float
    time_fade_in: float

    jump_distance: float = 0.0
    lazy_jump_distance: float = 0.0
    minimum_jump_distance: float = 0.0
    minimum_jump_time: float = 0.0
    travel_distance: float = 0.0
    travel_time: float = 0.0
    lazy_end_position: tuple[float, float] | None = None
    lazy_travel_distance: float = 0.0
    lazy_travel_time: float = 0.0
    angle: float | None = None
    normalised_vector_angle: float | None = None

    @property
    def small_circle_bonus(self) -> float:
        return max(1.0, 1.0 + (30 - self.obj.radius) / 70)

    def calculate_double_tap_feasibility(self, next_obj: "OsuDifficultyHitObject | None") -> float:
        if next_obj is None:
            return 0.0

        curr_delta_time = max(1.0, self.delta_time)
        next_delta_time = max(1.0, next_obj.delta_time)

        delta_difference = abs(next_delta_time - curr_delta_time)

        speed_ratio = curr_delta_time / max(curr_delta_time, delta_difference)

        from .._diffutils import reverse_lerp
        window_ratio = pow(min(1.0, curr_delta_time / self.hit_window_great), 5)

        distance_factor = pow(reverse_lerp(self.lazy_jump_distance, NORMALISED_DIAMETER, NORMALISED_RADIUS), 2)

        return 1.0 - pow(speed_ratio, distance_factor * (1 - window_ratio))

    def opacity_at(self, time: float, hidden: bool) -> float:
        if time > self.obj.start_time:
            return 0.0

        fade_in_start_time = self.obj.start_time - self.raw_preempt
        # Deliberately recomputed with the standard formula here, independent of self.time_fade_in
        # (which reflects Hidden's TimeFadeIn override, used only for fade_out_start_time below).
        fade_in_duration = 400 * min(1.0, self.raw_preempt / PREEMPT_MIN)

        if hidden:
            fade_out_duration_multiplier = 0.3
            fade_out_start_time = self.obj.start_time - self.raw_preempt + self.time_fade_in
            fade_out_duration = self.raw_preempt * fade_out_duration_multiplier
            return min(
                min(max((time - fade_in_start_time) / fade_in_duration, 0.0), 1.0),
                1.0 - min(max((time - fade_out_start_time) / fade_out_duration, 0.0), 1.0),
            )

        return min(max((time - fade_in_start_time) / fade_in_duration, 0.0), 1.0)


def previous(dobjs: list["OsuDifficultyHitObject"], index: int, n: int = 0) -> "OsuDifficultyHitObject | None":
    idx = index - 1 - n
    return dobjs[idx] if idx >= 0 else None


def next_obj(dobjs: list["OsuDifficultyHitObject"], index: int, n: int = 0) -> "OsuDifficultyHitObject | None":
    idx = index + 1 + n
    return dobjs[idx] if idx < len(dobjs) else None


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _sub(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
    return (a[0] - b[0], a[1] - b[1])


def build_difficulty_hit_objects(beatmap: OsuBeatmap, clock_rate: float = 1.0, hidden: bool = False) -> list[OsuDifficultyHitObject]:
    objs = beatmap.objects
    result: list[OsuDifficultyHitObject] = []

    hit_window_great = 2 * beatmap.hit_window_great / clock_rate
    overall_difficulty = (79.5 - hit_window_great / 2) / 6
    raw_preempt = beatmap.preempt
    default_time_fade_in = 400 * min(1.0, raw_preempt / PREEMPT_MIN)
    # Hidden overrides TimeFadeIn for non-slider objects to TimePreempt * 0.4;
    # sliders keep the default fade-in to match stable (OsuModHidden.ApplyToHitObject).
    hidden_time_fade_in = raw_preempt * 0.4

    for i in range(1, len(objs)):
        base_object = objs[i]
        last_object = objs[i - 1]

        delta_time = (base_object.start_time - last_object.start_time) / clock_rate
        adjusted_delta_time = max(delta_time, MIN_DELTA_TIME)

        last_difficulty_object = result[-1] if result else None
        if last_difficulty_object is not None:
            last_object_end_delta_time = max((base_object.start_time - last_object.end_time) / clock_rate, MIN_DELTA_TIME)
        else:
            last_object_end_delta_time = adjusted_delta_time

        time_fade_in = hidden_time_fade_in if hidden else default_time_fade_in

        do = OsuDifficultyHitObject(
            obj=base_object, last_obj=last_object, index=len(result), clock_rate=clock_rate,
            start_time=base_object.start_time / clock_rate, delta_time=delta_time,
            adjusted_delta_time=adjusted_delta_time, last_object_end_delta_time=last_object_end_delta_time,
            preempt=_preempt_for(beatmap, clock_rate), overall_difficulty=overall_difficulty,
            hit_window_great=hit_window_great, raw_preempt=raw_preempt, time_fade_in=time_fade_in,
        )

        _compute_slider_cursor_position(do)
        _set_distances(do, result, clock_rate)

        result.append(do)

    return result


def _preempt_for(beatmap: OsuBeatmap, clock_rate: float) -> float:
    return beatmap.preempt / clock_rate


def _get_end_cursor_position(d: OsuDifficultyHitObject) -> tuple[float, float]:
    return d.lazy_end_position if d.lazy_end_position is not None else d.obj.stacked_position


def _compute_slider_cursor_position(do: OsuDifficultyHitObject) -> None:
    obj = do.obj
    if obj.kind != OsuObjectKind.SLIDER:
        return
    if do.lazy_end_position is not None:
        return

    span_duration = (obj.duration / obj.span_count) if obj.span_count > 0 else 0.0

    tracking_end_time = max(
        obj.start_time + obj.duration + TAIL_LENIENCY,
        obj.start_time + obj.duration / 2,
    )

    nested_objects = obj.nested

    last_real_tick = None
    for n in obj.nested:
        if n.kind == NestedKind.TICK:
            last_real_tick = n

    if last_real_tick is not None and last_real_tick.start_time > tracking_end_time:
        tracking_end_time = last_real_tick.start_time
        reordered = [n for n in nested_objects if n is not last_real_tick]
        reordered.append(last_real_tick)
        nested_objects = reordered

    do.lazy_travel_time = tracking_end_time - obj.start_time

    end_time_min = do.lazy_travel_time / span_duration if span_duration > 0 else 0.0
    if end_time_min % 2 >= 1:
        end_time_min = 1 - end_time_min % 1
    else:
        end_time_min = end_time_min % 1

    from .._slider_path import position_at
    px, py = position_at(obj.path, end_time_min)
    sx, sy = obj.stacked_position
    ox, oy = obj.position
    do.lazy_end_position = (sx + (px - ox), sy + (py - oy))

    curr_cursor_position = obj.stacked_position
    scaling_factor = NORMALISED_RADIUS / obj.radius

    for i in range(1, len(nested_objects)):
        curr_movement_obj = nested_objects[i]

        ox2, oy2 = obj.stack_offset()
        curr_pos = (curr_movement_obj.position[0] + ox2, curr_movement_obj.position[1] + oy2)

        curr_movement = _sub(curr_pos, curr_cursor_position)
        curr_movement_length = scaling_factor * math.hypot(*curr_movement)

        required_movement = ASSUMED_SLIDER_RADIUS

        if i == len(nested_objects) - 1:
            lazy_movement = _sub(do.lazy_end_position, curr_cursor_position)
            if math.hypot(*lazy_movement) < math.hypot(*curr_movement):
                curr_movement = lazy_movement
            curr_movement_length = scaling_factor * math.hypot(*curr_movement)
        elif curr_movement_obj.kind == NestedKind.REPEAT:
            required_movement = NORMALISED_RADIUS

        if curr_movement_length > required_movement:
            factor = (curr_movement_length - required_movement) / curr_movement_length
            curr_cursor_position = (
                curr_cursor_position[0] + curr_movement[0] * factor,
                curr_cursor_position[1] + curr_movement[1] * factor,
            )
            curr_movement_length *= factor
            do.lazy_travel_distance += curr_movement_length

        if i == len(nested_objects) - 1:
            do.lazy_end_position = curr_cursor_position


def _set_distances(do: OsuDifficultyHitObject, history: list[OsuDifficultyHitObject], clock_rate: float) -> None:
    obj = do.obj

    if obj.kind == OsuObjectKind.SLIDER:
        do.travel_distance = do.lazy_travel_distance * max(1.0, pow(obj.repeat_count, 0.3))
        do.travel_time = max(do.lazy_travel_time / clock_rate, MIN_DELTA_TIME)

    do.minimum_jump_time = do.adjusted_delta_time

    if obj.kind == OsuObjectKind.SPINNER or do.last_obj.kind == OsuObjectKind.SPINNER:
        return

    scaling_factor = NORMALISED_RADIUS / obj.radius

    last_difficulty_object = history[-1] if history else None
    last_last_difficulty_object = history[-2] if len(history) >= 2 else None

    last_cursor_position = _get_end_cursor_position(last_difficulty_object) if last_difficulty_object is not None else do.last_obj.stacked_position

    do.jump_distance = _dist(do.last_obj.stacked_position, obj.stacked_position) * scaling_factor
    do.lazy_jump_distance = _dist(obj.stacked_position, last_cursor_position) * scaling_factor
    do.minimum_jump_distance = do.lazy_jump_distance

    if do.last_obj.kind == OsuObjectKind.SLIDER and last_difficulty_object is not None:
        last_travel_time = max(last_difficulty_object.lazy_travel_time / clock_rate, MIN_DELTA_TIME)
        do.minimum_jump_time = max(do.adjusted_delta_time - last_travel_time, MIN_DELTA_TIME)

        tail_jump_distance = _dist(do.last_obj.stacked_end_position, obj.stacked_position) * scaling_factor
        do.minimum_jump_distance = max(
            0.0,
            min(do.lazy_jump_distance - (MAXIMUM_SLIDER_RADIUS - ASSUMED_SLIDER_RADIUS), tail_jump_distance - MAXIMUM_SLIDER_RADIUS),
        )

    if last_last_difficulty_object is not None and last_last_difficulty_object.obj.kind != OsuObjectKind.SPINNER:
        if last_difficulty_object is not None and last_difficulty_object.obj.kind == OsuObjectKind.SLIDER and last_difficulty_object.travel_distance > 0:
            head = last_difficulty_object.obj.nested[0]
            ox, oy = last_difficulty_object.obj.stack_offset()
            last_cursor_position = (head.position[0] + ox, head.position[1] + oy)

        last_last_cursor_position = _get_end_cursor_position(last_last_difficulty_object)

        angle = _calculate_angle(obj.stacked_position, last_cursor_position, last_last_cursor_position)
        slider_angle = _calculate_slider_angle(obj.stacked_position, last_difficulty_object, last_last_cursor_position)

        vx = obj.stacked_position[0] - last_cursor_position[0]
        vy = obj.stacked_position[1] - last_cursor_position[1]
        do.normalised_vector_angle = math.atan2(abs(vy), abs(vx))

        do.angle = min(angle, slider_angle)


def _calculate_slider_angle(current_position: tuple[float, float], last_difficulty_object: OsuDifficultyHitObject, last_last_cursor_position: tuple[float, float]) -> float:
    last_cursor_position = _get_end_cursor_position(last_difficulty_object)

    if last_difficulty_object.obj.kind == OsuObjectKind.SLIDER and last_difficulty_object.travel_distance > 0:
        second_last_nested = last_difficulty_object.obj.nested[-2]
        ox, oy = last_difficulty_object.obj.stack_offset()
        last_last_cursor_position = (second_last_nested.position[0] + ox, second_last_nested.position[1] + oy)

    return _calculate_angle(current_position, last_cursor_position, last_last_cursor_position)


def _calculate_angle(current_position: tuple[float, float], last_position: tuple[float, float], last_last_position: tuple[float, float]) -> float:
    v1 = _sub(last_last_position, last_position)
    v2 = _sub(current_position, last_position)

    dot = v1[0] * v2[0] + v1[1] * v2[1]
    det = v1[0] * v2[1] - v1[1] * v2[0]

    return abs(math.atan2(det, dot))
