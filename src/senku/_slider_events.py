"""Ruleset-agnostic slider event timeline generation (head/tick/repeat/tail,
plus the historical "legacy last tick" used by rulesets that need it for tiny
droplet generation). Independent implementation; not adapted from any
specific codebase.
"""

from __future__ import annotations

TAIL_LENIENCY = -36.0


def generate_slider_events(start_time: float, span_duration: float, velocity: float, tick_distance: float,
                            total_distance: float, span_count: int) -> list[dict]:
    max_length = 100000.0
    length = min(max_length, total_distance)
    tick_distance = min(max(tick_distance, 0.0), length)
    min_distance_from_end = velocity * 10

    events: list[dict] = [{"type": "head", "span_index": 0, "time": start_time, "path_progress": 0.0}]

    for span in range(span_count):
        span_start_time = start_time + span * span_duration
        reversed_ = span % 2 == 1

        if tick_distance != 0:
            ticks = []
            d = tick_distance
            while d <= length:
                if d >= length - min_distance_from_end:
                    break
                path_progress = d / length
                time_progress = 1 - path_progress if reversed_ else path_progress
                ticks.append({"type": "tick", "span_index": span, "time": span_start_time + time_progress * span_duration, "path_progress": path_progress})
                d += tick_distance
            if reversed_:
                ticks.reverse()
            events.extend(ticks)

        if span < span_count - 1:
            events.append({
                "type": "repeat", "span_index": span,
                "time": span_start_time + span_duration,
                "path_progress": float((span + 1) % 2),
            })

    total_duration = span_count * span_duration
    final_span_index = span_count - 1
    final_span_start_time = start_time + final_span_index * span_duration

    legacy_last_tick_time = max(start_time + total_duration / 2, (final_span_start_time + span_duration) + TAIL_LENIENCY)
    legacy_last_tick_progress = (legacy_last_tick_time - final_span_start_time) / span_duration if span_duration > 0 else 0.0
    if span_count % 2 == 0:
        legacy_last_tick_progress = 1 - legacy_last_tick_progress

    events.append({"type": "legacy_last_tick", "span_index": final_span_index, "time": legacy_last_tick_time, "path_progress": legacy_last_tick_progress})
    events.append({"type": "tail", "span_index": final_span_index, "time": start_time + total_duration, "path_progress": float(span_count % 2)})

    return events
