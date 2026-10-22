# Team lines: the backtest

Generated 2026-10-22T12:38:15+00:00 by `teamline_backtest.py` from the cached matches (13576 side rows, test matches 2026-01-01 to 2026-10-19). The gate it writes, `teamlines_gate.json`, is what `teamlines.py` reads for the pages and for `teamlog.py`. Rerun it after the cache grows; this file is rewritten each time.

## Summary

2 of 7 team-line markets passed: corners (one side), take from an edge of 5.0%; shots on target (one side), take from an edge of 5.0%. Every other market stays as it has been since 21 October: acceptable at most, never a take. Three findings matter more than the verdicts:

1. **The page's own record price is worse than knowing nothing about the teams.** On every market the last-10 average through `probOver()` and `calibrate()` scores a worse log loss than the plain base rate, and its calibration slope is 1.3 to 1.6: underconfident, so it flattens real differences. That is how the page has priced a team line with no projection, and what the cross-league odds scaling behind the 26 takes started from.
2. **The team model beats the record on every market**, and the base rate on every market but corners (match total), where it adds nothing over the base rate. The intervals are below.
3. **Being better on average is not the same as beating a price.** Pooled over the five markets the proxy book can test, the 12044 lines the model would have called a take at a 5% edge were said to land 66.2% of the time and landed 62.1%, and claimed an edge of 11.8% a line for a return of 4.8%. Lines picked for disagreeing with a price are where the model's errors gather. Market by market and period by period, the gap ran from 3 points the right way to 12 points short.

## Why

On 21 Oct 2026, 26 of the 30 takes on the European pages were team lines (corners, cards, fouls, shots on target) with no evidence behind them, so the page stopped calling any team line a take. This is the evidence, market by market.

## Method

- **Walk forward.** For every month from January 2026 the team model is fitted again on every match before that month, the way `teammodel_train.py` fits it (LightGBM on the `teamstyle.py` features or the linear game state fit, whichever `teammodel/meta.json` chose for the stat; shots use the linear fit, the rest LightGBM), and scored on that month only. Nothing a prediction uses comes from on or after its kick-off. Spreads are fitted as the trainer fits them, on the training matches.
- **Markets.** The ones Paddy Power prices: each side's corners and cards (over and under), the match corners and cards (over and under), and each side's fouls, shots on target and shots ("N or more", overs only). Cards are yellow cards, the count `teamlog.py` settles on; a match with no card row in the feed is settled as none.
- **Lines.** Each side (and each match) is priced at five lines: floor(own last-10 average) + 0.5, and one and two either side. Over and under at one line are the same event, so each line is scored once.
- **Four prices for the same line.** *base*: how often the line landed across all training matches, ignoring who is playing. *record*: the page's fallback, the last-10 average through `probOver()` and `calibrate()`. *linear*: the game state fit. *model*: the team model as deployed.
- **Scores.** Log loss and Brier, lower is better. Differences carry 95% intervals from resampling whole matches (1000 draws), because the lines of one match are not independent.
- **Calibration.** The slope of the logistic regression of the result on logit(chance): 1 is right, below 1 overconfident, above 1 underconfident.
- **The proxy book.** No Paddy Power team prices were kept for finished matches (the team log starts now), so every line is priced by a stand-in: the linear game state fit, which knows each side's average, what the opponent concedes, home and the ball, and no more than any bookmaker knows, with a 9% overround split in proportion. A take is a line we call 50% or more where our chance times that price beats 1 by at least the threshold *t* and by no more than the page's 30% cap.
- **The threshold**, chosen on January to May only: the smallest *t* from 5% to 30% (steps of 2.5%) whose takes paid against the proxy book, with 200 or more takes and the 90% lower bound of the return per line at or above zero.
- **Confirmation**, June to October, never seen while choosing *t*: 50 or more takes and a return at or above zero.
- **Pass** needs all of: better than both base and record on log loss and on Brier (interval wholly below zero), slope 0.8 to 1.25, a threshold found, and the threshold holding on the later months.
- **Betfair.** Exchange prices were logged for match corners and match cards on 9 October games (`exchange_log.json`). They are scored below and decide nothing.

## Results by market

Every held-out line, January 2026 to the latest cached match.

