# The case: predicted score and home, draw and away chances, backtested

Written 22 October 2026. Everything here comes from `case_score_backtest.py`,
which replays the cache walk-forward and makes no requests. The tables below
are its output, unedited; `python case_score_backtest.py --report` prints them
again from `case_score_results.json`.

## Verdict

The predicted score and 1X2 chances The case has been printing were never
tested. Tested now, over 3,595 matches in four walk-forward windows, they were
clearly better than base rates and clearly worse than a plain model of each
club's attack and defence fitted on every result in the cache.

* **Adopted: independent Poisson with fitted attack and defence ratings.**
  Against the method as built it improves the ranked probability score from
  0.2153 to 0.2101 and log loss from 1.0364 to 1.0134. Both 95% intervals
  on the paired difference sit wholly below zero, and it was better on both
  measures in every one of the four windows. It also forecasts the 290 test
  matches (7.5%) the current method had nothing for. It is now wired into
  `context.score()`.
* **Dixon-Coles and the bivariate Poisson added nothing worth having.** The
  fitted low-score correction rho was small (-0.017 to -0.047) and moved the
  fourth decimal; the bivariate model's shared component lambda3 fitted to its
  floor of 0.0001 in every window, so it is the independent model under
  another name. Dixon-Coles was a hair ahead on the test windows (RPS 0.2099
  against 0.2101) but a hair behind on the training-only validation data
  (1.0005 against 0.9996), so the choice between them was made on the
  validation data, as it must be, and the simpler model won.
* **Independent Poisson from the existing Elo ratings** (strength.py's gap
  plus the competition's scoring level) also beat the current method, by
  less: 0.2116 and 1.0185.
* **The exact score is the weak part, and no model fixed it.** Every method
  calls the exact score about one time in ten (9.7% now, 10.0% adopted).
  Always saying 1-1 does better, at 11.6%, and so does each model's single
  likeliest score (11.0% to 12.4%). The reason is the page's pick rule, which
  takes the likeliest result first and then the likeliest score within it:
  the draw is almost never the single likeliest result, so the page called a
  draw 1.2% of the time against 25.1% draws played. That rule was chosen on
  purpose (a call of 1-1 every week says nothing about the game) and this
  change keeps it, but it should be read as a lean, not a forecast, and the
  page should not be judged on its exact-score hits.
* **Against the bookmaker, no conclusion is possible.** Betfair match odds are
  only on disk for 83 test matches (snapshots from 17 to 19 October in the
  history of `market_prices.json`). On those the adopted model scored better
  than Betfair's implied chances on RPS and log loss, and Betfair called more
  results correctly. Eighty-three matches is far too few to separate two
  forecasts this close, and an exchange beating or losing to a ratings model
  over one weekend is noise. The honest reading is that the model is in the
  same neighbourhood as the market, not that it beats it.

## How it was tested

* **Matches.** Every competitive (non-friendly) men's match in the cache with
  a full-time score where both clubs have their own match pages cached, which
  is what a report fixture has: 9,713 of 17,518. Results are the 90-minute
  score, which is what a 1X2 settles on.
* **Walk-forward.** The last 40% of those dates (3,885 matches, 25 September
  2025 to 19 October 2026) were cut into four windows of equal count. The
  current method could forecast 3,595 of them; every comparison of methods is
  on those 3,595 unless the table says otherwise.
* **No look-ahead.** Each forecast uses only matches before the UTC day of
  kick-off. The team-rating models were refitted weekly on matches before the
  start of that week.
* **Tuning on training only.** Half-life (how fast old results fade) and ridge
  (how hard a club seen rarely is pulled to average) were chosen per window on
  the 60 days before it opened, fitted on everything before those 60 days.
  Rho and lambda3 are fitted by maximum likelihood as part of each fit.
* **The current method was run, not rewritten.** `context.legacy_score()`,
  which is the whole of the old `context.score()`, was called on an entry
  built the way `run.py` builds one: the goals projection from
  `hitrates.league_ratings` and `project_fixture` for league fixtures (last 38
  in the competition, with the same refit when neither club is in the table),
  and for the Champions League, Europa League and Nations League no
  projection, so the page falls back to recent xG with the Elo re-split
  exactly as it does live.
* **Scores.** Exact score is the page's pick (likeliest result, then likeliest
  score within it) and, as a check, the single likeliest score. Score log loss
  is the log loss of the actual scoreline under each model's score grid.
  Outcome accuracy is how often the likeliest of home, draw and away happened.
  Ranked probability score, Brier and log loss are on the three outcomes.
  Lower is better for all three. Base rates are the home, draw and away shares
  of eligible matches in the year before each window, with 1-1, the commonest
  score, as the call.

