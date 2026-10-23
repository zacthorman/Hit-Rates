# Hit Rates: a sports statistics projection model

A Python pipeline that pulls match-level statistics from a sports data API, builds each team's and player's form, projects upcoming fixtures with a count model, and tests every projection against what actually happened.

Built and maintained solo: around 39,000 lines of Python across 72 modules, rebuilt and published automatically every morning.

## How it works

- **Data pipeline.** Fetches match, lineup and player statistics from SofaScore and caches every response permanently, since finished matches never change. A new gameweek only fetches that week's games.
- **Model.** Projects count statistics (shots, corners, cards, tackles) with a Poisson distribution where variance matches the mean and a negative binomial where it is larger, which is normal for team shots. Adjusts for opponent strength through shared opponents.
- **Backtest.** Replays past fixtures using only data available before kick-off, then settles them against real results.
- **Calibration.** Compares what the model said (for example 60%) with how often it actually happened, fits how far raw records should be pulled towards 50%, and feeds that back into future projections.
- **Player and team models.** Backtested gradient-boosted models price football player lines (`fmodel_live.py`), NBA and NFL player lines (`usmodel_live.py`) and football team lines (`teamstyle.py`, `teammodel_train.py`), each scored only on matches it never trained on.
- **Prices and records.** Betfair Exchange, Paddy Power and Bet365 prices sit beside the model's own, and every line is logged before kick-off and settled afterwards, so the record is kept honestly.
- **Output.** Self-contained HTML reports, one per competition, a front page, and `tonight.html` with the case for each fixture, published to GitHub Pages. Covers football, NFL, NBA, MLB and darts.

## What testing found

- **The test itself was wrong first.** 1,093 of 3,778 historical predictions came from the wrong competition, and the backtest was measuring a different form window from the live model. Aligning the two moved the measured calibration gap from 8.2 to 5.8 points.
- **Requiring fewer shared opponents** between two teams raised model coverage from 75% to 91%.
- **The lesson kept:** a backtest that measures something other than production is worse than no backtest, because it gets believed.

Full write-up in [FINDINGS.md](FINDINGS.md).

**Tech:** Python, HTML/JavaScript report generator, GitHub Pages, scheduled with macOS launchd.

## What runs when

| When | What |
|---|---|
| Every day at 07:00 | `update.py`: settle yesterday, build every league with `run.py`, re-render, index, commit, then `publish.sh` (prices, models, logs, `tonight.html`, push to `gh-pages`), then `tactics_fetch.py` |
| Every 15 minutes | `lineups_auto.py`: confirmed line-ups an hour before kick-off, then a republish |
| Mondays at 05:34 | `teammodel_train.py --weekly`: a small, checked update of the team model |
| Weekly, by hand | `gs_backtest.py build` and `test`, refitting the game state |
| When needed | `darts.sh`, `nfl_fit.sh`, `catchup.sh`, the backfills and the probes |

Every script, grouped by job, is listed in [USAGE.md](USAGE.md#the-files).

## Code health

On 22 October the duplicated probability helpers were gathered into `probability.py`, the report-reading code into `pagedata.py`, dead code was removed and the slowest steps of the daily build were sped up, without changing the output: every page and file the build writes is byte-for-byte identical apart from its build timestamps. `replay_build.py` replays the whole build from the cache with a frozen clock so that claim can be checked. Details and timings: [CODE-HEALTH.md](CODE-HEALTH.md).

**Running it:** see [USAGE.md](USAGE.md).
