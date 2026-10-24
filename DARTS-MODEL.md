# Darts leg model

`darts_legs.py` is a darts model built from the chance of winning a leg: it covers the match markets and the four stat lines the site bets on. `darts_legs_backtest.py` checks it walk-forward against what is live now. This note sets out the evidence and the decision.

**Decision: not wired into live pricing.** On the cache, the new stat-line prices beat the record prices clearly and out of sample. On the settled darts bets, the bets the site actually put up, they do no better, and the interval is wide. The new leg ratings tie the live Elo on match markets. Neither part has shown it beats what is live on the bets that matter, so the live code is unchanged. What would change that is at the end.

## How darts is priced now

There are two separate systems.

1. **Stat lines, the whole settled record.** All 266 darts entries in `best_bets.json` (233 distinct selections, 190 settled, kick-offs 9 to 23 October 2026) are player stat lines: 180s, 3-dart average, highest checkout and 100+ checkouts (`markets.DARTS_STATS`). Each is priced off the player's own record in his recent matches across every PDC event: `model.price` falls back to `calibrate_record(smooth_rate(hits, n))`, and since darts has no entry in `RECORD_CALIBRATION` the chance is (hits + 0.5) / (n + 1). The price takes no account of the opponent or the format. A best-of-11-legs floor match and a first-to-10 major are priced off the same last 20, and the darts page itself warns about this (`report.py`, `mismatchWarning`).
2. **Match markets** (winner, total legs, handicap, correct score, match 180s) on the Match tab come from `darts_model.py`. That is a leg-level Elo (K 3 a leg, throw 0.5, gap shrunk by 0.8, new names at 1350), blended 75% towards Betfair where an exchange price exists (`darts_market.py`). None of these markets has been bet, so none is in the settled record.

## The new model

**Leg strength.** Each player has a leg strength (log-odds of winning a leg against an average tour player, with neither throwing first) and an uncertainty. A new name starts slightly below the tour with a wide uncertainty, so his first results move him a long way and a regular's move him very little. That is the shrinkage towards the tour average. The uncertainty grows while a player is away. A match is binomial on legs plus a night-form term (`tau2`) shared by every leg of that match, so a 6-0 counts as strong evidence but not as six independent pieces of it. Ratings are updated one match at a time in date order, with a Kalman step on the rating gap. In sets matches the legs come from the period scores, so they count as legs rather than sets.

**Match distribution.** The night's gap is uncertain, so the score is averaged over it with 7 Gauss-Hermite nodes. Each node is worked out exactly for the format: first to N legs, or first to S sets of first to L legs, with the throw alternating leg to leg and set to set and who throws first averaged out. The output is the full distribution of (sets or legs, legs won by each player). Winner, handicap, total legs and each player's legs won all come from it.

**Stat lines**, each mixed over that legs distribution:

| stat | model |
|---|---|
| 180s | rate per leg played over his last 20 matches with stats, gamma-shrunk to the tour rate (80 legs of prior); negative binomial (size 50) over the legs played |
| 100+ checkouts | rate per leg won, gamma-shrunk (25 legs won of prior); Poisson over his legs won |
| highest checkout | chance a leg he wins is finished above the line, beta-shrunk to the tour figure, then 1 − (1 − s)^W over his legs won W |
| 3-dart average | legs-weighted mean, lightly shrunk; normal with a spread of night (5.0) and legs (6.0 / √legs) |

Tour figures come only from matches before the one priced.