| Market | Lines | Matches | Model | Log loss: base | record | linear | LightGBM | model | Brier: base | record | model | Slope | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| corners (one side) | 31156 | 3117 | gbm | 0.6042 | 0.6355 | 0.5786 | 0.5766 | 0.5766 | 0.2079 | 0.2222 | 0.1962 | 0.87 | pass |
| corners (match total) | 15585 | 3117 | gbm | 0.6009 | 0.6607 | 0.5985 | 0.6000 | 0.6000 | 0.2071 | 0.2341 | 0.2068 | 0.85 | fail |
| cards (one side) | 27904 | 3100 | gbm | 0.4881 | 0.5294 | 0.4798 | 0.4785 | 0.4785 | 0.1593 | 0.1743 | 0.1558 | 1.05 | fail |
| cards (match total) | 15482 | 3100 | gbm | 0.5601 | 0.5913 | 0.5530 | 0.5511 | 0.5511 | 0.1892 | 0.2017 | 0.1855 | 0.94 | fail |
| fouls (one side) | 31140 | 3114 | gbm | 0.6572 | 0.6599 | 0.6179 | 0.6164 | 0.6164 | 0.2311 | 0.2337 | 0.2138 | 0.94 | fail |
| shots on target (one side) | 31127 | 3117 | gbm | 0.6001 | 0.6134 | 0.5669 | 0.5596 | 0.5596 | 0.2052 | 0.2119 | 0.1893 | 0.90 | pass |
| shots (one side) | 30910 | 3091 | linear | 0.6728 | 0.6781 | 0.6110 | 0.6115 | 0.6110 | 0.2376 | 0.2426 | 0.2115 | 0.95 | fail |

### Model against the baselines

Model minus baseline, mean per line, with the 95% interval. Negative is the model better.

| Market | Log loss vs base | Log loss vs record | Brier vs base | Brier vs record |
|---|---|---|---|---|
| corners (one side) | -0.0276 (-0.0327 to -0.0220) | -0.0589 (-0.0658 to -0.0516) | -0.0116 (-0.0136 to -0.0095) | -0.0259 (-0.0287 to -0.0231) |
| corners (match total) | -0.0009 (-0.0045 to +0.0025) | -0.0607 (-0.0723 to -0.0488) | -0.0003 (-0.0018 to +0.0011) | -0.0273 (-0.0320 to -0.0224) |
| cards (one side) | -0.0095 (-0.0121 to -0.0069) | -0.0509 (-0.0551 to -0.0462) | -0.0035 (-0.0044 to -0.0026) | -0.0186 (-0.0202 to -0.0169) |
| cards (match total) | -0.0089 (-0.0131 to -0.0049) | -0.0402 (-0.0471 to -0.0329) | -0.0037 (-0.0054 to -0.0021) | -0.0162 (-0.0189 to -0.0133) |
| fouls (one side) | -0.0408 (-0.0464 to -0.0350) | -0.0436 (-0.0496 to -0.0374) | -0.0173 (-0.0197 to -0.0147) | -0.0199 (-0.0225 to -0.0172) |
| shots on target (one side) | -0.0406 (-0.0465 to -0.0346) | -0.0538 (-0.0604 to -0.0477) | -0.0160 (-0.0183 to -0.0137) | -0.0227 (-0.0252 to -0.0203) |
| shots (one side) | -0.0618 (-0.0708 to -0.0531) | -0.0671 (-0.0750 to -0.0583) | -0.0261 (-0.0300 to -0.0225) | -0.0310 (-0.0344 to -0.0273) |

### Calibration

| Market | Model intercept | Model slope | Record slope | Mean chance | Landed |
|---|---|---|---|---|---|
| corners (one side) | -0.031 | 0.868 | 1.397 | 45.5% | 45.3% |
| corners (match total) | +0.020 | 0.849 | 1.483 | 45.9% | 46.8% |
| cards (one side) | +0.028 | 1.046 | 1.573 | 42.8% | 43.1% |
| cards (match total) | -0.010 | 0.937 | 1.581 | 48.2% | 48.2% |
| fouls (one side) | -0.010 | 0.944 | 1.568 | 48.2% | 48.0% |
| shots on target (one side) | +0.025 | 0.897 | 1.488 | 46.3% | 47.1% |
| shots (one side) | +0.047 | 0.954 | 1.338 | 45.6% | 46.7% |

