# senku.taiko

Difficulty and performance calculation for osu!taiko.

## Pipeline

```python
from senku.taiko.beatmap import parse_osu_file
from senku.taiko.difficulty import calculate
from senku.taiko.performance import calculate_pp, TaikoJudgements

with open("beatmap.osu", encoding="utf-8-sig") as f:
    text = f.read()

beatmap = parse_osu_file(text)
attributes = calculate(beatmap)

result = calculate_pp(
    attributes,
    TaikoJudgements(n_great=940, n_ok=40, n_meh=0, n_miss=7),
    overall_difficulty=beatmap.overall_difficulty,
)

print(attributes.star_rating, result["total"])
```

## `parse_osu_file`

```python
def parse_osu_file(text: str) -> TaikoBeatmap
```

Returns a `TaikoBeatmap`:

| Field | Type | Notes |
|---|---|---|
| `overall_difficulty` | `float` | Determines the great hit window |
| `slider_multiplier` | `float` | |
| `notes` | `list[TaikoNote]` | Sorted by `start_time` |
| `timing_points` | `list[TimingPoint]` | Sorted by `time`, used for BPM/scroll-speed lookups |

`TaikoNote` has `start_time` and `kind` (`TaikoObjectKind.CENTRE` [don],
`RIM` [kat], `DRUMROLL`, `SWELL`); `is_hit` is `True` for `CENTRE`/`RIM`
only. `TimingPoint` has `time`, `beat_length` (negative = inherited SV
point, positive = uninherited ms-per-beat), `scroll_speed`.

`TaikoBeatmap.bpm_and_slider_velocity_at(time)` returns `(bpm,
effective_sv_multiplier)` at a given timestamp, honoring inherited/
uninherited timing point chaining.

## `difficulty.calculate`

```python
def calculate(
    beatmap: TaikoBeatmap,
    clock_rate: float = 1.0,
    is_convert: bool = False,
    is_relax: bool = False,
) -> TaikoDifficultyAttributes
```

- `clock_rate` — `1.5` for DT/NC, `0.75` for HT.
- `is_convert` — set for std→taiko converted beatmaps; affects some
  internal scaling.
- `is_relax` — taiko's own Relax handling at the difficulty-calculation
  level (separate from `RX`-style performance-only mods in other modes).

Returns `TaikoDifficultyAttributes`:

| Field | Meaning |
|---|---|
| `star_rating` | Final combined star rating |
| `mechanical_difficulty` | Physical/tapping difficulty component |
| `rhythm_difficulty` | Rhythm-complexity component |
| `reading_difficulty` | Visual/reading component |
| `colour_difficulty` | Don/kat colour-alternation component |
| `stamina_difficulty` | Stamina component |
| `mono_stamina_factor` | Same-colour-run stamina scaling |
| `consistency_factor` | Strain consistency scaling |
| `stamina_top_strains` | Top-weighted stamina strains |
| `great_hit_window` | Hit window for the 300/"great" judgement, derived from OD |

## `performance.calculate_pp`

```python
def calculate_pp(
    attributes: TaikoDifficultyAttributes,
    judgements: TaikoJudgements,
    overall_difficulty: float,
    clock_rate: float = 1.0,
    hidden: bool = False,
    flashlight: bool = False,
    easy: bool = False,
    is_convert: bool = False,
    is_classic: bool = False,
) -> dict
```

`TaikoJudgements(n_great=0, n_ok=0, n_meh=0, n_miss=0)`.

- `overall_difficulty` — pass `beatmap.overall_difficulty` (pre-mod; the
  great hit window is recomputed internally from OD + `clock_rate`).
- `clock_rate` — must match what was passed to `calculate`.
- `hidden` / `flashlight` — HD/FL performance multipliers (`×1.025`/`×1.05`
  family, see `_compute_difficulty_value`).
- `easy` — EZ performance multiplier (`×0.975` on the difficulty
  component).
- `is_convert` — must match `calculate`.
- `is_classic` — affects the deviation/accuracy model for classic
  (non-lazer) scores.

Returns a `dict`, not a float:

| Key | Meaning |
|---|---|
| `"difficulty"` | Difficulty (strain) pp component |
| `"accuracy"` | Accuracy pp component |
| `"estimated_unstable_rate"` | UR estimated from judgement counts, used internally for the accuracy component |
| `"total"` | `difficulty + accuracy` — the final pp value |

## Mod support matrix

| Mod | Where it's applied |
|---|---|
| `DT`/`NC` | `clock_rate=1.5` on both `calculate` and `calculate_pp` |
| `HT`/`DC` | `clock_rate=0.75` on both `calculate` and `calculate_pp` |
| `HD` | `hidden=True` on `calculate_pp` |
| `FL` | `flashlight=True` on `calculate_pp` |
| `EZ` | `easy=True` on `calculate_pp` |
| Relax | `is_relax=True` on `calculate` (difficulty-level only; no dedicated performance-side RX handling in taiko) |
| Convert (std→taiko) | `is_convert=True` on both `calculate` and `calculate_pp` |
