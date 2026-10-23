# US player models: audit (22 October 2026)

A stress test of the NBA and NFL player models in `usmodel/` (built 21 October,
see `usmodel/training/results.md`). The claim under test: they beat the site's
own price out of sample on every market, so their value flags can be trusted.
That claim rested on one train / validation / test split per sport, and the
only check against a real bookmaker was one game per sport.

Harness: `usmodel/training/audit_us.py` (rolling origin, bootstrap, betting
rule), `usmodel/training/audit_report.py` (these tables). Tests:
`tests/test_us_audit.py`. Fix: `usfeatures.py`.

## Verdict, in short

1. **NBA: not audited, and it cannot be from this repository.** The cache
   archive in the repo (`cache_backtest.tar.zst`) holds NFL box scores but no
   NBA ones, and SofaScore is not reachable from the cloud box. Every NBA
   number below is either from the original single split or a code review.
   The harness runs the full NBA audit on the Mac in one command (section 8).
   Until it has, NBA "take" flags have no backing beyond one split whose test
   period was mostly play-offs, and one opening night on which the site's own
   price beat both the model and the blend against Paddy Power.
2. **NFL: the model is a better probability than the site on six of twelve
   markets, robustly.** Receptions, rushing attempts, rushing plus receiving
   yards, tackles and anytime touchdown win in all or all but one of the
   test seasons and in 14 to 17 of 18 monthly origins (rushing attempts 11
   of 11), with game-level bootstrap intervals well clear
   of zero, even after a Bonferroni correction for twelve markets. Receiving
   yards survives at 95% but not Bonferroni.