Said against got, the model, every held-out line, in bands of 10 points (30 or more lines):

- **corners (one side)**: 7% said, 10% got (n 1837); 15% said, 18% got (n 4014); 25% said, 28% got (n 4410); 35% said, 35% got (n 4036); 45% said, 44% got (n 3867); 55% said, 53% got (n 3394); 65% said, 63% got (n 3128); 75% said, 73% got (n 2957); 85% said, 81% got (n 2320); 93% said, 92% got (n 1193)
- **corners (match total)**: 7% said, 10% got (n 692); 15% said, 20% got (n 1688); 25% said, 29% got (n 2154); 35% said, 38% got (n 2254); 45% said, 46% got (n 2195); 55% said, 55% got (n 1979); 65% said, 63% got (n 1759); 75% said, 71% got (n 1467); 84% said, 82% got (n 1037); 93% said, 91% got (n 360)
- **cards (one side)**: 6% said, 6% got (n 3986); 14% said, 13% got (n 4914); 25% said, 24% got (n 2913); 35% said, 34% got (n 3050); 45% said, 47% got (n 1461); 56% said, 57% got (n 2728); 64% said, 66% got (n 2485); 75% said, 75% got (n 829); 86% said, 87% got (n 4792); 91% said, 93% got (n 746)
- **cards (match total)**: 8% said, 8% got (n 666); 15% said, 17% got (n 2218); 25% said, 25% got (n 2003); 35% said, 36% got (n 1940); 45% said, 44% got (n 1404); 55% said, 55% got (n 1774); 65% said, 65% got (n 1258); 75% said, 73% got (n 1897); 86% said, 84% got (n 1389); 93% said, 91% got (n 933)
- **fouls (one side)**: 8% said, 10% got (n 231); 16% said, 17% got (n 2092); 25% said, 26% got (n 4290); 35% said, 36% got (n 5096); 45% said, 46% got (n 5162); 55% said, 55% got (n 4912); 65% said, 64% got (n 4369); 75% said, 73% got (n 3162); 84% said, 82% got (n 1548); 93% said, 91% got (n 278)
- **shots on target (one side)**: 7% said, 9% got (n 2082); 15% said, 18% got (n 4203); 25% said, 27% got (n 4127); 35% said, 37% got (n 3782); 45% said, 46% got (n 3332); 55% said, 54% got (n 3230); 65% said, 65% got (n 3068); 75% said, 73% got (n 2996); 85% said, 83% got (n 2763); 94% said, 92% got (n 1544)
- **shots (one side)**: 7% said, 10% got (n 679); 16% said, 18% got (n 2765); 25% said, 28% got (n 4313); 35% said, 36% got (n 5018); 45% said, 45% got (n 5176); 55% said, 56% got (n 4927); 65% said, 65% got (n 3994); 75% said, 75% got (n 2709); 84% said, 86% got (n 1203); 92% said, 94% got (n 126)

## The take threshold

Chosen on January to May, confirmed on June to October, against the proxy book at a 9% overround. Return is per line staked, at the proxy book's price. Said and got are on the takes only.

| Market | Threshold | Takes (Jan to May) | Said | Got | Claimed edge | Return | 90% low | Takes (Jun to Oct) | Said | Got | Return | 90% interval | Held |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| corners (one side) | 5.0% | 3122 | 69% | 66% | 12.2% | 6.7% | 4.2% | 1249 | 65% | 61% | 3.8% | 0.0% to 7.9% | yes |
| corners (match total) | 7.5% | 1004 | 65% | 61% | 14.8% | 6.2% | 1.4% | 468 | 65% | 53% | -7.8% | -15.1% to -0.6% | no |
| cards (one side) | none up to 30% | - | - | - | - | - | - | - | - | - | - | - | - |
| cards (match total) | 5.0% | 626 | 63% | 63% | 11.0% | 10.5% | 5.2% | 398 | 65% | 56% | -4.7% | -11.1% to 2.1% | no |
| fouls (one side) | none up to 30% | - | - | - | - | - | - | - | - | - | - | - | - |
| shots on target (one side) | 5.0% | 1304 | 67% | 62% | 12.8% | 4.9% | 1.3% | 618 | 65% | 69% | 18.5% | 13.4% to 23.3% | yes |
| shots (one side) | not testable | - | - | - | - | - | - | - | - | - | - | - | - |

