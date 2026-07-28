# senku

Another rhythm game performance calculator — pure Python, no external
runtime dependencies beyond NumPy.

senku computes difficulty ("star rating") and performance ("pp") for four
gameplay modes: `mania`, `taiko`, `catch`, and `osu` (standard). Each mode
is self-contained under `senku.<mode>` and exposes the same three-step
shape: parse a beatmap, calculate its difficulty attributes, then calculate
performance for a specific play.

Detailed per-mode reference (full function signatures, dataclass fields,
mod-support matrices): [docs/osu.md](docs/osu.md) ·
[docs/mania.md](docs/mania.md) · [docs/taiko.md](docs/taiko.md) ·
[docs/catch.md](docs/catch.md).

## Install

```bash
pip install -e .
```

Requires Python 3.10+ and NumPy.

## Package layout

```
senku/
├── mania/  beatmap.py  difficulty.py  performance.py
├── taiko/  beatmap.py  difficulty.py  performance.py
├── catch/  beatmap.py  difficulty.py  performance.py
└── osu/    beatmap.py  difficulty.py  performance.py  legacy_score.py
            aim.py  speed.py  reading.py  flashlight.py  (osu! skills)
```

Each `beatmap.py` exposes `parse_osu_file(text) -> <Mode>Beatmap` from raw
`.osu` file contents. Each `difficulty.py` exposes `calculate(beatmap,
...) -> <Mode>DifficultyAttributes` (mania instead exposes a plain
`star_rating(beatmap, ...) -> float` plus a separate `max_combo(beatmap)`
helper — see [docs/mania.md](docs/mania.md)). Each `performance.py`
exposes a `<Mode>Judgements` dataclass (hit-count input) and
`calculate_pp(attributes, judgements, ...) -> float` (taiko's returns a
`dict` with a `"total"` key — see [docs/taiko.md](docs/taiko.md)).

All dataclasses are immutable (`frozen=True` where applicable) and every
function takes its inputs explicitly — no mutable global state, no hidden
caching, safe to call concurrently from multiple threads/processes.

## Usage

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

The other three modes follow the same pattern:

```python
from senku.mania.beatmap import parse_osu_file
from senku.mania.difficulty import star_rating
from senku.mania.performance import calculate_pp, ManiaJudgements

from senku.taiko.beatmap import parse_osu_file
from senku.taiko.difficulty import calculate
from senku.taiko.performance import calculate_pp, TaikoJudgements

from senku.catch.beatmap import parse_osu_file
from senku.catch.difficulty import calculate
from senku.catch.performance import calculate_pp, CatchJudgements
```

### Mods

`osu` (standard) supports the full mod set: `DT`/`HT`/`NC`/`DC` (via
`clock_rate`), `HR`/`EZ`/`DA` (via `parse_osu_file(text, mods=...,
difficulty_adjust=...)`), `HD`/`FL` (via `calculate(..., hidden=True,
flashlight=True)`), and the performance-only mods
`NF`/`SO`/`AP`/`RX`/`BL`/`TC`/`TD`/`MG`/`DF` (via `mods=frozenset({...})`
passed to `calculate`/`calculate_pp`). Full matrix, including which
function each mod's parameter lives on: [docs/osu.md](docs/osu.md#mod-support-matrix).

`mania` supports `DT`/`HT`/`NC`/`DC` (via `clock_rate` on `star_rating`)
and `NF`/`EZ` (via `no_fail=`/`easy=` on `calculate_pp`) — see
[docs/mania.md](docs/mania.md#mod-support-matrix).

`taiko` supports `DT`/`HT`/`NC`/`DC`/`HR`/`EZ`/`HD`/`FL`/`RX`, plus
std→taiko convert handling — see
[docs/taiko.md](docs/taiko.md#mod-support-matrix). HR/EZ scale OD *and*
`slider_multiplier` (not just OD), and RX is a genuine difficulty-level
change in taiko, unlike osu!std.

`catch` supports `DT`/`HT`/`NC`/`DC`/`HR`/`EZ`/`HD`/`FL`/`NF` — see
[docs/catch.md](docs/catch.md#mod-support-matrix). HR also runs a
bit-exact port of the real client's legacy RNG fruit-position jitter
(`CatchBeatmapProcessor.ApplyPositionOffsets`), needed because it changes
hyperdash-target detection.

For osu! standard scores with a known legacy total score (real submitted
plays), pass `legacy_total_score=` to `calculate_pp` for a more precise
miss-count estimate on combo-broken plays than the combo-based heuristic
alone — see [docs/osu.md](docs/osu.md#legacy-scorev1-simulation).

## Design notes

- Every mode is independently validated against real leaderboard scores
  and, for osu! standard's mod matrix, cross-checked against an
  independent reference implementation for algorithm-shape agreement;
  see `tests/` for the fixture beatmaps and pinned regression values.
- Graveyard/unranked/unusual beatmaps are supported the same as ranked
  ones — difficulty calculation here doesn't depend on a beatmap's ranked
  status. This matters in practice: some official APIs only return
  correct attributes (e.g. max combo) for ranked/loved/qualified maps and
  silently return broken/zeroed values for graveyard maps; senku doesn't
  have that restriction.
- No mutable global state; every function takes its beatmap/attributes/
  judgements explicitly, so it's safe to call concurrently.
- `senku/_diffutils.py` holds small numeric primitives shared across
  modes (`erf`, `erf_inv`, `logistic_full`, `reverse_lerp`, `smoothstep`,
  `norm`, `SQRT2`) — pure-Python reimplementations of the special
  functions the algorithms need, since senku has no SciPy dependency.

## Testing

```bash
uv venv .venv && source .venv/bin/activate
uv pip install -e . pytest
pytest
```

22 regression tests across all four modes, pinned to senku's own output
(`rel=1e-9`) with the real leaderboard score or reference-implementation
value each case was cross-validated against at authoring time recorded as
a comment — see `tests/test_*.py`.

## License

MIT — see [LICENSE](LICENSE). See [NOTICE](NOTICE) for attribution.