**Tuning.** The leg settings were fitted on matches before 1 January 2026 (575 scored matches), on winner log loss plus exact-score log loss. The stat settings were fitted on matches before 1 July 2026, the first months with enough statistics. Every figure below is on matches after those dates. Several settings ended at the edge of their grid after a second, wider pass: new-player level, highest-checkout prior (240, which means the tour figure all but decides it, so a player's own checkout record carries little signal) and the average prior (0.5, very little shrinkage). I stopped there rather than keep widening on a small tuning window.

## Data

* `cache_backtest.tar.zst`, unpacked: 3,565 darts matches (June 2018 to 18 October 2026, most from 2024 on). 819 have match statistics, 774 of them from 2026.
* `best_bets.json`: 190 settled darts selections, 146 of them on 41 matches in the cache that the new model can price.

The cache record is not exactly what the site quoted. On the 146 settled legs, the site's sample was usually 3 to 10 matches smaller than the 20 the backfilled cache now holds, and only 5 of the 146 match exactly. The cache comparison below therefore runs the record method on more data than it had live, which if anything favours the record.

All intervals are paired bootstrap 95% intervals on the difference in mean log loss (new minus current, so negative means the new model is better). They resample whole matches, because several lines on one match are not independent.

## Results

### Match markets: new leg ratings against the live Elo

1,461 matches from 1 January 2026, both players on 10 or more earlier matches.

| market | rows | log loss Elo | log loss new | new minus Elo (95%) | Brier Elo | Brier new | ECE Elo | ECE new |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| match winner | 1461 | 0.6504 | 0.6506 | +0.0002 (−0.0037 to +0.0038) | 0.2292 | 0.2293 | 0.025 | 0.040 |
| total legs over the middle line | 1397 | 0.6834 | 0.6821 | −0.0013 (−0.0035 to +0.0009) | 0.2452 | 0.2446 | 0.029 | 0.011 |
| first-listed player −1.5 legs | 1397 | 0.6593 | 0.6575 | −0.0019 (−0.0055 to +0.0016) | 0.2337 | 0.2329 | 0.024 | 0.022 |
| exact score (legs format) | 1397 | 2.4132 | 2.4091 | −0.0041 (−0.0093 to +0.0009) | | | | |

This is a tie. The new model is better calibrated on total legs: the Elo says 47% in its biggest band and 44% land, while the new model says 47% and 46% land. Every interval still crosses zero. The Elo's settings were tuned on all the data, this test period included, and it still holds level. A model that cannot beat it is no reason to change the Match tab, and the winner price there is 75% Betfair anyway wherever a price exists.

Match winner calibration (chance for the player listed first):

| stated | Elo n | said | landed | new n | said | landed |
|---|---:|---:|---:|---:|---:|---:|
| 10-20% | 10 | 0.166 | 0.200 | 4 | 0.184 | 0.250 |
| 20-30% | 53 | 0.256 | 0.245 | 31 | 0.261 | 0.129 |
| 30-40% | 133 | 0.357 | 0.346 | 130 | 0.358 | 0.338 |
| 40-50% | 272 | 0.453 | 0.426 | 295 | 0.454 | 0.414 |
| 50-60% | 399 | 0.551 | 0.589 | 468 | 0.551 | 0.605 |
| 60-70% | 372 | 0.643 | 0.629 | 397 | 0.642 | 0.622 |
| 70-80% | 195 | 0.738 | 0.708 | 122 | 0.734 | 0.779 |
| 80-90% | 25 | 0.827 | 0.800 | 13 | 0.832 | 0.769 |

Total legs over the middle line (9.5 in first to 6):

| stated | Elo n | said | landed | new n | said | landed |
|---|---:|---:|---:|---:|---:|---:|
| 30-40% | 20 | 0.384 | 0.350 | 28 | 0.378 | 0.357 |
| 40-50% | 757 | 0.474 | 0.437 | 1152 | 0.471 | 0.459 |
| 50-60% | 437 | 0.509 | 0.506 | 52 | 0.573 | 0.577 |
| 60-70% | 140 | 0.650 | 0.600 | 144 | 0.643 | 0.639 |
| 70-80% | 32 | 0.727 | 0.781 | 17 | 0.754 | 0.706 |

### Stat lines on the cache: new model against the record price

489 matches with statistics from 1 July 2026. Each row is one player with 10 or more earlier matches with stats, priced over a fixed ladder of lines (180s 0.5 to 5.5, 100+ checkouts 0.5 to 2.5, highest checkout 80.5 to 120.5, average 85.5 to 97.5), over side only. The under is the same bet turned round, so its log loss is identical.

| market | rows | log loss record | log loss new | new minus record (95%) | Brier record | Brier new | ECE record | ECE new |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| all four | 13851 | 0.5411 | 0.5170 | −0.0242 (−0.0317 to −0.0166) | 0.1815 | 0.1726 | 0.025 | 0.015 |
| 180s | 4374 | 0.4827 | 0.4432 | −0.0395 (−0.0535 to −0.0264) | 0.1569 | 0.1437 | 0.015 | 0.011 |
| 100+ checkouts | 2187 | 0.4160 | 0.3989 | −0.0171 (−0.0273 to −0.0078) | 0.1336 | 0.1283 | 0.027 | 0.020 |
| highest checkout | 3645 | 0.6691 | 0.6394 | −0.0297 (−0.0439 to −0.0155) | 0.2358 | 0.2238 | 0.042 | 0.017 |
| 3-dart average | 3645 | 0.5583 | 0.5539 | −0.0045 (−0.0135 to +0.0049) | 0.1854 | 0.1826 | 0.034 | 0.041 |
| lines the record puts at 25-75% | 7296 | 0.6615 | 0.6383 | −0.0232 (−0.0320 to −0.0148) | 0.2345 | 0.2239 | 0.021 | 0.015 |
| matches not first to 6 | 3116 | 0.5943 | 0.5556 | −0.0387 (−0.0652 to −0.0137) | 0.1998 | 0.1850 | 0.052 | 0.048 |

The gain is largest where the format matters. In 180s, a count that grows with the legs played, the improvement is about twice as large in matches that are not first to 6. The record cannot see that. The highest-checkout gain comes almost entirely from pooling, because one player's checkouts are too few to say much. The 3-dart average shows no reliable gain, and both prices are too confident above 80%.

Calibration, record against new:

180s

| stated | record n | said | landed | new n | said | landed |
|---|---:|---:|---:|---:|---:|---:|
| 0-10% | 722 | 0.048 | 0.069 | 872 | 0.054 | 0.053 |
| 10-20% | 620 | 0.148 | 0.169 | 570 | 0.148 | 0.156 |
| 20-30% | 491 | 0.240 | 0.240 | 402 | 0.243 | 0.269 |
| 30-40% | 364 | 0.340 | 0.357 | 378 | 0.352 | 0.336 |
| 40-50% | 276 | 0.434 | 0.413 | 313 | 0.445 | 0.444 |
| 50-60% | 365 | 0.543 | 0.523 | 274 | 0.548 | 0.529 |
| 60-70% | 298 | 0.658 | 0.661 | 366 | 0.652 | 0.689 |
| 70-80% | 367 | 0.756 | 0.741 | 287 | 0.751 | 0.746 |
| 80-90% | 432 | 0.856 | 0.840 | 441 | 0.865 | 0.871 |
| 90-100% | 439 | 0.951 | 0.941 | 471 | 0.942 | 0.953 |

100+ checkouts

| stated | record n | said | landed | new n | said | landed |
|---|---:|---:|---:|---:|---:|---:|
| 0-10% | 830 | 0.048 | 0.047 | 950 | 0.041 | 0.042 |
| 10-20% | 434 | 0.139 | 0.104 | 381 | 0.137 | 0.113 |
| 20-30% | 201 | 0.246 | 0.234 | 138 | 0.250 | 0.275 |
| 30-40% | 228 | 0.341 | 0.386 | 271 | 0.355 | 0.424 |
| 40-50% | 168 | 0.434 | 0.464 | 265 | 0.440 | 0.464 |
| 50-60% | 206 | 0.533 | 0.476 | 119 | 0.544 | 0.546 |
| 60-70% | 78 | 0.650 | 0.551 | 42 | 0.640 | 0.548 |
| 70-80% | 39 | 0.741 | 0.615 | 16 | 0.730 | 0.750 |

Highest checkout

| stated | record n | said | landed | new n | said | landed |
|---|---:|---:|---:|---:|---:|---:|
| 0-10% | 40 | 0.057 | 0.325 | 0 | - | - |
| 10-20% | 189 | 0.157 | 0.302 | 107 | 0.184 | 0.206 |
| 20-30% | 607 | 0.249 | 0.297 | 683 | 0.252 | 0.259 |
| 30-40% | 702 | 0.344 | 0.369 | 794 | 0.349 | 0.349 |
| 40-50% | 603 | 0.434 | 0.448 | 775 | 0.449 | 0.465 |
| 50-60% | 781 | 0.540 | 0.530 | 577 | 0.548 | 0.563 |
| 60-70% | 372 | 0.654 | 0.591 | 505 | 0.647 | 0.685 |
| 70-80% | 267 | 0.746 | 0.682 | 136 | 0.738 | 0.684 |
| 80-90% | 79 | 0.844 | 0.684 | 58 | 0.850 | 0.776 |

3-dart average

| stated | record n | said | landed | new n | said | landed |
|---|---:|---:|---:|---:|---:|---:|
| 0-10% | 60 | 0.061 | 0.133 | 46 | 0.069 | 0.152 |
| 10-20% | 176 | 0.150 | 0.261 | 228 | 0.155 | 0.197 |
| 20-30% | 263 | 0.243 | 0.285 | 293 | 0.253 | 0.334 |
| 30-40% | 330 | 0.342 | 0.355 | 282 | 0.350 | 0.333 |
| 40-50% | 250 | 0.434 | 0.448 | 328 | 0.452 | 0.479 |
| 50-60% | 468 | 0.546 | 0.551 | 322 | 0.548 | 0.534 |
| 60-70% | 375 | 0.653 | 0.611 | 355 | 0.653 | 0.637 |
| 70-80% | 409 | 0.757 | 0.756 | 405 | 0.750 | 0.701 |
| 80-90% | 603 | 0.853 | 0.819 | 564 | 0.855 | 0.809 |
| 90-100% | 711 | 0.950 | 0.889 | 822 | 0.951 | 0.901 |

### The settled darts record

190 distinct settled selections. They landed 66.3% against a stated 62.5%, so the record method was, if anything, slightly cautious on the bets it picked. 146 of them, on 41 matches, can be priced again by the new model as of kick-off. The record column is the price the site actually quoted (one over `fair`).

| market | rows | matches | log loss record | log loss new | new minus record (95%) | Brier record | Brier new | ECE record | ECE new |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| all settled | 146 | 41 | 0.6454 | 0.6486 | +0.0033 (−0.0499 to +0.0549) | 0.2268 | 0.2289 | 0.044 | 0.111 |
| 180s | 33 | 30 | 0.6689 | 0.6014 | −0.0675 (−0.1605 to +0.0234) | 0.2391 | 0.2080 | 0.111 | 0.079 |
| 100+ checkouts | 48 | 36 | 0.6043 | 0.6266 | +0.0224 (−0.0456 to +0.0836) | 0.2064 | 0.2180 | 0.125 | 0.192 |
| highest checkout | 27 | 26 | 0.6699 | 0.7013 | +0.0314 (−0.0901 to +0.1503) | 0.2385 | 0.2536 | 0.081 | 0.208 |
| 3-dart average | 38 | 35 | 0.6593 | 0.6799 | +0.0206 (−0.0576 to +0.0995) | 0.2338 | 0.2433 | 0.051 | 0.087 |

| stated | record n | said | landed | new n | said | landed |
|---|---:|---:|---:|---:|---:|---:|
| 20-30% | 2 | 0.261 | 0.500 | 0 | - | - |
| 30-40% | 1 | 0.318 | 1.000 | 8 | 0.366 | 0.375 |
| 40-50% | 5 | 0.476 | 0.400 | 39 | 0.461 | 0.667 |
| 50-60% | 48 | 0.553 | 0.583 | 56 | 0.538 | 0.625 |
| 60-70% | 65 | 0.649 | 0.692 | 33 | 0.646 | 0.697 |
| 70-80% | 23 | 0.722 | 0.739 | 8 | 0.727 | 0.875 |

No difference can be read from 146 legs on 41 matches: the interval runs from 5 points better to 5 points worse. The point estimate is slightly worse, and the new model is less well calibrated on these bets: it says 54% on average and 66% land. Only the 180s point the same way as the cache, and even there the interval crosses zero. Two cautions apply. The sample is two weeks of October, so one good night lifts many legs together. And the new model is pricing from the backfilled cache, which holds more history than the site had at the time, so it gets a small advantage here and still does not show a gain.

## Why it is not wired in

The brief was to wire it in only if it beats the current method out of sample. It does on the cache, for 180s, 100+ checkouts and highest checkout, with intervals clear of zero. It does not on the settled record. The settled record is the only test of the bets the site actually selects, and selection is where the two could differ: the record method picks lines where a player's recent record looks strong, and on those picks it landed slightly more often than it said. Changing live prices on the strength of the cache alone would mean trusting the wider test over the narrower one that matches what is bet. With 146 legs, the narrower test can neither confirm nor refute the cache result. On match markets the new ratings do not beat the Elo at all. So `weekend.py`, `model.py`, `report.py`, `darts_model.py` and `darts_market.py` are unchanged.

What would change the decision:

* **More settled darts legs.** At roughly the present spread, a real gain of 0.02 in log loss needs something like 500 to 1,000 settled legs before its interval clears zero. That is a few months of darts at the current rate. Re-running `python darts_legs_backtest.py --cache cache` against the growing `best_bets.json` answers it with no new code.
* **A narrower first step.** The 180s line is the case where the cache gain is largest (−0.040), the format effect is plainest, and the settled record agrees in direction (−0.068, n = 33). If anything goes live first, it should be the 180s price alone, behind the same check.

## Running it

```
mkdir -p /tmp/darts-cache && python - <<'EOF'
import tarfile, zstandard
with open("cache_backtest.tar.zst", "rb") as f:
    tarfile.open(fileobj=zstandard.ZstdDecompressor().stream_reader(f), mode="r|").extractall("/tmp/darts-cache", filter="data")
EOF
python darts_legs_backtest.py --cache /tmp/darts-cache          # every table above, about a minute
python darts_legs_backtest.py --cache /tmp/darts-cache --tune   # refit, about half an hour
python -m pytest tests/                                         # includes tests/test_darts_legs.py
```

The archive is about 80 MB and unpacks to about 1.1 GB, most of it other sports. `zstandard` is not in `requirements.txt`; `pip install zstandard`, or use `tar --zstd` where the `zstd` tool is installed.

`tests/test_darts_legs.py` uses synthetic tours only. It checks that distributions sum to one in both formats, that the sets and legs bookkeeping is consistent, that a longer format favours the stronger player, that gap uncertainty pulls prices towards evens, that there is no look-ahead in the ratings, that shrinkage behaves as described for newcomers and regulars, that more legs mean more 180s, that every stat chance is a probability falling with the line, that the record formula is the live one, and that on a tour generated by the model's own assumptions the model beats the record.
