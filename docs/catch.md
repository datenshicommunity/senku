# senku.catch

Difficulty and performance calculation for osu!catch.

## Pipeline

```python
from senku.catch.beatmap import parse_osu_file
from senku.catch.difficulty import calculate
from senku.catch.performance import calculate_pp, CatchJudgements

with open("beatmap.osu", encoding="utf-8-sig") as f:
    text = f.read()

beatmap = parse_osu_file(text)
attributes = calculate(beatmap)

pp = calculate_pp(
    attributes,
    CatchJudgements(n_fruit=983, n_large_droplet=0, n_small_droplet=242, n_small_droplet_miss=0, n_miss=0),
    max_combo_achieved=983,
    approach_rate=beatmap.approach_rate,
)

print(attributes.star_rating, pp)
```

## `parse_osu_file`

```python
def parse_osu_file(text: str) -> CatchBeatmap
```

Returns a `CatchBeatmap`:

| Field | Type | Notes |
|---|---|---|
| `circle_size` | `float` | Determines catcher width via `catch_width()` |
| `approach_rate` | `float` | |
| `slider_multiplier` | `float` | |
| `slider_tick_rate` | `float` | |
| `objects` | `list[CatchObject]` | Sorted, palpable objects only — bananas and (already-excluded) tiny droplets are handled by the caller/parser as needed |

`CatchBeatmap.catch_width()` returns the catcher's effective catch width
in playfield units, derived from `circle_size`.

`CatchObject` has `start_time`, `x` (already includes any hyperdash
x-offset), `kind` (`CatchObjectKind.FRUIT/DROPLET/TINY_DROPLET/BANANA` —
`BANANA` is excluded from difficulty entirely), `hyper_dash_target`, and
`distance_to_hyper_dash`; `hyper_dash` is `True` when
`hyper_dash_target is not None`.

## `difficulty.calculate`

```python
def calculate(beatmap: CatchBeatmap, clock_rate: float = 1.0) -> CatchDifficultyAttributes
```

- `clock_rate` — `1.5` for DT/NC, `0.75` for HT.

Returns `CatchDifficultyAttributes`:

| Field | Meaning |
|---|---|
| `star_rating` | Final star rating |
| `max_combo` | Maximum achievable combo (fruits + droplets, excluding bananas) |

## `performance.calculate_pp`

```python
def calculate_pp(
    attributes: CatchDifficultyAttributes,
    judgements: CatchJudgements,
    max_combo_achieved: int,
    approach_rate: float,
    clock_rate: float = 1.0,
    hidden: bool = False,
    flashlight: bool = False,
    no_fail: bool = False,
) -> float
```

`CatchJudgements` fields (all default `0`, osu!catch's judgement naming
maps to standard terms as follows):

| Field | Standard equivalent |
|---|---|
| `n_fruit` | count300 / Great |
| `n_large_droplet` | count100 |
| `n_small_droplet` | count50 |
| `n_small_droplet_miss` | countkatu |
| `n_miss` | countmiss (fruit misses + large-droplet misses) |

- `max_combo_achieved` — the combo actually reached in the play.
- `approach_rate` — pass `beatmap.approach_rate`.
- `clock_rate` — must match what was passed to `calculate`.
- `hidden` — HD multiplier; scales with `approach_rate` (steeper bonus
  below AR10, flatter above).
- `flashlight` — FL multiplier (`×1.35 × length_bonus`).
- `no_fail` — NF multiplier (`max(0.90, 1.0 - 0.02 × n_miss)`).

Helper functions also exported from `performance.py`:

- `_accuracy(judgements)` / `total_hits(judgements)` /
  `total_combo_hits(judgements)` — accuracy and hit-count helpers (private
  by convention but stable; used internally by `calculate_pp`).
- `preempt_to_approach_rate(preempt_ms)` — inverse of the standard AR→
  preempt-time formula, useful when only a raw preempt time is known.
- `difficulty_range(difficulty, min_value, mid_value, max_value)` — the
  standard OD/AR/CS/HP piecewise linear interpolation helper.

## Mod support matrix

| Mod | Where it's applied |
|---|---|
| `DT`/`NC` | `clock_rate=1.5` on both `calculate` and `calculate_pp` |
| `HT`/`DC` | `clock_rate=0.75` on both `calculate` and `calculate_pp` |
| `HD` | `hidden=True` on `calculate_pp` |
| `FL` | `flashlight=True` on `calculate_pp` |
| `NF` | `no_fail=True` on `calculate_pp` |

There's no CS/AR/OD difficulty-adjust or HR/EZ-specific handling
implemented in `parse_osu_file` for catch yet — pass an already-adjusted
`CatchBeatmap` if you need HR/EZ CS/AR scaling.