### Every threshold

What each threshold on the grid would have done. Only the January to May columns choose; the June to October columns are shown so the choice can be checked, not to make it.

**corners (one side)**

| t | Takes (Jan to May) | Said | Got | Return | 90% low | Takes (Jun to Oct) | Said | Got | Return | 90% low |
|---|---|---|---|---|---|---|---|---|---|---|
| 5.0% | 3122 | 69% | 66% | 6.7% | 4.2% | 1249 | 65% | 61% | 3.8% | 0.0% |
| 7.5% | 2284 | 68% | 64% | 7.2% | 4.1% | 870 | 65% | 60% | 5.8% | 1.1% |
| 10.0% | 1668 | 67% | 62% | 8.0% | 4.4% | 607 | 64% | 61% | 9.9% | 4.2% |
| 12.5% | 1210 | 67% | 61% | 9.9% | 5.8% | 409 | 63% | 60% | 11.3% | 4.7% |
| 15.0% | 878 | 66% | 61% | 11.2% | 6.7% | 260 | 62% | 59% | 12.5% | 4.3% |
| 17.5% | 611 | 65% | 59% | 10.4% | 5.0% | 180 | 62% | 57% | 11.2% | 0.9% |
| 20.0% | 419 | 65% | 57% | 9.2% | 2.9% | 119 | 62% | 53% | 4.2% | -7.5% |
| 22.5% | 269 | 64% | 55% | 8.7% | 0.6% | 72 | 62% | 51% | 1.4% | -13.6% |
| 25.0% | 158 | 63% | 55% | 10.2% | -0.4% | 35 | 63% | 40% | -21.5% | -41.3% |
| 27.5% | 76 | 64% | 58% | 15.4% | 1.1% | 14 | 63% | 29% | -44.2% | -74.4% |
| 30.0% | 0 | - | - | - | - | 0 | - | - | - | - |

**corners (match total)**

| t | Takes (Jan to May) | Said | Got | Return | 90% low | Takes (Jun to Oct) | Said | Got | Return | 90% low |
|---|---|---|---|---|---|---|---|---|---|---|
| 5.0% | 1367 | 66% | 61% | 2.6% | -1.6% | 672 | 66% | 54% | -8.6% | -14.5% |
| 7.5% | 1004 | 65% | 61% | 6.2% | 1.4% | 468 | 65% | 53% | -7.8% | -15.1% |
| 10.0% | 752 | 65% | 59% | 7.2% | 1.7% | 329 | 64% | 50% | -9.3% | -18.3% |
| 12.5% | 548 | 64% | 59% | 10.0% | 3.7% | 222 | 63% | 50% | -5.3% | -16.1% |
| 15.0% | 401 | 63% | 59% | 12.3% | 5.0% | 162 | 63% | 49% | -6.3% | -18.3% |
| 17.5% | 300 | 63% | 57% | 10.3% | 1.7% | 98 | 62% | 48% | -4.3% | -19.1% |
| 20.0% | 204 | 62% | 54% | 9.8% | -0.8% | 72 | 61% | 46% | -5.3% | -22.4% |
| 22.5% | 123 | 60% | 57% | 18.9% | 7.2% | 47 | 60% | 45% | -6.5% | -24.4% |
| 25.0% | 84 | 59% | 49% | 6.1% | -9.6% | 21 | 63% | 43% | -12.6% | -39.8% |
| 27.5% | 44 | 59% | 50% | 10.6% | -10.4% | 12 | 64% | 42% | -15.6% | -50.2% |
| 30.0% | 0 | - | - | - | - | 0 | - | - | - | - |

**cards (one side)**

