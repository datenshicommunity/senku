# senku.osu

Difficulty and performance calculation for osu! standard, including full
mod support and a legacy ScoreV1 simulator for replayed/combo-broken
scores.

## Pipeline

```python
from senku.osu.beatmap import parse_osu_file
from senku.osu.difficulty import calculate
from senku.osu.performance import calculate_pp, OsuJudgements

with open("beatmap.osu", encoding="utf-8-sig") as f:
    text = f.read()

beatmap = parse_osu_file(text)
attributes = calculate(beatmap)

pp = calculate_pp(
    attributes,
    OsuJudgements(n300=980, n100=15, n50=2, n_miss=0),
    score_max_combo=attributes.max_combo,
    approach_rate=beatmap.approach_rate,
    overall_difficulty_raw=beatmap.overall_difficulty,
)

print(attributes.star_rating, pp)
```

## `parse_osu_file`

```python
def parse_osu_file(
    text: str,
    mods: frozenset[str] = frozenset(),
    difficulty_adjust: dict[str, float] | None = None,
) -> OsuBeatmap
```

- `text` — full contents of a `.osu` file (open with `encoding="utf-8-sig"`
  — beatmap files commonly carry a UTF-8 BOM).
- `mods` — beatmap-affecting mods to bake into CS/AR/OD/HP and object
  timing at parse time. Only `HR` and `EZ` matter here (they scale
  CS/AR/OD/HP via `_apply_difficulty_mods`, including HR's slider-endpoint
  vertical reflection); DT/HT are handled separately via `clock_rate` on
  `calculate`/`calculate_pp`, not here.
- `difficulty_adjust` — direct CS/AR/OD/HP override for `ModDifficultyAdjust`
  (DA), applied *after* HR/EZ scaling. Dict keys: `"cs"`, `"ar"`, `"od"`,
  `"hp"` (all optional; omitted keys keep the HR/EZ-scaled value). Supports
  "extended limits" values outside the normal `[0, 10]` range — AR down to
  `-10` / up to `11`, CS/OD/HP up to `11`. When using DA, also pass
  `mods=frozenset({"DA", ...})` to `calculate`/`calculate_pp` so the
  extended-limits hit-window/approach-time math applies consistently.

Returns an `OsuBeatmap`:

| Field | Type | Notes |
|---|---|---|
| `circle_size` | `float` | Post-mod/DA CS |
| `approach_rate` | `float` | Post-mod/DA AR |
| `overall_difficulty` | `float` | Post-mod/DA OD |
| `drain_rate` | `float` | Post-mod/DA HP |
| `slider_multiplier` | `float` | |
| `slider_tick_rate` | `float` | |
| `format_version` | `int` | `.osu` file format version |
| `stack_leniency` | `float` | |
| `objects` | `list[OsuObject]` | Hit circles/sliders/spinners, in time order, with stacking already applied |
| `breaks` | `list[tuple[float, float]]` | `(start, end)` pairs |

`OsuObject` carries `kind` (`OsuObjectKind.CIRCLE/SLIDER/SPINNER`),
`start_time`/`end_time`, unstacked `position`/`end_position`, `stack_height`,
`scale`, and for sliders: `path`, `path_distance`, `span_count`,
`repeat_count`, `velocity`, `duration`, and `nested` (a list of
`NestedObject` — the slider head/repeat/tail/tick sub-objects used by
difficulty calculation).

## `difficulty.calculate`

```python
def calculate(
    beatmap: OsuBeatmap,
    clock_rate: float = 1.0,
    hidden: bool = False,
    flashlight: bool = False,
    mods: frozenset[str] = frozenset(),
    magnetised_strength: float = 0.5,
    deflate_start_scale: float = 2.0,
) -> OsuDifficultyAttributes
```

- `clock_rate` — `1.5` for DT/NC, `0.75` for HT. Feeds directly into object
  timing before any skill runs.
- `hidden` — enables the Reading skill's hidden-specific opacity curve.
- `flashlight` — enables the Flashlight skill (otherwise it's skipped
  entirely; `flashlight_difficulty` stays `0.0`).
