"""Top-level osu!catch star rating: models difficulty as how far and how
often the player's catcher must move to intercept fruits/droplets,
with bonuses for direction changes, streams, and "edge dash" hyperdash
timing windows. Independent implementation; not adapted from any
specific codebase.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .._strain_skill import StrainDecaySkill
from .beatmap import CatchBeatmap, CatchObjectKind

NORMALIZED_HALF_CATCHER_WIDTH = 41.0
ABSOLUTE_PLAYER_POSITIONING_ERROR = 16.0
DIRECTION_CHANGE_BONUS = 21.0
DIFFICULTY_MULTIPLIER = 4.59


@dataclass
class _MovementObject:
    start_time: float
    delta_time: float  # vs previous PALPABLE (non-tiny) object, per DifficultyHitObject base semantics
    strain_time: float  # max(40, delta_time)
    distance_moved: float
    exact_distance_moved: float
    hyper_dash: bool
    distance_to_hyper_dash: float
    clock_rate: float


@dataclass
class CatchDifficultyAttributes:
    star_rating: float
    max_combo: int


def _build_movement_objects(beatmap: CatchBeatmap, clock_rate: float) -> list[_MovementObject]:
    # Only fruits and (non-tiny) droplets contribute to combo/difficulty --
    # tiny droplets and bananas are excluded entirely.
    palpable = [o for o in beatmap.objects if o.kind in (CatchObjectKind.FRUIT, CatchObjectKind.DROPLET)]
    if len(palpable) < 2:
        return []

    half_catcher_width = beatmap.catch_width() / 2
    # Extra shrink beyond CS 5.5 -- applies only to movement/difficulty-object
    # construction, NOT to Catcher.CalculateCatchWidth itself (beatmap.catch_width()
    # above) and NOT to hyperdash-target detection at parse time (_compute_hyperdash
    # in beatmap.py uses the raw width). Below CS 5.5 this is a no-op.
    half_catcher_width *= 1.0 - max(0.0, beatmap.circle_size - 5.5) * 0.0625
    scaling_factor = NORMALIZED_HALF_CATCHER_WIDTH / half_catcher_width

    normalized_positions = [o.x * scaling_factor for o in palpable]
    times = [o.start_time / clock_rate for o in palpable]

    objects: list[_MovementObject] = []
    last_player_position = normalized_positions[0]

    for i in range(1, len(palpable)):
        normalized_position = normalized_positions[i]
        delta_time = times[i] - times[i - 1]

        player_position = min(
            max(last_player_position, normalized_position - (NORMALIZED_HALF_CATCHER_WIDTH - ABSOLUTE_PLAYER_POSITIONING_ERROR)),
            normalized_position + (NORMALIZED_HALF_CATCHER_WIDTH - ABSOLUTE_PLAYER_POSITIONING_ERROR),
        )

        distance_moved = player_position - last_player_position
        exact_distance_moved = normalized_position - last_player_position

        prev_object = palpable[i - 1]

        objects.append(_MovementObject(
            start_time=times[i],
            delta_time=delta_time,
            strain_time=max(40.0, delta_time),
            distance_moved=distance_moved,
            exact_distance_moved=exact_distance_moved,
            hyper_dash=prev_object.hyper_dash,
            distance_to_hyper_dash=prev_object.distance_to_hyper_dash,
            clock_rate=clock_rate,
        ))

        # After a hyperdash we ARE in the correct position, always.
        if prev_object.hyper_dash:
            last_player_position = normalized_position
        else:
            last_player_position = player_position

    return objects


def _movement_difficulty(objects: list[_MovementObject], index: int, is_relax: bool = False) -> float:
    current = objects[index]
    last = objects[index - 1] if index >= 1 else None
    last_last = objects[index - 2] if index >= 2 else None

    catcher_speed_multiplier = current.clock_rate

    weighted_strain_time = current.strain_time + 13 + (3 / catcher_speed_multiplier)
    distance_addition = pow(abs(current.distance_moved), 1.3) / 510
    sqrt_strain = math.sqrt(weighted_strain_time)

    if abs(current.distance_moved) > 0.1:
        # Direction-change bonus prices the cost of reversing a held-key discrete
        # movement commitment -- Relax drives the catcher via a stateless absolute
        # mouse-position assignment (no direction/momentum state to reverse), so
        # this mechanic doesn't apply at all under RX, not just less.
        if (not is_relax and index >= 1 and last is not None and abs(last.distance_moved) > 0.1
                and _sign(current.distance_moved) != _sign(last.distance_moved)):
            bonus_factor = min(50.0, abs(current.distance_moved)) / 50
            antiflow_factor = max(min(70.0, abs(last.distance_moved)) / 70, 0.38)
            distance_addition += (
                DIRECTION_CHANGE_BONUS
                / math.sqrt(last.strain_time + 16)
                * bonus_factor
                * antiflow_factor
                * max(1 - pow(weighted_strain_time / 1000, 3), 0.0)
            )

        distance_addition += (
            12.5 * min(abs(current.distance_moved), NORMALIZED_HALF_CATCHER_WIDTH * 2)
            / (NORMALIZED_HALF_CATCHER_WIDTH * 6)
            / sqrt_strain
        )

    # Linear spacing nerf.
    linear_spacing_count = 0
    for i in range(min(index, 10)):
        prev = objects[index - i - 1]
        if _sign(current.distance_moved) != _sign(prev.distance_moved) or current.distance_moved == 0 or prev.distance_moved == 0:
            break
        current_spacing = abs(current.distance_moved / current.strain_time)
        prev_spacing = abs(prev.distance_moved / prev.strain_time)
        relative_difference = abs(current_spacing / prev_spacing - 1)
        if relative_difference > 0.05:
            break
        linear_spacing_count += 1

    distance_addition *= pow(0.7, linear_spacing_count)

    # Edge dash bonus.
    if current.distance_to_hyper_dash <= 20.0:
        edge_dash_bonus = 5.7 if not current.hyper_dash else 0.0
        distance_addition *= 1.0 + edge_dash_bonus * ((20 - current.distance_to_hyper_dash) / 20) * pow(
            min(current.strain_time * catcher_speed_multiplier, 265) / 265, 1.5
        )

    # "Buzz" pattern nullification.
    if (
        index >= 2
        and last is not None
        and last_last is not None
        and abs(current.exact_distance_moved) <= NORMALIZED_HALF_CATCHER_WIDTH * 2
        and current.exact_distance_moved == -last.exact_distance_moved
        and last.exact_distance_moved == -last_last.exact_distance_moved
        and current.strain_time == last.strain_time
        and last.strain_time == last_last.strain_time
    ):
        distance_addition = 0.0

    if is_relax:
        # Continuous mouse positioning still costs some residual hand-eye-tracking
        # effort, so this is dampened rather than zeroed -- reuses taiko's own
        # established RX dampening factor (`sp /= 1.5` in taiko/difficulty.py) rather
        # than inventing an unvalidated constant. ABSOLUTE_PLAYER_POSITIONING_ERROR
        # is deliberately left untouched: it models reaction-time/misjudgment safety
        # margin, which a mouse doesn't eliminate, and touching it too would
        # double-count the same "no movement momentum to correct" fact already
        # captured by the direction-change removal and this dampening.
        distance_addition /= 1.5

    return distance_addition / weighted_strain_time


def _sign(x: float) -> int:
    return (x > 0) - (x < 0)


def calculate(beatmap: CatchBeatmap, clock_rate: float = 1.0, is_relax: bool = False) -> CatchDifficultyAttributes:
    objects = _build_movement_objects(beatmap, clock_rate)
    if not objects:
        return CatchDifficultyAttributes(star_rating=0.0, max_combo=0)

    movement_skill = StrainDecaySkill(
        skill_multiplier=1.0,
        strain_decay_base=0.2,
        strain_value_of=lambda i: _movement_difficulty(objects, i.index, is_relax),
        decay_weight=0.94,
        section_length=750.0,
    )

    for i, obj in enumerate(objects):
        movement_skill.process(_IndexedTime(obj.start_time, obj.delta_time, i))

    star_rating = math.sqrt(movement_skill.difficulty_value()) * DIFFICULTY_MULTIPLIER

    # TinyDroplets do NOT increment combo -- only fruits and (non-tiny) droplets do.
    max_combo = sum(1 for o in beatmap.objects if o.kind in (CatchObjectKind.FRUIT, CatchObjectKind.DROPLET))

    return CatchDifficultyAttributes(star_rating=star_rating, max_combo=max_combo)


class _IndexedTime:
    """Adapter so StrainDecaySkill's generic (start_time, delta_time) process()
    loop can drive strain_value_of(index) instead of strain_value_of(object)."""
    __slots__ = ("start_time", "delta_time", "index")

    def __init__(self, start_time: float, delta_time: float, index: int):
        self.start_time = start_time
        self.delta_time = delta_time
        self.index = index
