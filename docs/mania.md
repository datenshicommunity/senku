# senku.mania

Difficulty and performance calculation for osu!mania. Simplest of the four
modes — no separate difficulty-attributes dataclass; `star_rating` is a
single float, and pp is derived directly from it plus judgement counts.

## Pipeline

```python
from senku.mania.beatmap import parse_osu_file
from senku.mania.difficulty import star_rating, max_combo
from senku.mania.performance import calculate_pp, ManiaJudgements

with open("beatmap.osu", encoding="utf-8-sig") as f:
    text = f.read()

beatmap = parse_osu_file(text)
sr = star_rating(beatmap)

pp = calculate_pp(
    sr,
    ManiaJudgements(n_perfect=1200, n_great=50, n_good=0, n_ok=0, n_meh=0, n_miss=0),
)

print(sr, pp, max_combo(beatmap))
```

## `parse_osu_file`

```python
def parse_osu_file(text: str) -> ManiaBeatmap
```

No mod parameters — mania's DT/HT are handled via `clock_rate` on
`star_rating`, and EZ/NF/HR have no difficulty effect in this
implementation (only the pp-side multipliers in `calculate_pp`).

Returns a `ManiaBeatmap`:

| Field | Type | Notes |
|---|---|---|
| `column_count` | `int` | Number of playfield columns (keys) |
| `overall_difficulty` | `float` | Used only for the perfect/great hit-window definition upstream, not by senku's star rating or pp formulas |
| `notes` | `list[ManiaNote]` | Sorted by `start_time` ascending |

`ManiaNote` has `start_time`, `end_time` (equal to `start_time` for a
regular note), `column`, and an `is_hold` property (`end_time >
start_time`).

Column assignment (`x` position → column index) deliberately narrows to
`float32` at each step to match the reference client's single-precision
arithmetic — a note landing on or near a column boundary can otherwise be
misclassified in double precision.

## `difficulty.star_rating`

```python
def star_rating(beatmap: ManiaBeatmap, clock_rate: float = 1.0) -> float
```

- `clock_rate` — `1.5` for DT/NC, `0.75` for HT.

## `difficulty.max_combo`

```python
def max_combo(beatmap: ManiaBeatmap) -> int
```

Total note count (holds count once, not per tick) — the max achievable
combo for the beatmap.

## `performance.calculate_pp`

```python
def calculate_pp(
    star_rating: float,
    judgements: ManiaJudgements,
    no_fail: bool = False,
    easy: bool = False,
) -> float
```

`ManiaJudgements` fields (all default `0`): `n_perfect` (MAX/rainbow 300),
`n_great` (300), `n_good` (200), `n_ok` (100), `n_meh` (50), `n_miss`.

Two computed properties used internally (also useful for callers):

- `total_hits` — sum of all six counts.
- `custom_accuracy` — judgement-weighted accuracy (`PERFECT=320`,
  `GREAT=300`, `GOOD=200`, `OK=100`, `MEH=50`, weighted average over
  `total_hits * 320`), **not** the standard osu!mania accuracy percentage.

- `no_fail` — applies the `0.75×` NF multiplier.
- `easy` — applies the `0.5×` EZ multiplier.

There is no Relax mode for mania (RX doesn't apply) and no `DA`/`HD`/`FL`
support — mania's real difficulty/performance model doesn't vary by those
mods beyond what's modeled here.

## Mod support matrix

| Mod | Where it's applied |
|---|---|
| `DT`/`NC` | `clock_rate=1.5` on `star_rating` |
| `HT`/`DC` | `clock_rate=0.75` on `star_rating` |
| `NF` | `no_fail=True` on `calculate_pp` |
| `EZ` | `easy=True` on `calculate_pp` |
