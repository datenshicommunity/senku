"""Ruleset-agnostic legacy timing-point beat length lookup, including the
"precision adjusted" beat length that folds an inherited (green line) slider
velocity multiplier back into an effective beat length via a deliberately
float32-precision round trip (matching legacy stable's floating point
behaviour, reproduced here from public documentation of that behaviour).
Independent implementation; not adapted from any specific codebase.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class TimingPoint:
    time: float
    beat_length: float
    scroll_speed: float = 1.0


def beat_length_at(timing_points: list[TimingPoint], time: float) -> tuple[float, float]:
    beat_length = 500.0
    scroll_speed = 1.0
    last_uninherited = 500.0
    for tp in timing_points:
        if tp.time > time:
            break
        if tp.beat_length > 0:
            last_uninherited = tp.beat_length
            beat_length = tp.beat_length
            scroll_speed = 1.0
        else:
            beat_length = last_uninherited
            scroll_speed = tp.scroll_speed
    return beat_length, scroll_speed


# Rulesets differ only in the clamp range applied to the derived bpm multiplier.
_CLAMP_RANGE = {
    "osu": (10.0, 1000.0),
    "fruits": (10.0, 1000.0),
    "taiko": (10.0, 10000.0),
    "mania": (10.0, 10000.0),
}


def precision_adjusted_beat_length(raw_beat_length: float, scroll_speed: float, ruleset: str = "osu") -> float:
    lo, hi = _CLAMP_RANGE[ruleset]
    slider_velocity_as_beat_length = -100.0 / scroll_speed
    if slider_velocity_as_beat_length < 0:
        bpm_multiplier = float(np.clip(np.float32(-slider_velocity_as_beat_length), lo, hi)) / 100.0
    else:
        bpm_multiplier = 1.0
    return raw_beat_length * bpm_multiplier