## Results

### Windows

| Window | From | To | Test matches | Current method forecasts |
|---|---|---|---|---|
| 1 | 2025-09-25 | 2025-12-14 | 972 | 835 |
| 2 | 2025-12-14 | 2026-03-18 | 972 | 904 |
| 3 | 2026-03-18 | 2026-08-15 | 972 | 923 |
| 4 | 2026-08-15 | 2026-10-19 | 969 | 933 |

### All test matches with every model (3595 matches)

| Method | Exact score (page pick) | Exact score (modal) | Score log loss | Outcome accuracy | RPS | Brier | Log loss |
|---|---|---|---|---|---|---|---|
| Current (The case as built) | 9.7% | 11.0% | 3.0490 | 48.8% | 0.2153 | 0.6186 | 1.0364 |
| Independent Poisson (fitted attack and defence) | 10.0% | 12.1% | 2.9732 | 50.1% | 0.2101 | 0.6067 | 1.0134 |
| Dixon-Coles | 9.9% | 11.9% | 2.9724 | 50.2% | 0.2099 | 0.6064 | 1.0128 |
| Bivariate Poisson | 10.1% | 12.2% | 2.9732 | 50.1% | 0.2101 | 0.6067 | 1.0134 |
| Independent Poisson (existing Elo ratings) | 10.1% | 12.4% | 2.9813 | 49.4% | 0.2116 | 0.6102 | 1.0185 |
| Elo 1X2 (strength.py, reference) |  |  |  | 49.7% | 0.2118 | 0.6138 | 1.0294 |
| Base rates | 11.6% | 11.6% |  | 45.0% | 0.2288 | 0.6459 | 1.0685 |
| Shipped constants (hindsight check) | 10.1% | 12.2% | 2.9738 | 49.8% | 0.2102 | 0.6070 | 1.0139 |

### Report competitions only (3274 matches)

| Method | Exact score (page pick) | Exact score (modal) | Score log loss | Outcome accuracy | RPS | Brier | Log loss |
|---|---|---|---|---|---|---|---|
| Current (The case as built) | 9.7% | 10.8% | 3.0330 | 48.6% | 0.2162 | 0.6215 | 1.0377 |
| Independent Poisson (fitted attack and defence) | 10.2% | 12.1% | 2.9643 | 49.8% | 0.2114 | 0.6106 | 1.0191 |
| Dixon-Coles | 10.0% | 11.8% | 2.9635 | 49.8% | 0.2113 | 0.6103 | 1.0187 |
| Bivariate Poisson | 10.2% | 12.1% | 2.9642 | 49.8% | 0.2114 | 0.6106 | 1.0191 |
| Independent Poisson (existing Elo ratings) | 10.3% | 12.4% | 2.9733 | 49.2% | 0.2128 | 0.6139 | 1.0241 |
| Elo 1X2 (strength.py, reference) |  |  |  | 49.5% | 0.2129 | 0.6172 | 1.0341 |
| Base rates | 11.5% | 11.5% |  | 45.2% | 0.2281 | 0.6455 | 1.0680 |
| Shipped constants (hindsight check) | 10.2% | 12.2% | 2.9658 | 49.5% | 0.2116 | 0.6112 | 1.0201 |