| t | Takes (Jan to May) | Said | Got | Return | 90% low | Takes (Jun to Oct) | Said | Got | Return | 90% low |
|---|---|---|---|---|---|---|---|---|---|---|
| 5.0% | 645 | 65% | 61% | 4.3% | -0.4% | 448 | 64% | 64% | 11.3% | 5.9% |
| 7.5% | 408 | 64% | 59% | 3.9% | -2.1% | 291 | 63% | 61% | 10.3% | 3.4% |
| 10.0% | 253 | 62% | 57% | 5.0% | -3.3% | 200 | 62% | 56% | 6.1% | -2.4% |
| 12.5% | 165 | 61% | 55% | 4.9% | -4.7% | 129 | 62% | 57% | 11.1% | -0.1% |
| 15.0% | 99 | 60% | 52% | 2.8% | -10.6% | 87 | 60% | 55% | 11.9% | -2.5% |
| 17.5% | 73 | 59% | 51% | 3.5% | -12.9% | 55 | 59% | 49% | 6.0% | -12.9% |
| 20.0% | 42 | 57% | 52% | 11.4% | -10.9% | 36 | 58% | 50% | 10.5% | -12.3% |
| 22.5% | 18 | 57% | 39% | -17.2% | -50.4% | 24 | 58% | 58% | 31.0% | 2.5% |
| 25.0% | 10 | 58% | 30% | -39.2% | -77.9% | 11 | 58% | 82% | 87.4% | 47.7% |
| 27.5% | 2 | 62% | 50% | 12.7% | -100.0% | 3 | 57% | 67% | 65.1% | -17.7% |
| 30.0% | 0 | - | - | - | - | 0 | - | - | - | - |

**cards (match total)**

| t | Takes (Jan to May) | Said | Got | Return | 90% low | Takes (Jun to Oct) | Said | Got | Return | 90% low |
|---|---|---|---|---|---|---|---|---|---|---|
| 5.0% | 626 | 63% | 63% | 10.5% | 5.2% | 398 | 65% | 56% | -4.7% | -11.1% |
| 7.5% | 428 | 62% | 61% | 13.2% | 6.9% | 270 | 63% | 55% | -1.9% | -10.0% |
| 10.0% | 280 | 61% | 61% | 16.3% | 8.0% | 185 | 62% | 51% | -6.0% | -16.4% |
| 12.5% | 185 | 59% | 61% | 22.7% | 13.3% | 121 | 61% | 50% | -4.1% | -16.4% |
| 15.0% | 128 | 57% | 60% | 26.1% | 15.1% | 84 | 60% | 49% | -4.3% | -18.8% |
| 17.5% | 83 | 56% | 59% | 27.7% | 13.1% | 47 | 60% | 53% | 7.8% | -13.3% |
| 20.0% | 52 | 56% | 56% | 22.0% | 1.5% | 36 | 60% | 50% | 3.1% | -18.6% |
| 22.5% | 35 | 58% | 57% | 23.4% | -1.3% | 20 | 60% | 55% | 9.6% | -18.5% |
| 25.0% | 20 | 55% | 50% | 15.5% | -17.0% | 10 | 61% | 70% | 44.1% | 2.4% |
| 27.5% | 8 | 55% | 25% | -38.3% | -100.0% | 6 | 62% | 67% | 35.8% | -21.2% |
| 30.0% | 0 | - | - | - | - | 0 | - | - | - | - |

**fouls (one side)**

| t | Takes (Jan to May) | Said | Got | Return | 90% low | Takes (Jun to Oct) | Said | Got | Return | 90% low |
|---|---|---|---|---|---|---|---|---|---|---|
| 5.0% | 982 | 64% | 57% | -1.3% | -6.4% | 613 | 63% | 62% | 9.4% | 3.6% |
| 7.5% | 685 | 63% | 55% | -0.7% | -6.8% | 383 | 62% | 62% | 12.5% | 4.6% |
| 10.0% | 497 | 63% | 54% | -1.0% | -8.1% | 264 | 61% | 61% | 15.7% | 6.5% |
| 12.5% | 352 | 62% | 53% | 1.3% | -7.2% | 164 | 61% | 63% | 20.8% | 9.7% |
| 15.0% | 252 | 62% | 51% | -0.4% | -9.8% | 118 | 60% | 59% | 16.7% | 4.3% |
| 17.5% | 161 | 63% | 54% | 6.3% | -5.0% | 68 | 59% | 60% | 20.8% | 5.4% |
| 20.0% | 110 | 62% | 55% | 8.6% | -3.7% | 45 | 60% | 60% | 20.9% | -1.2% |
| 22.5% | 71 | 63% | 52% | 4.5% | -11.9% | 27 | 60% | 56% | 11.7% | -13.5% |
| 25.0% | 37 | 61% | 49% | -3.0% | -23.5% | 12 | 63% | 42% | -25.9% | -57.0% |
| 27.5% | 14 | 61% | 43% | -13.3% | -44.2% | 4 | 64% | 50% | -14.4% | -58.7% |
| 30.0% | 0 | - | - | - | - | 0 | - | - | - | - |