- `mods` — performance/skill-affecting mod set for AP/RX/BL/TC/TD/MG/DF/DA
  (see the [mod matrix](#mod-support-matrix) below). HR/EZ/DA CS-AR-OD-HP
  changes must already be baked into `beatmap` via `parse_osu_file`; passing
  `"DA"` here only affects skill-level behavior, not CS/AR/OD/HP values.
- `magnetised_strength` — only relevant with `"MG"` in `mods`.
- `deflate_start_scale` — only relevant with `"DF"` in `mods`.

Returns `OsuDifficultyAttributes`:

| Field | Meaning |
|---|---|
| `star_rating` | Final combined star rating |
| `aim_difficulty` / `speed_difficulty` / `reading_difficulty` / `flashlight_difficulty` | Per-skill difficulty values feeding `star_rating` |
| `slider_factor` | Aim-without-sliders / aim-with-sliders ratio |
| `aim_difficult_strain_count` / `speed_difficult_strain_count` | Effective counts of "difficult" strains per skill, used by the miss penalty in pp calculation |
| `reading_difficult_note_count` | Same idea for the reading skill |
| `speed_note_count` | Used for the speed deviation estimate |
| `aim_difficult_slider_count` | Sliders contributing meaningfully to aim difficulty |
| `aim_top_weighted_slider_factor` / `speed_top_weighted_slider_factor` | Slider-break estimate inputs |
| `max_combo` | Maximum achievable combo on this beatmap (works correctly on unranked/graveyard maps — see [Design notes](../README.md#design-notes)) |
| `hit_circle_count` / `slider_count` / `spinner_count` | Object counts |
| `nested_score_per_object` / `legacy_score_base_multiplier` / `maximum_legacy_combo_score` | Inputs for the legacy ScoreV1 simulator ([legacy_score.py](#legacy-scorev1-simulation)) |

## `performance.calculate_pp`

```python
def calculate_pp(
    attributes: OsuDifficultyAttributes,
    judgements: OsuJudgements,
    score_max_combo: int,
    approach_rate: float,
    overall_difficulty_raw: float,
    clock_rate: float = 1.0,
    flashlight: bool = False,
    legacy_total_score: float | None = None,
    mods: frozenset[str] = frozenset(),
    drain_rate: float = 5.0,
) -> float
```

`OsuJudgements(n300=0, n100=0, n50=0, n_miss=0)` — hit counts for the play
being scored.

- `score_max_combo` — the combo actually achieved (not the map's max
  combo, unless the play is a full combo).
- `approach_rate` / `overall_difficulty_raw` — pass `beatmap.approach_rate`
  / `beatmap.overall_difficulty` from the *same* `OsuBeatmap` used for
  `calculate` (post-mod/DA values).
- `clock_rate` — must match what was passed to `calculate`.
- `flashlight` — must match what was passed to `calculate`.
- `legacy_total_score` — the score's real legacy total score, if known.
  When provided, uses the score-based miss-count estimator
  (`legacy_score.py`) instead of the combo-based heuristic — materially
  more accurate for combo-broken plays (see
  `tests/test_osu.py::test_osu_legacy_score_simulator_broken_combo`, a
  ~2.7% pp difference on a real case).
- `mods` — the same performance-affecting mod set passed to `calculate`,
  plus any performance-only mods (`NF`, `SO`, `AP`, `RX`, `BL`, `TC`, `TD`,
  `MG`, `DF`) and `"DA"` if difficulty-adjust was used.
- `drain_rate` — `beatmap.drain_rate`; used by the NF multiplier.

## Mod support matrix

| Mod | Where it's applied |
|---|---|
| `DT`/`NC` | `clock_rate=1.5` on both `calculate` and `calculate_pp` |
| `HT`/`DC` | `clock_rate=0.75` on both `calculate` and `calculate_pp` |
| `HR` | `parse_osu_file(text, mods={"HR"})` — scales CS/AR/OD/HP and reflects sliders vertically |
| `EZ` | `parse_osu_file(text, mods={"EZ"})` — scales CS/AR/OD/HP |
| `DA` (ModDifficultyAdjust) | `parse_osu_file(text, difficulty_adjust={"cs":.., "ar":.., "od":.., "hp":..})`, plus `mods={"DA"}` on `calculate`/`calculate_pp` for extended-limits math |
| `HD` | `calculate(beatmap, hidden=True)` |
| `FL` | `calculate(beatmap, flashlight=True)`, `calculate_pp(..., flashlight=True)` |
| `NF` | `mods={"NF"}` on `calculate_pp` — score multiplier penalty |
| `SO` | `mods={"SO"}` on `calculate_pp` — spinner-count-based multiplier penalty |
| `AP` (Autopilot) | `mods={"AP"}` on `calculate` and `calculate_pp` — zeroes aim/speed-adjacent contributions, scales reading/flashlight down |
| `RX` (Relax) | `mods={"RX"}` on `calculate` and `calculate_pp` — zeroes speed/accuracy contributions, scales aim/flashlight, adjusts effective miss count from 100s/50s |
| `BL` (Blinds) | `mods={"BL"}` on `calculate_pp` — aim/speed/accuracy bonus |
| `TC` (Traceable) | `mods={"TC"}` on `calculate_pp` — aim/accuracy bonus |
| `TD` (Touch Device) | `mods={"TD"}` on `calculate` and `calculate_pp` — reshapes aim/reading/flashlight curves |
| `MG` (Magnetised) | `mods={"MG"}`, `magnetised_strength=` on `calculate` — reshapes aim/reading/flashlight |
| `DF` (Deflate) | `mods={"DF"}`, `deflate_start_scale=` on `calculate` — reshapes flashlight |

`mods` must be passed consistently to *both* `calculate` and `calculate_pp`
for any mod that affects both (AP, RX, TD, MG, DF, DA) — `calculate_pp`
does not re-derive mods from `attributes`.

## Legacy ScoreV1 simulation

`senku/osu/legacy_score.py` reconstructs an estimate of what a
pre-lazer/ScoreV1 client would have reported as the total score for a
given judgement sequence, so that a real submitted `legacy_total_score`
can be used to back out a more accurate miss count than combo alone
allows (a broken combo is consistent with many different miss
placements; the actual score value narrows this down).

Key functions:

- `calculate_difficulty_peppy_stars(...)` — legacy (pre-lazer) star rating,
  used only as an input to the legacy score model, not exposed as the
  primary star rating.
- `get_legacy_score_multiplier(mods, score_v2=False)` — the classic
  mod score multiplier (e.g. HD `1.06`, HR `1.06`, DT `1.12`, EZ `0.5`,
  `NF` checked internally from `mods`).
- `simulate_combo_score(...)` / `calculate_nested_score_per_object(...)` —
  per-object legacy score contribution given combo state.
- `calculate_score_based_miss_count(...)` — the estimator `calculate_pp`
  calls internally when `legacy_total_score` is provided.

These aren't usually called directly — pass `legacy_total_score=` to
`calculate_pp` and the simulator runs automatically.