### Paired difference against the current method (negative is better)

| Method | n | RPS diff | 95% interval | Log loss diff | 95% interval | Windows better on both |
|---|---|---|---|---|---|---|
| Independent Poisson (fitted attack and defence) | 3595 | -0.0053 | -0.0080 to -0.0025 | -0.0231 | -0.0342 to -0.0119 | 4 of 4 |
| Dixon-Coles | 3595 | -0.0054 | -0.0081 to -0.0027 | -0.0236 | -0.0346 to -0.0126 | 4 of 4 |
| Bivariate Poisson | 3595 | -0.0053 | -0.0080 to -0.0025 | -0.0231 | -0.0342 to -0.0119 | 4 of 4 |
| Independent Poisson (existing Elo ratings) | 3595 | -0.0037 | -0.0063 to -0.0012 | -0.0179 | -0.0287 to -0.0072 | 4 of 4 |
| Elo 1X2 (strength.py, reference) | 3595 | -0.0035 | -0.0060 to -0.0009 | -0.0070 | -0.0191 to +0.0050 | 3 of 4 |
| Base rates | 3595 | +0.0135 | +0.0089 to +0.0182 | +0.0321 | +0.0159 to +0.0482 | 0 of 4 |
| Shipped constants (hindsight check) | 3595 | -0.0051 | -0.0079 to -0.0024 | -0.0226 | -0.0338 to -0.0114 | 4 of 4 |

### By window (RPS / log loss)

| Window | n | Current (The case as built) | Independent Poisson (fitted attack and defence) | Dixon-Coles | Bivariate Poisson | Independent Poisson (existing Elo ratings) | Base rates |
|---|---|---|---|---|---|---|---|
| 1 | 835 | 0.2070 / 0.9937 | 0.2054 / 0.9851 | 0.2052 / 0.9851 | 0.2054 / 0.9851 | 0.2051 / 0.9823 | 0.2264 / 1.0442 |
| 2 | 904 | 0.2204 / 1.0675 | 0.2118 / 1.0242 | 0.2114 / 1.0233 | 0.2118 / 1.0242 | 0.2155 / 1.0377 | 0.2309 / 1.0813 |
| 3 | 923 | 0.2240 / 1.0697 | 0.2181 / 1.0474 | 0.2180 / 1.0468 | 0.2181 / 1.0474 | 0.2204 / 1.0552 | 0.2269 / 1.0753 |
| 4 | 933 | 0.2093 / 1.0117 | 0.2046 / 0.9945 | 0.2046 / 0.9940 | 0.2046 / 0.9945 | 0.2050 / 0.9960 | 0.2309 / 1.0711 |

### By the current method's source

| Source | n | Current RPS | Adopted model RPS | Current log loss | Adopted model log loss |
|---|---|---|---|---|---|
| Elo for the result, recent xG for the goals (untested) | 806 | 0.1998 | 0.1989 | 0.9775 | 0.9610 |
| goals projection | 2789 | 0.2198 | 0.2134 | 1.0535 | 1.0292 |

### Draws: mean forecast against what happened

| Method | Mean home | Mean draw | Mean away | Draw called (page pick) |
|---|---|---|---|---|
| Actual | 45.0% | 25.1% | 29.9% | 25.1% |
| Current (The case as built) | 45.5% | 22.9% | 31.6% | 1.2% |
| Independent Poisson (fitted attack and defence) | 44.3% | 23.9% | 31.9% | 0.1% |
| Dixon-Coles | 43.9% | 24.6% | 31.5% | 0.3% |
| Bivariate Poisson | 44.3% | 23.9% | 31.9% | 0.1% |
| Independent Poisson (existing Elo ratings) | 44.3% | 22.9% | 32.8% | 0.0% |
| Elo 1X2 (strength.py, reference) | 47.4% | 20.2% | 32.4% |  |