**shots on target (one side)**

| t | Takes (Jan to May) | Said | Got | Return | 90% low | Takes (Jun to Oct) | Said | Got | Return | 90% low |
|---|---|---|---|---|---|---|---|---|---|---|
| 5.0% | 1304 | 67% | 62% | 4.9% | 1.3% | 618 | 65% | 69% | 18.5% | 13.4% |
| 7.5% | 972 | 66% | 61% | 5.6% | 1.3% | 444 | 64% | 68% | 21.5% | 15.5% |
| 10.0% | 743 | 65% | 60% | 7.2% | 2.3% | 322 | 63% | 67% | 24.0% | 16.8% |
| 12.5% | 567 | 65% | 59% | 7.1% | 1.9% | 233 | 63% | 63% | 19.3% | 10.1% |
| 15.0% | 428 | 65% | 58% | 7.5% | 1.3% | 162 | 63% | 64% | 23.9% | 14.4% |
| 17.5% | 304 | 64% | 59% | 13.4% | 6.0% | 116 | 62% | 65% | 29.1% | 17.7% |
| 20.0% | 198 | 63% | 60% | 16.6% | 7.9% | 80 | 63% | 62% | 23.8% | 10.0% |
| 22.5% | 137 | 63% | 57% | 12.5% | 1.8% | 43 | 65% | 67% | 31.5% | 14.3% |
| 25.0% | 86 | 63% | 49% | -4.6% | -17.9% | 20 | 66% | 55% | 6.4% | -22.7% |
| 27.5% | 40 | 61% | 42% | -13.8% | -34.0% | 7 | 66% | 86% | 65.4% | 27.4% |
| 30.0% | 0 | - | - | - | - | 0 | - | - | - | - |

### How much the overround matters

Each passed market's threshold, re-priced against proxy books with other overrounds. A smaller overround is a sharper, harder book.

| Market | Threshold | Overround | Takes (Jan to May) | Return | Takes (Jun to Oct) | Return |
|---|---|---|---|---|---|---|
| corners (one side) | 5.0% | 5% | 4818 | 7.5% | 2132 | 3.9% |
| corners (one side) | 5.0% | 9% | 3122 | 6.7% | 1249 | 3.8% |
| corners (one side) | 5.0% | 12% | 2253 | 5.4% | 835 | 3.7% |
| shots on target (one side) | 5.0% | 5% | 1889 | 7.1% | 969 | 20.0% |
| shots on target (one side) | 5.0% | 9% | 1304 | 4.9% | 618 | 18.5% |
| shots on target (one side) | 5.0% | 12% | 961 | 4.2% | 445 | 18.5% |

## Against Betfair's prices

The exchange's own chance at the last price logged before kick-off, over side, one row per match and line. Far too few matches to decide anything, shown so the gap can be watched.

| Market | Lines | Matches | Log loss: Betfair | base | record | model | Brier: Betfair | base | record | model |
|---|---|---|---|---|---|---|---|---|---|---|
| corners (match total) | 9 | 9 | 0.666 | 0.670 | 0.714 | 0.674 | 0.237 | 0.239 | 0.260 | 0.241 |
| cards (match total) | 9 | 9 | 0.564 | 0.654 | 0.566 | 0.584 | 0.186 | 0.231 | 0.188 | 0.196 |

## Verdict by market

