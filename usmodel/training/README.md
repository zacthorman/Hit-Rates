# How the NBA and NFL player models were built (21 October 2026)

The backtest behind `usmodel/` and `usmodel_live.py`, kept so the models can be
checked or retrained. Run in a scratch Linux box with LightGBM, pandas, pyarrow,
scipy and scikit-learn; paths inside point at `/home/claude/usbt` (raw SofaScore
JSON in `raw/`, tables in `data/`, exports in `export/`). The Mac needs none of
this to use the models.

The features are NOT here: they live in `usfeatures.py` at the repo root, shared
with the live scorer so the two cannot drift (the football model keeps the same
rule with `sim_test.py`).

Order of play:

1. Data: `backfill.py` (repo root, run on the Mac) fills `cache/` with whole
   seasons; the cached NBA / NFL schedules, box scores and line-ups are copied
   to `raw/`.
2. `rebuild.py nba|nfl`: `usfeatures.build` then `usfeatures.features`, written
   to `data/{sport}_*.parquet`. One row per player per game, strictly from
   earlier games: form (last 3/5/10/20, weighted, spread, minutes and volume),
   team and opponent style, Elo, what the opponent concedes to his position,
   missing regular team-mates, head to head, rest and back-to-backs.
3. `evaluate_us.py nba|nfl ablate`: feature groups added one at a time, kept on
   validation deviance. Splits: NFL train to Aug 2025, validation Sep to Nov
   2025, out of sample from Dec 2025 (incl. the 2026 season so far). NBA train
   to Jan 2026, validation Feb to Mar 2026, out of sample from Apr 2026.
4. `train_us.py nba|nfl`: per market, settings chosen on validation; a Poisson
   LightGBM model of the player's number as a multiple of his own weighted
   average (an offset, so stars are not pulled to the pack); the spread around
   it (negative binomial for counts, empirical ratio for yards), a Platt
   calibration and the blend with the site's own chance, all fitted on
   validation; the out-of-sample report; then a production refit on every game
   with a recency shift, exported to `usmodel/`.
5. `ppcheck_us.py nba|nfl`: the train-only models scored on Paddy Power's real
   settled lines from pplog/.
6. `simtest_us.py` (live features equal backtest features for games replayed as
   upcoming) and `parity_test.py` (numpy tree scorer equals LightGBM).

Scored at three lines per player-game built from his own earlier games (his
last-10 median, and 25-30% either side, the ladder rungs). Results: see
`results.md` beside this file.

## Audit (22 October 2026)

`audit_us.py` stress-tests the design: rolling-origin backtests (each season,
or each month on a one-season cache), the pipeline above rebuilt at every
origin, game-level bootstrap intervals, and the page's take rule against a
synthetic book. `audit_report.py` turns its output into tables. Results and
the verdict: `US-MODELS-AUDIT.md` at the repo root; how to run it on the
Mac's NBA cache is in its section 8.
