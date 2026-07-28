# senku

Another rhythm game performance calculator — pure Python, no external
runtime dependencies beyond NumPy.

senku computes difficulty ("star rating") and performance ("pp") for four
gameplay modes: `mania`, `taiko`, `catch`, and `osu` (standard). Each mode
is self-contained under `senku.<mode>` and exposes the same three-step
shape: parse a beatmap, calculate its difficulty attributes, then calculate
performance for a specific play.

## Install

```bash
pip install -e .
```

Requires Python 3.10+ and NumPy.

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

### Mods (osu! standard)

The `osu` mode supports the full mod set: `DT`/`HT` (via `clock_rate`),
`HR`/`EZ`/`DA` (via `parse_osu_file(text, mods=..., difficulty_adjust=...)`),
`HD`/`FL` (via `calculate(..., hidden=True, flashlight=True)`), and the
performance-only mods `NF`/`SO`/`AP`/`RX`/`BL`/`TC`/`TD`/`MG`/`DF` (via
`mods=frozenset({...})` passed to `calculate_pp`).

For scores with a known legacy total score (real submitted plays), pass
`legacy_total_score=` to `calculate_pp` for a more precise miss-count
estimate on combo-broken plays than the combo-based heuristic alone.

## Design notes

- Every mode is independently validated against real leaderboard scores;
  see `tests/` for the fixture beatmaps and expected values used to catch
  regressions.
- Graveyard/unranked/unusual beatmaps are supported the same as ranked
  ones — difficulty calculation here doesn't depend on a beatmap's ranked
  status.
- No mutable global state; every function takes its beatmap/attributes/
  judgements explicitly, so it's safe to call concurrently.

## License

MIT — see [LICENSE](LICENSE). See [NOTICE](NOTICE) for attribution.
