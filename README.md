# Hit Rates: a sports statistics projection model

A Python pipeline that pulls match-level statistics from a sports data API, builds each team's and player's form, projects upcoming fixtures with a count model, and tests every projection against what actually happened.

Built and maintained solo: around 21,000 lines of Python across 33 modules, rebuilt and published automatically each gameweek.

## How it works

- **Data pipeline.** Fetches match, lineup and player statistics from SofaScore and caches every response permanently, since finished matches never change. A new gameweek only fetches that week's games.
- **Model.** Projects count statistics (shots, corners, cards, tackles) with a Poisson distribution where variance matches the mean and a negative binomial where it is larger, which is normal for team shots. Adjusts for opponent strength through shared opponents.
- **Backtest.** Replays past fixtures using only data available before kick-off, then settles them against real results.
- **Calibration.** Compares what the model said (for example 60%) with how often it actually happened, fits how far raw records should be pulled towards 50%, and feeds that back into future projections.
- **Output.** Self-contained HTML reports, one per competition, published to GitHub Pages. Covers football, NFL and darts.

## What testing found

- **The test itself was wrong first.** 1,093 of 3,778 historical predictions came from the wrong competition, and the backtest was measuring a different form window from the live model. Aligning the two moved the measured calibration gap from 8.2 to 5.8 points.
- **Requiring fewer shared opponents** between two teams raised model coverage from 75% to 91%.
- **The lesson kept:** a backtest that measures something other than production is worse than no backtest, because it gets believed.

Full write-up in [FINDINGS.md](FINDINGS.md).

**Tech:** Python, HTML/JavaScript report generator, GitHub Pages, scheduled with macOS launchd.

**Running it:** see [USAGE.md](USAGE.md).