### Against Betfair's implied chances (83 matches)

Betfair's exact score is the same pick rule run on its correct-score market, which only 2 of these matches had.

| Method | Exact score (page pick) | Outcome accuracy | RPS | Brier | Log loss |
|---|---|---|---|---|---|
| Betfair implied | 0.0% | 57.8% | 0.2001 | 0.5863 | 0.9804 |
| Current (The case as built) | 10.8% | 53.0% | 0.2075 | 0.5940 | 0.9959 |
| Independent Poisson (fitted attack and defence) | 13.3% | 55.4% | 0.1959 | 0.5733 | 0.9660 |
| Dixon-Coles | 10.8% | 55.4% | 0.1959 | 0.5734 | 0.9657 |
| Bivariate Poisson | 13.3% | 55.4% | 0.1959 | 0.5733 | 0.9661 |
| Independent Poisson (existing Elo ratings) | 10.8% | 50.6% | 0.1980 | 0.5787 | 0.9733 |
| Base rates | 10.8% | 37.3% | 0.2425 | 0.6678 | 1.0973 |

### Test matches the current method cannot forecast (290 matches)

| Method | Exact score (page pick) | Exact score (modal) | Score log loss | Outcome accuracy | RPS | Brier | Log loss |
|---|---|---|---|---|---|---|---|
| Independent Poisson (fitted attack and defence) | 12.8% | 12.8% | 2.8530 | 54.8% | 0.2034 | 0.5818 | 0.9799 |
| Dixon-Coles | 12.4% | 12.1% | 2.8558 | 54.1% | 0.2036 | 0.5824 | 0.9807 |
| Bivariate Poisson | 12.8% | 12.8% | 2.8528 | 54.8% | 0.2034 | 0.5817 | 0.9799 |
| Independent Poisson (existing Elo ratings) | 10.3% | 12.4% | 2.8604 | 51.0% | 0.2094 | 0.5911 | 0.9944 |
| Base rates | 11.7% | 11.7% |  | 46.9% | 0.2305 | 0.6371 | 1.0552 |

### Tuning (chosen on the 60 days before each window)

| Window | Model | Half-life (days) | Ridge | Validation matches | Home edge | rho | lambda3 | Teams |
|---|---|---|---|---|---|---|---|---|
| 1 | Independent Poisson (fitted attack and defence) | 1460 | 0.1 | 529 | 0.213 | +0.000 | 0.0000 | 1158 |
| 1 | Dixon-Coles | 730 | 0.1 | 529 | 0.212 | -0.047 | 0.0000 | 1158 |
| 1 | Bivariate Poisson | 1460 | 0.1 | 529 | 0.213 | +0.000 | 0.0002 | 1158 |
| 2 | Independent Poisson (fitted attack and defence) | 1460 | 2.0 | 711 | 0.213 | +0.000 | 0.0000 | 1262 |
| 2 | Dixon-Coles | 365 | 2.0 | 711 | 0.212 | -0.017 | 0.0000 | 1262 |
| 2 | Bivariate Poisson | 1460 | 2.0 | 711 | 0.213 | +0.000 | 0.0001 | 1262 |
| 3 | Independent Poisson (fitted attack and defence) | 365 | 2.0 | 725 | 0.212 | +0.000 | 0.0000 | 1347 |
| 3 | Dixon-Coles | 365 | 2.0 | 725 | 0.212 | -0.020 | 0.0000 | 1347 |
| 3 | Bivariate Poisson | 365 | 2.0 | 725 | 0.212 | +0.000 | 0.0001 | 1347 |
| 4 | Independent Poisson (fitted attack and defence) | 1460 | 0.1 | 146 | 0.222 | +0.000 | 0.0000 | 1429 |
| 4 | Dixon-Coles | 1460 | 0.1 | 146 | 0.222 | -0.042 | 0.0000 | 1429 |
| 4 | Bivariate Poisson | 1460 | 0.1 | 146 | 0.222 | +0.000 | 0.0001 | 1429 |