- **corners (one side)**: **Passed, take from an edge of 5.0%.** The model's log loss is 0.5766 against 0.6042 for the base rate and 0.6355 for the page's record price; calibration slope 0.87. Against the proxy book its takes paid 6.7% a line on January to May (3122 takes) and 3.8% on June to October (1249 takes, 90% interval 0.0% to 7.9%). On the later takes it said 65% and got 61%: the chance shown on a take runs high, as on any line picked for disagreeing with a price, and the edge it claimed (11.3% on average) was more than it earned. Against a sharper book with a 5% overround the same threshold returned 3.9% on the later months. The biggest claimed edges did worst: on June to October the 35 lines claiming 25.0% or more returned -21.5%, so a take far above the threshold deserves more doubt, not less. Whether that survives Paddy Power's real prices is for the team log to say.
- **corners (match total)**: **Failed.** The model's log loss is 0.6000 against 0.6009 for the base rate and 0.6607 for the page's record price; calibration slope 0.85. Failed because: not clearly better than the base on log loss; not clearly better than the base on brier; the 7.5% threshold did not hold from June. The model adds next to nothing over the base rate here, so a gap between it and a price is mostly noise. On the 9 matches Betfair priced, the exchange scored 0.666 and the model 0.674. Never a take; acceptable at most.
- **cards (one side)**: **Failed.** The model's log loss is 0.4785 against 0.4881 for the base rate and 0.5294 for the page's record price; calibration slope 1.05. Failed because: no threshold up to 30% paid against the proxy book on January to May. The later months look better than the earlier ones, but choosing a threshold from them would be choosing it on the data that is meant to test it. Never a take; acceptable at most.
- **cards (match total)**: **Failed.** The model's log loss is 0.5511 against 0.5601 for the base rate and 0.5913 for the page's record price; calibration slope 0.94. Failed because: the 5.0% threshold did not hold from June. On the 9 matches Betfair priced, the exchange scored 0.564 and the model 0.584. Never a take; acceptable at most.
- **fouls (one side)**: **Failed.** The model's log loss is 0.6164 against 0.6572 for the base rate and 0.6599 for the page's record price; calibration slope 0.94. Failed because: no threshold up to 30% paid against the proxy book on January to May. The later months look better than the earlier ones, but choosing a threshold from them would be choosing it on the data that is meant to test it. Never a take; acceptable at most.
- **shots on target (one side)**: **Passed, take from an edge of 5.0%.** The model's log loss is 0.5596 against 0.6001 for the base rate and 0.6134 for the page's record price; calibration slope 0.90. Against the proxy book its takes paid 4.9% a line on January to May (1304 takes) and 18.5% on June to October (618 takes, 90% interval 13.4% to 23.3%). On the later takes it said 65% and got 69%, on January to May 67% and 62%. The later months beat the earlier ones by a distance, which says more about how weak the proxy book was on them than about Paddy Power. Against a sharper book with a 5% overround the same threshold returned 20.0% on the later months. Whether that survives Paddy Power's real prices is for the team log to say.
- **shots (one side)**: **Failed.** The model's log loss is 0.6110 against 0.6728 for the base rate and 0.6781 for the page's record price; calibration slope 0.95. Failed because: the deployed model is the linear fit itself, so it cannot disagree with the proxy book. The model is no worse for it: it beats the base rate and the record by more than any other market, but its only advantage is the linear fit, and that is the least a bookmaker knows. Never a take; acceptable at most.

## What this does not show

- **Paddy Power is not the proxy book.** It knows the team news, the referee and its own traders' views, so it is sharper than the linear fit, and a take against it is rarer and worth less than one against the stand-in. Passing here is the least a market must do, not proof that it beats Paddy Power.
- **The chance shown on a take is too high on average.** Pooled, the takes landed 4.1% below what the model said. The page shows the model's chance as it is; read the edge on a take as a good deal less than it says.
- **The lines are not Paddy Power's.** The ladder sits around each side's own average, which is close to where the main lines sit, but the alternative lines Paddy Power also offers further out are only partly covered.
- **The record has the last word.** `teamlog.py` now logs the team model's chance and the verdict on every Paddy Power team line, and `python teamlog.py report` splits the settled lines by market and by verdict. A passed market whose takes lose at the real prices over a few hundred settled lines should be failed by hand in `teamlines_gate.json` and the backtest revisited.

## Wiring

- `teamlines.py` holds the markets, the negative binomial and `verdict()`, and reads the gate.
- `report.py` attaches, at build time, each side's team-model expectation and spread to every football fixture (`teamModel`) and the gate (`teamLineGate`). `teamValued()` prices a line in a passed market from the team model and calls it a take only from the market's threshold to the 30% cap; every other line is priced as before and is never a take.
- `teamlog.py snapshot` records the team model's chance, the market and the verdict with every line; `report` splits the record by market and verdict.