3. **NFL: the five quarterback markets and rushing yards do not survive.**
   Against the site recalibrated (the fair comparison: a calibration fix is
   not the model's achievement) their gains are within noise, and on
   completions and attempts the model alone is worse than the recalibrated
   site. "Beats the site on every market" was true against the raw site
   price only, which is badly calibrated (it says 48% to 50% on overs that
   land 42% to 47%).
4. **Leakage: no feature reads same-day or later results.** One real flaw,
   fixed: an NFL player only became a row if he recorded a statistic, so a
   receiver's blank game (a guaranteed under) was never scored and never
   entered his form. Effect on the scores is small (at most 0.003 log loss).
5. **Betting: no evidence yet against a real bookmaker.** Against a synthetic
   book (the recalibrated site price plus a 7.5% margin) the page's take rule
   makes +9.6% over 22,338 NFL bets, interval +8.0% to +11.2%, but that book
   is the site itself, which Paddy Power beats. This is an upper bound, not
   a forecast. The value flags are only as good as the model is sharper than
   the book you bet into, and that has been measured on one game.
6. **The six live blended markets:** NFL passing attempts stays blended (the
   blend is clearly better than the model alone) but has no edge over the
   recalibrated site, so its takes are not evidenced. NBA points, points and
   rebounds, points and assists, and points rebounds and assists: provisionally
   switch to the model alone (the blend lost to the model alone out of sample
   on all four). NBA steals: keep the blend. All five NBA markets: hold takes
   to "acceptable" until the NBA audit has run. Details in section 7.

## 1. Data and method

**What the cache holds.** NFL only: 744 finished games with box scores and
line-ups, 2020 to 19 October 2026, uneven by season (41, 63, 95, 72, 96, 285
and 92 games for the 2020 to 2026 seasons). No NBA box scores at all.

**Rolling origin.** Each season is a test block once 15% of all rows lie
before it: 2023, 2024, 2025 and 2026 (2020 to 2022 are history only). For each
block and market, everything before the block is history; its last quarter
by date is validation, the rest training. Inside each fold the live pipeline
is rebuilt exactly as `train_us.py` builds it: tree shape chosen on
validation from the same four, Poisson LightGBM on his own weighted average
as an offset, the spread (negative binomial or empirical ratio) and Platt
calibration fitted on validation, the site's price recalibrated on training,
the blend fitted on validation, and blend-or-model chosen on the two halves
of validation. The test block is scored once. A market is skipped in a block
when training has under 300 rows (the rule in `train_us.py`); that leaves
the quarterback markets with two blocks (2025, 2026), the rest with four.

**Prices compared**, all at three lines per player-game (his last-10 median
and 25% to 30% either side, as in the original backtest):

| name | what it is |
|---|---|
| site | `model.price_player` on his last 20 games: what the page quotes |
| site recal | the same, recalibrated on the fold's training data |
| model | the model alone, calibrated on validation |
| blend | the model blended with site recal (always) |
| live | blend or model alone, as chosen inside validation: what the page shows |

**Bootstrap.** Lines in one game move together (one quarterback's bad day
sinks all his lines and his receivers' lines), so every interval resamples
whole games, 2,000 times. A gain "survives" when its 95% interval is above
zero; "survives Bonferroni" when the share of replicates at or below zero is
under 0.05 / 12.

**Sensitivity runs**, same harness: monthly origins (18 blocks, the model
retrained every month), and the known starter flag replaced by start rate.

**What is optimistic in this design, and what is not.** The feature list per
market is the one the live model uses, chosen in the original ablation on a
validation window (September to November 2025) that lies inside the 2025
test block, so the 2025 block is mildly flattered; the 2026 block is clean.
The lines are synthetic, not bookmakers' lines.

## 2. Leakage review of usfeatures.py

| check | how | result |
|---|---|---|
| Any feature from same-day or later box scores | Scrambled every result, team box score and player box score from 2 November 2025 on and deleted every later game, rebuilt the features, compared every pre-game column for that day and before (697 rows on the day, 24,249 in all) | No column moved. Also a unit test, NFL and NBA, on synthetic seasons |
| Same-day, earlier kick-off | Changed the 1pm games' box scores, compared the 4pm games' features | Unchanged (test) |
| Elo | Read before each game's update; new season pulled a third to 1500 | Clean |
| Team style and positional concession | Updated only when the clock moves past a tip-off time | Clean |
| Player form, head to head, rest | His history is appended after each time block | Clean |
| **Which rows exist** | NFL rows kept only where the player recorded a statistic | **Leak, fixed** (below) |
| Starter flag | This game's line-up: exact in the backtest, live only when team news has a confirmed line-up, else start rate 50%+ | NFL: no effect (starter-proxy run, table 6). NBA: must be checked, run with `--starter-proxy` |
| Missing team-mates, tonight's side | This game's line-up list. NFL lists who took part; live uses ESPN and team news outs | Pre-game information, but the backtest knows it perfectly. NBA line-ups list only players who got minutes, so a coach's decision not to play someone counts as "missing" in training: worth checking on the Mac |
| Evaluation lines | From his last-10 median before the game | Clean |
| Calibration, blend, blend choice | All fitted on validation; the `recent_shift` intercept in production meta uses the out-of-sample period, as documented in `train_us.py` | Clean for the scores; the shift is production-only |

**The fix.** In the NFL, SofaScore lists about 35 players a side (those who
took part, not the 46+ actives); 2,584 of 51,794 listed appearances carry no
statistics, 182 of them receivers, tight ends and running backs. Those rows
were dropped (`played = has_stats == 1`), so the blank game was never scored
(the over always loses there) and never entered his form. Now every listed
NFL player is a row and a blank game is a game of zeros, in `features()` and
in `add_upcoming()`'s choice of regulars. NBA is unchanged: a player with no
minutes did not play and his bets are void. Tests: `ZeroStatGames` (fail on
the old code, pass now).

**Production models were not retrained.** The exported NFL trees were fitted
on the old features. The fix moves form features only for players with a
recent blank game (348 of 104,641 scored lines came from blank games). Retrain
on the Mac after merging: `train_us.py nfl` as in `usmodel/training/README.md`.

## 3. NFL rolling-origin backtest

Test blocks 2023, 2024, 2025 and 2026 (to 19 October). 104,641 scored lines across 545 games.

### 3a. Log loss, pooled over every test block (lower is better)

| market | folds | games | lines | site | site recal | model | blend | live | live v recal |
|---|---|---|---|---|---|---|---|---|---|
| pass_yds | 2 | 377 | 2300 | 0.6077 | 0.6075 | 0.6009 | 0.5968 | 0.5978 | +0.0097 |
| pass_cmp | 2 | 377 | 2361 | 0.5576 | 0.5307 | 0.5416 | 0.5293 | 0.5372 | -0.0065 |
| pass_att | 2 | 377 | 2364 | 0.5426 | 0.5175 | 0.5238 | 0.5114 | 0.5189 | -0.0014 |
| pass_td | 2 | 374 | 2283 | 0.6485 | 0.6429 | 0.6410 | 0.6425 | 0.6410 | +0.0019 |
| rush_yds | 4 | 544 | 6723 | 0.6608 | 0.6546 | 0.6523 | 0.6518 | 0.6523 | +0.0023 |
| rush_att | 4 | 543 | 5766 | 0.6199 | 0.6078 | 0.5664 | 0.5671 | 0.5658 | +0.0419 |
| rec_yds | 4 | 545 | 14118 | 0.6681 | 0.6610 | 0.6537 | 0.6546 | 0.6537 | +0.0073 |
| rec | 4 | 545 | 16650 | 0.6504 | 0.6389 | 0.6235 | 0.6238 | 0.6235 | +0.0154 |
| rush_rec_yds | 4 | 545 | 13389 | 0.6645 | 0.6579 | 0.6372 | 0.6373 | 0.6372 | +0.0207 |
| pass_rush_yds | 2 | 376 | 2297 | 0.5996 | 0.5998 | 0.5970 | 0.5924 | 0.5970 | +0.0027 |
| tackles | 4 | 545 | 31329 | 0.6388 | 0.6270 | 0.6145 | 0.6146 | 0.6144 | +0.0126 |
| td | 4 | 545 | 5061 | 0.6073 | 0.5857 | 0.5718 | 0.5726 | 0.5721 | +0.0137 |

The last column is the gap that matters: positive means the page's live chance beat the site's own price after that price was recalibrated.

### 3b. Brier score (lower is better)

| market | site | site recal | model | blend | live |
|---|---|---|---|---|---|
| pass_yds | 0.2086 | 0.2086 | 0.2067 | 0.2051 | 0.2054 |
| pass_cmp | 0.1864 | 0.1770 | 0.1793 | 0.1762 | 0.1777 |
| pass_att | 0.1800 | 0.1711 | 0.1714 | 0.1680 | 0.1696 |
| pass_td | 0.2283 | 0.2254 | 0.2252 | 0.2259 | 0.2252 |
| rush_yds | 0.2341 | 0.2314 | 0.2279 | 0.2278 | 0.2279 |
| rush_att | 0.2148 | 0.2099 | 0.1921 | 0.1925 | 0.1919 |
| rec_yds | 0.2377 | 0.2345 | 0.2310 | 0.2313 | 0.2310 |
| rec | 0.2292 | 0.2242 | 0.2172 | 0.2172 | 0.2172 |
| rush_rec_yds | 0.2359 | 0.2330 | 0.2230 | 0.2230 | 0.2230 |
| pass_rush_yds | 0.2051 | 0.2054 | 0.2043 | 0.2026 | 0.2043 |
| tackles | 0.2236 | 0.2185 | 0.2129 | 0.2130 | 0.2129 |
| td | 0.2079 | 0.1988 | 0.1927 | 0.1930 | 0.1928 |

### 3c. Calibration

Said and landed are the mean chance of the over and the share of overs that landed. Slope: logistic regression of the outcome on the log-odds of the chance; 1 is right, under 1 means too confident, over 1 too timid. ECE: mean gap between said and landed in ten bins.

| market | landed | site said | site slope | site ECE | recal said | recal slope | recal ECE | live said | live slope | live ECE |
|---|---|---|---|---|---|---|---|---|---|---|
| pass_yds | 0.465 | 0.480 | 1.38 | 0.052 | 0.474 | 1.40 | 0.051 | 0.445 | 0.87 | 0.034 |
| pass_cmp | 0.454 | 0.476 | 1.83 | 0.087 | 0.470 | 1.06 | 0.018 | 0.455 | 0.93 | 0.020 |
| pass_att | 0.485 | 0.485 | 1.80 | 0.082 | 0.476 | 1.14 | 0.028 | 0.472 | 1.07 | 0.040 |
| pass_td | 0.428 | 0.463 | 1.65 | 0.052 | 0.408 | 0.82 | 0.035 | 0.442 | 0.73 | 0.047 |
| rush_yds | 0.433 | 0.494 | 1.28 | 0.061 | 0.406 | 1.23 | 0.035 | 0.432 | 0.63 | 0.047 |
| rush_att | 0.446 | 0.486 | 1.65 | 0.064 | 0.430 | 1.24 | 0.035 | 0.433 | 0.98 | 0.014 |
| rec_yds | 0.431 | 0.495 | 1.18 | 0.064 | 0.405 | 1.21 | 0.031 | 0.450 | 0.83 | 0.019 |
| rec | 0.424 | 0.480 | 1.62 | 0.061 | 0.403 | 1.02 | 0.021 | 0.432 | 0.97 | 0.012 |
| rush_rec_yds | 0.438 | 0.498 | 1.16 | 0.060 | 0.418 | 1.21 | 0.025 | 0.453 | 0.86 | 0.019 |
| pass_rush_yds | 0.468 | 0.483 | 1.40 | 0.053 | 0.464 | 1.46 | 0.057 | 0.457 | 0.77 | 0.042 |
| tackles | 0.436 | 0.474 | 1.69 | 0.061 | 0.433 | 0.96 | 0.007 | 0.435 | 0.98 | 0.003 |
| td | 0.284 | 0.381 | 0.73 | 0.108 | 0.273 | 1.66 | 0.026 | 0.275 | 0.79 | 0.021 |

The raw site overstates the over on eleven of twelve markets, by 4 to 6 points on most and 10 on anytime touchdown, and is too timid everywhere but anytime touchdown (slopes 1.2 to 1.8): most of why it lost to the model in the original report. The live chance is within two points of what landed on every market, but too confident on the yards markets (slopes 0.63 to 0.87), passing touchdowns (0.73) and anytime touchdown (0.79): its strong opinions there should be shrunk.

### 3d. Gain per test block, against the recalibrated site

Positive: live better. Blank: too little history before that block to train a quarterback model (under 300 rows).

| market | 2023 | 2024 | 2025 | 2026 | blocks won |
|---|---|---|---|---|---|
| pass_yds |  |  | +0.0130 | -0.0007 | 1 of 2 |
| pass_cmp |  |  | -0.0080 | -0.0017 | 0 of 2 |
| pass_att |  |  | -0.0059 | +0.0131 | 1 of 2 |
| pass_td |  |  | +0.0037 | -0.0037 | 1 of 2 |
| rush_yds | -0.0482 | +0.0125 | +0.0052 | +0.0167 | 3 of 4 |
| rush_att | +0.0484 | +0.0294 | +0.0447 | +0.0416 | 4 of 4 |
| rec_yds | +0.0025 | +0.0053 | +0.0067 | +0.0149 | 4 of 4 |
| rec | +0.0024 | +0.0175 | +0.0172 | +0.0175 | 4 of 4 |
| rush_rec_yds | +0.0225 | +0.0364 | +0.0133 | +0.0266 | 4 of 4 |
| pass_rush_yds |  |  | +0.0083 | -0.0148 | 1 of 2 |
| tackles | -0.0009 | +0.0169 | +0.0147 | +0.0117 | 3 of 4 |
| td | +0.0122 | +0.0203 | +0.0123 | +0.0125 | 4 of 4 |

## 4. Bootstrap: which gains survive

Live's log-loss gain over the raw site and over the recalibrated site, 95% interval from resampling whole games.

| market | v site | 95% interval | v recal site | 95% interval | P(gain <= 0) | survives | survives Bonferroni |
|---|---|---|---|---|---|---|---|
| pass_yds | +0.0099 | -0.0030 to +0.0231 | +0.0097 | -0.0030 to +0.0223 | 0.069 | no | no |
| pass_cmp | +0.0204 | +0.0059 to +0.0338 | -0.0065 | -0.0180 to +0.0042 | 0.880 | no | no |
| pass_att | +0.0237 | +0.0106 to +0.0354 | -0.0014 | -0.0119 to +0.0090 | 0.603 | no | no |
| pass_td | +0.0075 | -0.0063 to +0.0207 | +0.0019 | -0.0122 to +0.0161 | 0.409 | no | no |
| rush_yds | +0.0085 | -0.0070 to +0.0242 | +0.0023 | -0.0123 to +0.0167 | 0.364 | no | no |
| rush_att | +0.0541 | +0.0420 to +0.0664 | +0.0419 | +0.0302 to +0.0540 | 0.000 | yes | yes |
| rec_yds | +0.0144 | +0.0091 to +0.0197 | +0.0073 | +0.0015 to +0.0131 | 0.006 | yes | no |
| rec | +0.0269 | +0.0218 to +0.0316 | +0.0154 | +0.0111 to +0.0195 | 0.000 | yes | yes |
| rush_rec_yds | +0.0273 | +0.0205 to +0.0339 | +0.0207 | +0.0143 to +0.0270 | 0.000 | yes | yes |
| pass_rush_yds | +0.0025 | -0.0137 to +0.0182 | +0.0027 | -0.0133 to +0.0184 | 0.365 | no | no |
| tackles | +0.0244 | +0.0212 to +0.0274 | +0.0126 | +0.0098 to +0.0154 | 0.000 | yes | yes |
| td | +0.0352 | +0.0268 to +0.0435 | +0.0137 | +0.0078 to +0.0198 | 0.000 | yes | yes |

**Survive** (interval above zero against the recalibrated site): rushing attempts, receiving yards, receptions, rushing plus receiving yards, tackles, anytime touchdown. All but receiving yards also survive Bonferroni.

**Do not survive:** passing yards, completions, attempts, touchdowns, passing plus rushing yards, rushing yards. Against the raw site, completions and attempts do survive, which is the original report's claim; it was a calibration gain. Rushing yards survives with monthly retraining (section 6) but lost badly in the 2023 block (-0.048): retraining often matters for it.

For scale: a gain of 0.01 in log loss is about the difference between saying 53% and 60% on lines that land 60% of the time.

## 5. The page's betting rule, simulated

The rule is `verdictOf` in report.py: **take** when our chance is 50% or more, the edge (chance times price, minus one) is 5% or more but not over 30% (the NBA and NFL guard), the record is five games or more and the data is not stale (a game in the last 60 days). Flat one-unit stakes on every take, at every one of the three lines, either side.

**There are no historical bookmaker prices for these seasons.** Paddy Power's record (`pplog/`) lives on the Mac only, starts in October 2026 and covers one NFL game. So the book here is synthetic: the recalibrated site chance, turned into two-way prices with a 7.5% margin (5% and 10% as checks; a raw-site book as another). That book knows what the site knows and nothing else. A real bookmaker knows more: on the one NFL game checked, Paddy Power's log loss was 0.5043 against the site's 0.5200, and across all sports the page's own value flags on Paddy Power lines are at -34% ROI over 177 bets (pp-results.html, 21 October). Read every ROI below as what the rule would make against a book no sharper than our own site: an upper bound.

### 5a. Every take, at all three lines

Columns: bets and ROI at a 7.5% margin with its 95% interval (resampling whole games); ROI (bets) at 5% and 10% margins; one bet per player-game at the line with the biggest edge; and a book priced from the raw site instead.

| market | bets (7.5%) | won | ROI 7.5% | 95% interval | ROI 5% margin | ROI 10% margin | best rung only: bets, ROI, interval | book = raw site, 7.5%: bets, ROI |
|---|---|---|---|---|---|---|---|---|
| pass_yds | 964 | 677 | +5.1% | +0.1% to +9.9% | +6.5% (1066) | +3.6% (838) | 549, +6.0%, -0.0% to +11.7% | 969, +5.5% |
| pass_cmp | 347 | 221 | -4.5% | -12.7% to +3.7% | -2.0% (421) | -3.4% (280) | 245, -8.5%, -17.9% to +1.0% | 995, +7.2% |
| pass_att | 299 | 200 | +1.8% | -6.9% to +10.3% | +1.4% (357) | +1.6% (240) | 208, +4.6%, -6.2% to +14.8% | 780, +10.1% |
| pass_td | 500 | 281 | -1.9% | -13.8% to +10.7% | -1.0% (558) | +0.3% (440) | 296, -1.3%, -11.6% to +9.0% | 1046, +9.0% |
| rush_yds | 1899 | 1219 | +4.9% | +0.2% to +9.4% | +5.5% (2044) | +3.8% (1752) | 1041, +6.9%, +1.9% to +11.9% | 2493, +9.5% |
| rush_att | 1501 | 1126 | +16.0% | +12.0% to +20.0% | +16.0% (1641) | +13.9% (1411) | 969, +16.4%, +11.7% to +21.0% | 2040, +19.0% |
| rec_yds | 3285 | 1941 | +8.2% | +4.2% to +12.2% | +9.6% (3505) | +7.8% (3036) | 2151, +10.7%, +6.7% to +14.5% | 4960, +8.5% |
| rec | 3406 | 2195 | +13.1% | +9.5% to +16.8% | +13.3% (3898) | +13.3% (2886) | 2226, +13.3%, +9.8% to +16.7% | 6509, +14.8% |
| rush_rec_yds | 3695 | 2418 | +12.0% | +8.5% to +15.5% | +12.4% (4080) | +12.3% (3303) | 2334, +11.5%, +7.9% to +15.0% | 4979, +14.3% |
| pass_rush_yds | 908 | 642 | +3.9% | -0.8% to +8.3% | +6.4% (992) | +1.1% (820) | 561, +5.7%, +0.1% to +11.2% | 915, +2.4% |
| tackles | 4914 | 3231 | +11.6% | +8.8% to +14.5% | +11.5% (6224) | +11.4% (3913) | 3435, +12.1%, +9.3% to +15.1% | 13065, +12.5% |
| td | 620 | 509 | +4.6% | +0.4% to +8.4% | +5.0% (968) | +3.7% (360) | 620, +4.6%, +0.4% to +8.4% | 2337, +10.8% |

All markets together (7.5% margin): 22338 bets, 14660 won, ROI +9.6%, 95% interval +8.0% to +11.2%.

### 5b. One line per player-game, at his median (closest to a bookmaker's main line)

The ladder rungs 25% to 30% either side of his median are where the biggest disagreements with the site sit, and real books rarely offer them at such prices. The median line alone, both sides, and the over alone (Paddy Power mostly offers overs), 7.5% margin:

| market | bets | ROI | 95% interval | over-only bets | ROI | 95% interval |
|---|---|---|---|---|---|---|
| pass_yds | 332 | -2.9% | -12.0% to +6.7% | 130 | +2.7% | -13.2% to +19.2% |
| pass_cmp | 154 | -13.0% | -26.4% to +0.9% | 30 | +11.3% | -27.6% to +51.3% |
| pass_att | 124 | -0.3% | -15.2% to +14.8% | 41 | -15.3% | -44.2% to +11.9% |
| pass_td | 122 | -5.3% | -22.4% to +12.9% | 69 | -6.4% | -31.7% to +18.1% |
| rush_yds | 633 | +3.5% | -3.3% to +9.9% | 177 | +9.5% | -5.1% to +24.6% |
| rush_att | 537 | +16.4% | +9.4% to +22.9% | 118 | +26.4% | +9.2% to +44.3% |
| rec_yds | 925 | +1.1% | -4.9% to +7.4% | 655 | +1.6% | -6.8% to +10.5% |
| rec | 900 | +12.7% | +7.2% to +18.4% | 442 | +18.6% | +8.7% to +28.3% |
| rush_rec_yds | 1149 | +10.4% | +4.8% to +15.8% | 590 | +8.1% | -0.1% to +16.9% |
| pass_rush_yds | 242 | -8.6% | -19.7% to +3.1% | 110 | -4.4% | -23.3% to +13.8% |
| tackles | 1769 | +10.8% | +6.7% to +14.9% | 486 | +18.6% | +10.3% to +27.2% |
| td | 620 | +4.6% | +0.4% to +8.4% | 5 | +46.9% | -51.9% to +145.8% |
| all | 7507 | +6.9% | +4.8% to +9.0% | 2853 | +9.6% | +5.3% to +14.3% |

Even against the soft book, the take rule loses or breaks even on every quarterback market at the median line, and on receiving yards it is +1.1% (-4.9% to +7.4%). Rushing attempts, receptions, rushing plus receiving yards and tackles hold up. Bet counts are large because the simulation bets every eligible player in every game; a real book offers a fraction of these lines.

## 6. Sensitivity

### 6a. Monthly origins (model retrained every month) and starter flag replaced by start rate

| market | season blocks: gain v recal [95%] | monthly: blocks, lines, gain [95%], survives, blocks won | live log loss, start-rate starter v known starter |
|---|---|---|---|
| pass_yds | +0.0097 [-0.0030, +0.0223] | 9, 2642, +0.0036 [-0.0095, +0.0170], no, 5 of 9 | 0.5971 v 0.5978 |
| pass_cmp | -0.0065 [-0.0180, +0.0042] | 9, 2709, -0.0057 [-0.0153, +0.0040], no, 4 of 9 | 0.5372 v 0.5372 |
| pass_att | -0.0014 [-0.0119, +0.0090] | 9, 2721, +0.0004 [-0.0084, +0.0092], no, 6 of 9 | 0.5189 v 0.5189 |
| pass_td | +0.0019 [-0.0122, +0.0161] | 8, 2454, +0.0042 [-0.0075, +0.0154], no, 4 of 8 | 0.6416 v 0.6410 |
| rush_yds | +0.0023 [-0.0123, +0.0167] | 14, 6405, +0.0202 [+0.0092, +0.0308], yes, 10 of 14 | 0.6505 v 0.6523 |
| rush_att | +0.0419 [+0.0302, +0.0540] | 11, 5079, +0.0465 [+0.0333, +0.0601], yes, 11 of 11 | 0.5665 v 0.5658 |
| rec_yds | +0.0073 [+0.0015, +0.0131] | 18, 14517, +0.0093 [+0.0041, +0.0143], yes, 16 of 18 | 0.6537 v 0.6537 |
| rec | +0.0154 [+0.0111, +0.0195] | 18, 17112, +0.0168 [+0.0121, +0.0214], yes, 14 of 18 | 0.6236 v 0.6235 |
| rush_rec_yds | +0.0207 [+0.0143, +0.0270] | 18, 13797, +0.0170 [+0.0108, +0.0230], yes, 16 of 18 | 0.6371 v 0.6372 |
| pass_rush_yds | +0.0027 [-0.0133, +0.0184] | 9, 2639, +0.0084 [-0.0069, +0.0221], no, 5 of 9 | 0.5990 v 0.5970 |
| tackles | +0.0126 [+0.0098, +0.0154] | 18, 32205, +0.0130 [+0.0102, +0.0161], yes, 17 of 18 | 0.6131 v 0.6144 |
| td | +0.0137 [+0.0078, +0.0198] | 18, 5211, +0.0151 [+0.0095, +0.0208], yes, 16 of 18 | 0.5726 v 0.5721 |

Monthly retraining gives the same six survivors plus rushing yards. Replacing the known NFL starter by his start rate changes nothing. All markets together under monthly origins: 23,388 synthetic take bets, ROI +10.9% (+9.2% to +12.5%); with the start-rate starter, 21,926 bets, +10.0% (+8.4% to +11.5%).

### 6b. The zero-stat fix, before and after (season blocks)

| market | lines before | lines after | live log loss before | after | gain v recal before | after |
|---|---|---|---|---|---|---|
| pass_yds | 2300 | 2300 | 0.5999 | 0.5978 | +0.0077 | +0.0097 |
| pass_cmp | 2361 | 2361 | 0.5376 | 0.5372 | -0.0068 | -0.0065 |
| pass_att | 2364 | 2364 | 0.5188 | 0.5189 | -0.0011 | -0.0014 |
| pass_td | 2283 | 2283 | 0.6401 | 0.6410 | +0.0029 | +0.0019 |
| rush_yds | 6726 | 6723 | 0.6511 | 0.6523 | +0.0036 | +0.0023 |
| rush_att | 5769 | 5766 | 0.5662 | 0.5658 | +0.0417 | +0.0419 |
| rec_yds | 14196 | 14118 | 0.6517 | 0.6537 | +0.0092 | +0.0073 |
| rec | 16713 | 16650 | 0.6243 | 0.6235 | +0.0141 | +0.0154 |
| rush_rec_yds | 13431 | 13389 | 0.6378 | 0.6372 | +0.0198 | +0.0207 |
| pass_rush_yds | 2297 | 2297 | 0.5972 | 0.5970 | +0.0026 | +0.0027 |
| tackles | 31431 | 31329 | 0.6154 | 0.6144 | +0.0115 | +0.0126 |
| td | 5061 | 5061 | 0.5762 | 0.5721 | +0.0102 | +0.0137 |

Fewer lines after the fix because a blank game now lowers his median, which takes some fringe players under the market's floor. The fix moves log loss by at most 0.003 either way: a real bias, a small one.

## 7. The six live blended markets

The page blends the model with the site (weights in `usmodel/*_meta.json`,
`use_blend: true`) on six markets: NFL passing attempts, and NBA points,
steals, points rebounds and assists, points and rebounds, points and assists.
Everywhere else it shows the model alone.

### 7a. NFL, every market: the blend always on, against the recalibrated site and against the model alone

| market | blend v recal site | 95% interval | blend v model alone | 95% interval | validation chose the blend in |
|---|---|---|---|---|---|
| pass_yds | +0.0107 | -0.0015 to +0.0230 | +0.0040 | +0.0023 to +0.0058 | 1 of 2 blocks |
| pass_cmp | +0.0014 | -0.0062 to +0.0087 | +0.0123 | +0.0068 to +0.0183 | 1 of 2 |
| **pass_att (live blend)** | +0.0061 | -0.0008 to +0.0130 | +0.0124 | +0.0073 to +0.0178 | 1 of 2 |
| pass_td | +0.0004 | -0.0178 to +0.0187 | -0.0016 | -0.0073 to +0.0040 | 0 of 2 |
| rush_yds | +0.0028 | -0.0116 to +0.0172 | +0.0005 | +0.0000 to +0.0009 | 0 of 4 |
| rush_att | +0.0406 | +0.0291 to +0.0524 | -0.0007 | -0.0021 to +0.0007 | 1 of 4 |
| rec_yds | +0.0064 | +0.0006 to +0.0124 | -0.0009 | -0.0015 to -0.0002 | 0 of 4 |
| rec | +0.0151 | +0.0103 to +0.0199 | -0.0002 | -0.0010 to +0.0005 | 0 of 4 |
| rush_rec_yds | +0.0206 | +0.0141 to +0.0270 | -0.0001 | -0.0005 to +0.0003 | 0 of 4 |
| pass_rush_yds | +0.0074 | -0.0073 to +0.0219 | +0.0046 | +0.0028 to +0.0065 | 0 of 2 |
| tackles | +0.0123 | +0.0093 to +0.0154 | -0.0001 | -0.0005 to +0.0003 | 1 of 4 |
| td | +0.0131 | +0.0071 to +0.0192 | -0.0009 | -0.0016 to -0.0002 | 1 of 4 |

Two lessons. On the quarterback markets the blend is clearly better than the
model alone (the site's record of a quarterback carries information the
trees miss); on every other market the site adds nothing. And the
blend-or-model choice made on one validation window is unstable: it flipped
between blocks on six of twelve markets. A choice made once, on one split,
should not be trusted; for the quarterback markets "always blend" is the
better rule.

### 7b. NBA, the evidence there is (original single split, `usmodel/nba_meta.json`)

Out of sample April to June 2026 plus opening week. Mostly play-off games,
from a model trained on one regular season.

| market | site | site recal | model alone | blend (live) | blend minus model |
|---|---|---|---|---|---|
| points | 0.6440 | 0.6376 | 0.5875 | 0.5903 | +0.0028 (worse) |
| steals | 0.6242 | 0.5992 | 0.5900 | 0.5894 | -0.0006 (better) |
| pra | 0.6178 | 0.6100 | 0.5519 | 0.5538 | +0.0019 (worse) |
| pr | 0.6338 | 0.6275 | 0.5715 | 0.5742 | +0.0027 (worse) |
| pa | 0.6303 | 0.6240 | 0.5692 | 0.5718 | +0.0026 (worse) |

(`results.md` quotes slightly different numbers for the same markets, from
an earlier run; the meta file is what was exported.) The model's lead over
the recalibrated site, 0.04 to 0.06, is far larger than anything on the NFL
and larger than any NFL market sustained across seasons; that alone is a
reason to re-check it on more than one split. On opening night (561 Paddy
Power lines, one game) the order reversed: site 0.5686, blend 0.5729, model
0.5737, Paddy Power 0.5550.

### 7c. Recommendations

| market | recommendation | evidence |
|---|---|---|
| NFL passing attempts | **Stay live, blended as now.** Do not call its value flags "take" until pplog has a season of settled lines | Blend beats the model alone (+0.012, +0.007 to +0.018) with weights stable across blocks (0.55 / 0.50 and 0.57 / 0.50, live 0.58 / 0.59), but beats the recalibrated site by only +0.006 (-0.001 to +0.013). Take rule +1.8% (-6.9% to +10.3%) over 299 bets even against the soft book; -0.3% at the median line |
| NBA points | **Blend differently: model alone**, provisional | Blend lost to the model alone out of sample (+0.0028); site weight only 0.20 |
| NBA points rebounds and assists | **Model alone**, provisional | Blend lost (+0.0019); site weight 0.14 |
| NBA points and rebounds | **Model alone**, provisional | Blend lost (+0.0027); site weight 0.15 |
| NBA points and assists | **Model alone**, provisional | Blend lost (+0.0026); site weight 0.18 |
| NBA steals | **Stay live, blended** | The one NBA blend that won out of sample (-0.0006), small |
| All five NBA | **Switch off "take" (cap at acceptable) until the NBA audit has run** | No rolling-origin evidence; one season of training; test period mostly play-offs; on the one real-price check the site beat both the model and the blend |

The differences between blend and model alone on the NBA are 0.002 to 0.003,
small next to the uncertainty of a single split, so switching them is a low
stakes call either way. The take cap is the call that matters.

Beyond the six: on the NFL, value flags on passing yards, completions,
passing touchdowns, passing plus rushing yards and rushing yards rest on no
demonstrated edge (section 4) and should not be called "take" either. The
markets where the flags have a case are receptions, rushing attempts,
rushing plus receiving yards and tackles, then anytime touchdown and
receiving yards.

These are recommendations only: no page, model file or blend weight has been
changed in this branch.

## 8. NBA: how to run this audit on the Mac

The Mac's `cache/` holds the NBA box scores (`backfill.py` fetched the
2025-26 season). In the repo, with the training packages installed
(LightGBM, scipy, scikit-learn, pyarrow):

```
AUDIT_THREADS=4 python3 usmodel/training/audit_us.py nba --cache cache --data /tmp/usaudit --boot 2000
AUDIT_THREADS=4 python3 usmodel/training/audit_us.py nba --data /tmp/usaudit --out /tmp/usaudit/starter --starter-proxy
python3 usmodel/training/audit_report.py /tmp/usaudit/nba_audit.json > nba-audit-tables.md
```

With one season in the cache it uses calendar months as origins (each block
once 15% of the rows lie before it). Run the starter-proxy line too: the NBA
starter flag is this game's real starting five, which the page only knows
once team news confirms a line-up. Then fill the NBA rows of section 7 from
the tables. Same for the NFL with `nfl`, if the Mac's cache holds more
seasons than the archive here.

To score the models on real prices, `ppcheck_us.py` already matches pplog's
settled Paddy Power lines; it needs a few weeks of NFL and NBA lines before
its numbers mean anything, and its ROI should get the same game-level
bootstrap (`audit_us.roi_ci`).

## 9. Honest verdict

The NFL model is real. On receptions, rushing attempts, rushing plus
receiving yards, tackles and anytime touchdown it is a better probability
than the site's price, recalibrated or not, in every season the cache can
test, every monthly origin, with intervals that clear zero by a distance.
Receiving yards is better, narrowly. That much of the 21 October report
stands.

The headline claim does not. "Beats the site on every market" compared the
model with a badly calibrated site price; against the site recalibrated, the
quarterback markets and rushing yards are a coin toss, and completions and
attempts are slightly worse on the model alone. The model is also too
confident on the yards and touchdown markets.

Nothing here shows the value flags make money. The only simulation possible
without historical prices uses a book that is our own site with a margin, and
the real record on Paddy Power lines is one NFL game and one NBA night, with
the site's own flags losing a third of their stakes across sports. A model
that beats our site by 0.01 to 0.04 in log loss beats a bookmaker only if the
bookmaker is no sharper than our site, and on the one game measured it was
sharper.

The NBA model is unaudited. Its out-of-sample lead was larger than anything
the NFL sustained, on a play-off-heavy test period, from one season of
training, and it lost to the site on the one real check. Until the audit in
section 8 has run, treat its takes as unproven.

What would change the verdict: a few weeks of pplog settlements scored by
`ppcheck_us.py`, with game-level intervals, on the six NFL markets that
survive here. If the model beats Paddy Power's own price there, the flags on
those markets have earned their place.

## 10. Files

| file | what |
|---|---|
| `usfeatures.py` | the zero-stat fix (features and add_upcoming) |
| `usmodel/training/audit_us.py` | rolling origin, bootstrap, take-rule simulation; `--cache` builds from a cache, `--by season or month`, `--starter-proxy`, `AUDIT_THREADS` caps LightGBM threads |
| `usmodel/training/audit_report.py` | the tables in sections 3 to 6 from `{sport}_audit.json` |
| `tests/test_us_audit.py` | no look-ahead (NFL and NBA, synthetic), the fix, folds, take rule, settling, margins, bootstrap, report |