### Validation log loss pooled over the four tuning periods (training data only)

| Model | Best half-life | Best ridge | Pooled validation log loss |
|---|---|---|---|
| Independent Poisson (fitted attack and defence) | 1460 | 2.0 | 0.9996 |
| Dixon-Coles | 1460 | 2.0 | 1.0005 |
| Bivariate Poisson | 1460 | 2.0 | 0.9996 |


## What to keep in mind

* **Known leak in the Elo constants.** strength.py's K factors and home edge
  were tuned once on the whole cache, so they saw the test period. Ratings are
  still as of kick-off. It touches the current method's xG and Elo route and
  the Elo-Poisson model, which flatters both slightly; it does not touch the
  adopted model.
* **The shipped constants were picked with hindsight.** `context.py` uses a
  half-life of 1,460 days and a ridge of 2.0, the best pooled validation
  setting across the four windows' training data, so windows 1 to 3 did not
  have it available at the time. The "Shipped constants" row shows that
  setting scored 0.2102 and 1.0139, the same as the per-window tuned model to
  three decimals, so nothing rests on the choice.
* **The half-life sits at the top of the grid.** With results older than
  1,100 days dropped, a 1,460-day half-life means near-equal weight on three
  years. Recent form did not earn extra weight on this data.
* **Approximations of `run.py`.** A competition's clubs are taken as the paged
  clubs who played in it in the previous 240 days, where `run.py` reads the
  live table, and each club's history is every cached match it appears in,
  where `run.py` reads its own two pages. Both touch only the current
  method's inputs, and both are close for the leagues the site covers, where
  every club in the table has its pages cached.
* **Window 4's tuning period was thin.** The 60 days before 15 August held
  only 146 eligible matches (summer). It still chose the same half-life as
  the pooled best, and a lighter ridge (0.1 against 2.0).
* **Where the old method lost most.** On league fixtures with a goals
  projection, log loss 1.0535 against 1.0292. On European and Nations League
  nights, where it used recent xG and the Elo re-split, it was much closer
  (0.9775 against 0.9610). The projection is fitted on one season's
  in-competition games per club, the adopted model on every result for three
  years, cups and Europe included.

* **Played fixtures re-rendered later.** The live model is fitted once per
  process on every result on disk, so a report rebuilt after a match has been
  played includes that match in its own forecast. Forecasts made before
  kick-off, which is what the page is for, are unaffected.

## What changed

* `scoremodels.py` (new): score grids, the four models and the scoring rules.
  Nothing in it reads the cache.
* `case_score_backtest.py` (new): the walk-forward harness and every table
  here.
* `context.py`: `score()` now uses the fitted model (`_model_score`), fitted
  once per process on every competitive result in the cache
  (`score_matches`). The old route is kept as `legacy_score()` and is used
  only when the model has never seen one of the clubs or cannot be fitted.
  The returned fields are unchanged; the source reads "team attack and
  defence ratings (backtested)". The fit needs scipy, now in
  `requirements.txt`; without it the page falls back to the old route, which
  the source line will show.
* Tests: `tests/test_scoremodels.py`, `tests/test_case_score_backtest.py`, and
  three new cases in `tests/test_context.py` for the model route and both
  fallbacks.

## Reproducing

```
python case_score_backtest.py                       # about eight minutes
mkdir -p /tmp/mp && for c in f252396 9d74056 21e22b4; do git show $c:market_prices.json > /tmp/mp/$c.json; done
python case_score_backtest.py --snapshots /tmp/mp   # with the Betfair rows
python case_score_backtest.py --report              # tables from the saved run
```

The cache used was `cache_backtest.tar.zst` unpacked into `cache/` (20,652
finished matches, the last on 19 October 2026).
