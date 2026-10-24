# Acca correlation

Do the site's multiples land as often as their prices say? Written 23 October 2026 on the `acca-correlation` branch. Every number below is reproduced by

    python -B acca_corr.py report

which writes the same tables to `calib/acca_correlation.md`. The walk forward needs `cache/`, unpacked from `cache_backtest.tar.zst`; `--no-cache` runs sections 1 to 3 from `best_bets.json` alone.

## Verdict

**Pricing is left alone.** Nothing in the multiplied price is wrong by more than noise for a reason a multi-level correction could fix.

1. **Cross-game multiples (tonight.py's `ACCA_SHAPES` through `weekend.best_acca`, and the evens double): multiplying is right.** Legs in different games on the same night are independent to three decimal places. Fitted on the walk forward's earlier months the residual correlation is -0.0001 (interval -0.0003 to +0.0002); on 200 million later-month pairs the calibrated product lands at 1.01 (1.00 to 1.02) with or without it, because there is nothing to correct. Across the 277,000 cross-game pairs of legs the site actually published, rho is +0.001 for two team legs, +0.004 for two player legs and -0.007 for one of each, every interval spanning zero.

2. **The published 3-leg accas did land more often than said** (41 of 92, 44.6% against 31.2%, landed/said 1.43 with a by-night interval of 1.00 to 1.92). That is the legs, not the multiplying. Published legs land about 5% more often than their stated chance (football team legs 1.05, interval 1.02 to 1.10), and three of them compound to roughly 1.16. Priced off recalibrated legs the same tickets come out at 1.26 (0.88 to 1.65), which is noise on 92 tickets over 25 nights. Leg calibration is learner.py's job; correcting it at the multi would correct it twice.

3. **Same-game builders, priced off the joint count, are the one real warning, but the correction does not hold.** In the walk forward the builder weekend.py would have shown lands 31% of the time when its joint count says 43% (landed/said 0.72, 0.69 to 0.75, 6,158 football builders), because picking the best of twenty combinations on a 10 to 38 game sample picks the luckiest joint count. A correction fitted on the months before April 2026 fixes the later months (log loss 0.642 to 0.618), and then makes the 63 builders the site really published worse (predicts 39.5% where 54.0% landed; log loss 0.704 to 0.741). The walk forward builds its builders from record-only legs at the shared line, the page builds its own from strength-adjusted legs with its own pool, and a correction that helps the copy while hurting the original is a fact about the copy. So it is not wired in. It is the first thing to recheck once the published builder record is a few hundred tickets long rather than 63.

4. **Same-side legs do move together, and the page already respects it.** Two stats of the same team correlate (residual rho +0.033 overall, +0.205 for total shots with shots on target, +0.148 for corners with total shots); two stats of the same player more so (+0.047 for football players in the walk forward, +0.534 across the published player legs, led by the NFL at +0.470 and MLB at +0.977, where receptions and receiving yards, or hits and total bases, are nearly one bet). Multiplying such legs would underprice them. The page never multiplies them: `best_acca` takes one leg per fixture, `best_double` allows two legs from one game only on opposite sides (rho +0.002, nothing), and builders and parlays use joint counts. This class "holds" in section 5 of the tables, and it holds for a code path that does not exist.

One thing the evidence contradicts is the closing note on tonight.html, which says the cross-game prices "do not [carry the correlation discount], and are therefore optimistic". On this evidence they are not optimistic through correlation; any optimism or caution comes from the legs. I have not changed the copy, since the brief was to leave the page alone unless pricing changed, but it is worth a line next time tonight.py is touched.

## What was measured, and from what

**The record.** `best_bets.json`: 3,219 published bets between 27 September and 21 October 2026, of which 373 are settled multiples with no void leg (accas, evens doubles, builders, parlays) over 25 nights, and 2,564 distinct settled legs. A ticket with a void leg is left out rather than repriced, because a builder's joint count cannot be re-read without the leg. Each leg is priced as first shown.

**The lead log.** `lead_log.json` began on 21 October 2026. 15 of its leads have settled, all on one night: 12 landed against 78.3% said, and their 105 cross-game pairs landed together 66 times against 64 multiplied. Consistent with everything else, and far too small to say more.

**pplog.** Not in the repo. `pplog/` is gitignored and lives only on the machine that publishes, so the Paddy Power line record could not be used. Its settled lines would add player legs on the same nights; on the evidence here they would not change the cross-game verdict, but the same-player rows are worth adding when it is to hand.

**The cache.** `cache_backtest.tar.zst` unpacks to 9,117 matches with full statistics, December 2021 to 19 October 2026 (most of the weight from autumn 2024 on): football, NFL, darts and MLB. `acca_corr.py` walks it forward in date order. Every team leg is priced from that side's games strictly before kick-off, the way the page prices a team leg without a projection: the competition's sellable stats, the fixture's shared line (median of both sides' recent games, rounded, minus a half), the side's own sample (38 games, venue split when there are six or more), `model.price` on the record. Football player legs come from each starter's last ten appearances of 45 minutes or more, at whichever of 1+ or 2+ has a record nearest 65%. Builders are every three-leg combination of a side's six best-evidenced legs, priced off their joint count in the same sample, with the one weekend.py would have shown marked. A test checks that changing a match's own result leaves its legs' prices untouched.

**Separating calibration from correlation.** A multiple can miss its price because its legs are mispriced or because its legs move together. Each leg is first recalibrated (logistic on the logit of its stated chance, per sport and leg kind, the shape `model.RECORD_CALIBRATION` uses). Correlation is then what remains: whether two legs landed together more often than the product of their calibrated chances. The residual rho is the pooled correlation of the calibrated residuals, sum((y - q)(y' - q')) over sum(sqrt(q(1-q) q'(1-q'))), which is zero for independent legs at any price.

**Pair classes.** Inside one night, every pair of legs falls in exactly one of: same game and same team or player on a different stat; same game and same side but a different player or the team leg; same game on opposite sides; different games. Two lines on the same stat for the same side are left out, as mechanically linked. The sums are computed in closed form per group, and a test checks them against brute-force enumeration.

**Intervals.** Rates carry a Wilson 95% interval. Every ratio and every rho carries a cluster bootstrap 95% interval that resamples whole nights (2,000 draws, fixed seed), because a leg on one night sits in many pairs and many tickets and nothing is independent below the night.

**Earlier and later months.** The record covers under four weeks, so the fit and the confirmation both use the walk forward: fitted on nights before 1 April 2026, confirmed on nights after, with leg calibration refitted on the earlier nights only so the later months see nothing of themselves. A correction counts as holding only if its earlier-months rho excludes zero, the uncorrected later months are off by more than their interval, and the corrected later months land nearer. The builder correction additionally has to beat the joint count on the published builders.

## Limits

- The walk forward's legs are record-only. The page's football team legs also carry team strength, which is why the walk forward's football team legs land 1.11 times their stated chance against the published legs' 1.05. Correlation is measured against recalibrated chances, so this mostly washes out of the rho, but the builder section is exactly where it does not, which is why that correction is checked against the real record before anything else.
- The record is 25 nights. Every interval on the published tickets is wide, and the evens double split "same game" (13 tickets) has an interval of 0.00 to 1.64 because most of its weight sits on one or two nights.
- Basketball has published legs but no matches with statistics in the cache, so its cross-game evidence is two nights of the record.
- Parlays (same-game player legs, joint count per side, multiplied across sides) were checked only on the record: 27 of 86 landed against 30.6% said, landed/said 1.03 (0.46 to 1.65). The cross-side multiplication is the opposite-sides class, where rho is nil, so that part of their pricing is sound; the per-side joint count may share the builders' optimism and is not tested here.

## Files

- `acca_corr.py`: the analysis. Reads only `best_bets.json`, `lead_log.json` and `cache/`; writes only its report. It does not touch the page, the picks or any deployment.
- `tests/test_acca_corr.py`: 21 tests, synthetic data only.
- `calib/acca_correlation.md`: the generated tables, the same as below.

Running the existing suite (`python -B -m unittest discover -s tests`) rewrites `learned.json` as a side effect of `learner.model()`; that predates this branch, and the file is not part of this change.

## Every table

The output of `python -B acca_corr.py report`, headings moved down one level.

Generated by `python -B acca_corr.py report` on 2026-10-23 08:49 UTC. Bootstrap intervals resample whole nights, 2000 draws, seed 20261023.

### 1. Published multiples

373 settled multiples with no void leg, 25 nights. 'said' is the chance the site stated (one over its fair price); 'multiplied' is the product of the legs' own chances, which for an acca or double is the same number.

#### By category, legs, game

| category | legs | game | tickets | landed | rate (95% Wilson) | said | landed / said (95% by night) | multiplied | landed / multiplied |
|---|---|---|---|---|---|---|---|---|---|
| acca | 2 | cross game | 18 | 6 | 33.3% (16.3% to 56.3%) | 41.6% | 0.80 (0.36 to 1.43) | 41.6% | 0.80 (0.36 to 1.43) |
| acca | 3 | cross game | 92 | 41 | 44.6% (34.8% to 54.7%) | 31.2% | 1.43 (1.00 to 1.92) | 31.2% | 1.43 (1.00 to 1.92) |
| builder | 3 | same game | 63 | 34 | 54.0% (41.8% to 65.7%) | 49.4% | 1.09 (0.84 to 1.38) | 30.3% | 1.78 (1.34 to 2.32) |
| evens double | 2 | cross game | 101 | 52 | 51.5% (41.9% to 61.0%) | 50.7% | 1.01 (0.83 to 1.34) | 50.7% | 1.01 (0.83 to 1.34) |
| evens double | 2 | same game | 13 | 7 | 53.8% (29.1% to 76.8%) | 48.8% | 1.10 (0.00 to 1.64) | 48.8% | 1.10 (0.00 to 1.64) |
| parlay | 4 | same game | 86 | 27 | 31.4% (22.6% to 41.8%) | 30.6% | 1.03 (0.46 to 1.65) | 24.3% | 1.29 (0.58 to 2.07) |

#### By legs

| legs | tickets | landed | rate (95% Wilson) | said | landed / said (95% by night) | multiplied | landed / multiplied |
|---|---|---|---|---|---|---|---|
| 2 | 132 | 65 | 49.2% (40.9% to 57.7%) | 49.3% | 1.00 (0.81 to 1.26) | 49.3% | 1.00 (0.81 to 1.26) |
| 3 | 155 | 75 | 48.4% (40.7% to 56.2%) | 38.6% | 1.25 (1.00 to 1.56) | 30.9% | 1.57 (1.27 to 1.95) |
| 4 | 86 | 27 | 31.4% (22.6% to 41.8%) | 30.6% | 1.03 (0.46 to 1.65) | 24.3% | 1.29 (0.58 to 2.07) |

#### By game

| game | tickets | landed | rate (95% Wilson) | said | landed / said (95% by night) | multiplied | landed / multiplied |
|---|---|---|---|---|---|---|---|
| cross game | 211 | 99 | 46.9% (40.3% to 53.6%) | 41.5% | 1.13 (0.91 to 1.43) | 41.5% | 1.13 (0.91 to 1.43) |
| same game | 162 | 68 | 42.0% (34.6% to 49.7%) | 39.3% | 1.07 (0.85 to 1.30) | 28.6% | 1.47 (1.14 to 1.85) |

#### By sport

| sport | tickets | landed | rate (95% Wilson) | said | landed / said (95% by night) | multiplied | landed / multiplied |
|---|---|---|---|---|---|---|---|
| american-football | 87 | 34 | 39.1% (29.5% to 49.6%) | 37.7% | 1.04 (0.36 to 1.62) | 31.3% | 1.25 (0.46 to 1.92) |
| baseball | 37 | 14 | 37.8% (24.1% to 53.9%) | 37.1% | 1.02 (0.26 to 2.13) | 33.6% | 1.13 (0.29 to 2.54) |
| basketball | 22 | 8 | 36.4% (19.7% to 57.0%) | 38.1% | 0.95 (0.83 to 1.05) | 32.5% | 1.12 (1.06 to 1.16) |
| darts | 41 | 22 | 53.7% (38.7% to 67.9%) | 40.6% | 1.32 (1.02 to 1.72) | 34.5% | 1.55 (1.21 to 2.02) |
| football | 186 | 89 | 47.8% (40.8% to 55.0%) | 42.8% | 1.12 (0.86 to 1.40) | 39.2% | 1.22 (0.95 to 1.57) |

#### By kind

| kind | tickets | landed | rate (95% Wilson) | said | landed / said (95% by night) | multiplied | landed / multiplied |
|---|---|---|---|---|---|---|---|
| mixed | 21 | 6 | 28.6% (13.8% to 50.0%) | 40.4% | 0.71 (0.19 to 1.16) | 40.4% | 0.71 (0.19 to 1.16) |
| player | 123 | 43 | 35.0% (27.1% to 43.7%) | 35.8% | 0.98 (0.60 to 1.32) | 31.4% | 1.11 (0.69 to 1.48) |
| team | 229 | 118 | 51.5% (45.1% to 57.9%) | 43.1% | 1.20 (1.00 to 1.49) | 37.9% | 1.36 (1.13 to 1.77) |

### 2. Published legs

2564 distinct settled legs, each priced at its first sighting.

| sport | kind | legs | landed | rate (95% Wilson) | said | landed / said (95% by night) |
|---|---|---|---|---|---|---|
| american-football | player | 253 | 181 | 71.5% (65.7% to 76.7%) | 68.7% | 1.04 (0.98 to 1.13) |
| american-football | team | 85 | 55 | 64.7% (54.1% to 74.0%) | 66.8% | 0.97 (0.79 to 1.29) |
| baseball | player | 88 | 59 | 67.0% (56.7% to 76.0%) | 67.6% | 0.99 (0.72 to 1.25) |
| baseball | team | 13 | 7 | 53.8% (29.1% to 76.8%) | 68.8% | 0.78 (0.25 to 1.34) |
| basketball | player | 156 | 109 | 69.9% (62.3% to 76.5%) | 70.0% | 1.00 (0.96 to 1.13) |
| basketball | team | 29 | 22 | 75.9% (57.9% to 87.8%) | 67.3% | 1.13 (0.97 to 1.35) |
| darts | team | 190 | 126 | 66.3% (59.3% to 72.7%) | 62.5% | 1.06 (0.96 to 1.21) |
| football | player | 431 | 316 | 73.3% (68.9% to 77.3%) | 70.1% | 1.05 (0.95 to 1.11) |
| football | team | 1319 | 967 | 73.3% (70.9% to 75.6%) | 70.1% | 1.05 (1.02 to 1.10) |

#### Cross-game multiples against calibrated legs

The same tickets, 'said' now the product of each leg recalibrated on every published leg of its sport and kind. What is left is correlation and noise.

| category | legs | tickets | landed | rate (95% Wilson) | said | landed / said (95% by night) |
|---|---|---|---|---|---|---|
| acca | 2 | 18 | 6 | 33.3% (16.3% to 56.3%) | 44.2% | 0.75 (0.34 to 1.30) |
| acca | 3 | 92 | 41 | 44.6% (34.8% to 54.7%) | 35.4% | 1.26 (0.88 to 1.65) |
| evens double | 2 | 101 | 52 | 51.5% (41.9% to 61.0%) | 53.8% | 0.96 (0.78 to 1.27) |

### 3. Pairs from the published legs

| split | pair class | pairs | nights | both landed | both said | both calibrated | landed / said | landed / calibrated | residual rho |
|---|---|---|---|---|---|---|---|---|---|
| team + team | same game, same team or player, different stat | 2180 | 25 | 1211 | 1080 | 1180 | 1.12 (1.07 to 1.23) | 1.03 (0.98 to 1.13) | +0.128 (+0.086 to +0.164) |
| team + team | same game, opposite sides | 1467 | 24 | 773 | 733 | 800 | 1.05 (1.00 to 1.20) | 0.97 (0.91 to 1.10) | -0.018 (-0.090 to +0.047) |
| team + team | cross game, same night | 137162 | 23 | 69005 | 67396 | 73616 | 1.02 (0.96 to 1.10) | 0.94 (0.89 to 1.00) | +0.001 (-0.004 to +0.009) |
| player + player | same game, same team or player, different stat | 347 | 19 | 216 | 163 | 173 | 1.32 (1.15 to 1.55) | 1.25 (1.09 to 1.44) | +0.534 (+0.340 to +0.795) |
| player + player | same game, same side, different player or team leg | 1637 | 21 | 820 | 778 | 823 | 1.05 (0.88 to 1.20) | 1.00 (0.82 to 1.14) | +0.010 (-0.065 to +0.099) |
| player + player | same game, opposite sides | 1417 | 19 | 785 | 677 | 718 | 1.16 (1.05 to 1.37) | 1.09 (1.00 to 1.29) | -0.034 (-0.071 to +0.038) |
| player + player | cross game, same night | 44824 | 20 | 23306 | 21771 | 23045 | 1.07 (0.91 to 1.19) | 1.01 (0.87 to 1.11) | +0.004 (-0.004 to +0.027) |
| team + player | same game, same side, different player or team leg | 1848 | 22 | 929 | 890 | 962 | 1.04 (0.93 to 1.17) | 0.97 (0.88 to 1.10) | -0.002 (-0.055 to +0.092) |
| team + player | same game, opposite sides | 1551 | 21 | 819 | 746 | 807 | 1.10 (0.95 to 1.21) | 1.01 (0.90 to 1.13) | +0.016 (-0.062 to +0.114) |
| team + player | cross game, same night | 94724 | 22 | 49073 | 45892 | 49579 | 1.07 (0.98 to 1.18) | 0.99 (0.91 to 1.09) | -0.007 (-0.025 to +0.003) |
| sport = american-football | same game, same team or player, different stat | 227 | 11 | 137 | 103 | 109 | 1.34 (1.03 to 1.72) | 1.26 (0.97 to 1.60) | +0.470 (+0.256 to +0.763) |
| sport = american-football | same game, same side, different player or team leg | 758 | 11 | 364 | 347 | 367 | 1.05 (0.85 to 1.36) | 0.99 (0.79 to 1.29) | +0.042 (-0.111 to +0.185) |
| sport = american-football | same game, opposite sides | 622 | 10 | 345 | 281 | 298 | 1.23 (0.90 to 1.63) | 1.16 (0.83 to 1.58) | +0.099 (+0.023 to +0.198) |
| sport = american-football | cross game, same night | 8079 | 3 | 3606 | 3792 | 3925 | 0.95 (0.85 to 1.04) | 0.92 (0.79 to 1.04) | -0.016 (-0.054 to +0.013) |
| sport = baseball | same game, same team or player, different stat | 71 | 7 | 45 | 33 | 32 | 1.37 (0.88 to 1.86) | 1.39 (0.90 to 1.89) | +0.977 (+0.685 to +1.261) |
| sport = baseball | same game, same side, different player or team leg | 343 | 7 | 146 | 157 | 155 | 0.93 (0.51 to 1.48) | 0.94 (0.52 to 1.51) | +0.047 (-0.097 to +0.198) |
| sport = baseball | same game, opposite sides | 226 | 7 | 106 | 105 | 103 | 1.01 (0.55 to 1.55) | 1.03 (0.56 to 1.57) | +0.072 (-0.195 to +0.365) |
| sport = darts | same game, same team or player, different stat | 185 | 6 | 87 | 73 | 82 | 1.20 (0.98 to 1.54) | 1.07 (0.88 to 1.37) | +0.070 (-0.069 to +0.207) |
| sport = darts | same game, opposite sides | 91 | 6 | 47 | 38 | 41 | 1.23 (0.84 to 1.67) | 1.13 (0.77 to 1.59) | -0.040 (-0.303 to +0.218) |
| sport = darts | cross game, same night | 3098 | 6 | 1257 | 1186 | 1349 | 1.06 (0.89 to 1.32) | 0.93 (0.79 to 1.17) | +0.008 (-0.020 to +0.069) |
| sport = football | same game, same team or player, different stat | 1930 | 25 | 1097 | 980 | 1071 | 1.12 (1.07 to 1.21) | 1.02 (0.98 to 1.11) | +0.124 (+0.072 to +0.161) |
| sport = football | same game, same side, different player or team leg | 1787 | 20 | 949 | 874 | 965 | 1.09 (0.94 to 1.15) | 0.98 (0.86 to 1.04) | -0.020 (-0.055 to +0.052) |
| sport = football | same game, opposite sides | 2920 | 23 | 1584 | 1455 | 1595 | 1.09 (1.01 to 1.15) | 0.99 (0.93 to 1.05) | -0.032 (-0.094 to +0.019) |
| sport = football | cross game, same night | 141445 | 20 | 76571 | 71655 | 78343 | 1.07 (1.00 to 1.12) | 0.98 (0.92 to 1.02) | -0.002 (-0.005 to +0.005) |

#### tonight.py's leads

15 settled leads over 1 night(s): 12 landed (80.0%, 54.8% to 93.0%), the page said 78.3%. Cross-game pairs among them, against the page's own chances:

105 pairs, 66 both landed against 64 multiplied: 1.03, too few nights for an interval. The log was started on 21 October 2026, so it holds very few settled nights so far.

### 4. Walk forward over the cache

9117 matches, 48144 team legs and 307949 football player legs, 355929 of them priced 1.25 to 3.0 (the range used for legs and pairs below), 613 nights, 2021-12-05 to 2026-10-19.

#### Legs

| sport | kind | legs | landed | rate (95% Wilson) | said | landed / said (95% by night) |
|---|---|---|---|---|---|---|
| american-football | team | 5417 | 3276 | 60.5% (59.2% to 61.8%) | 60.2% | 1.00 (0.98 to 1.03) |
| baseball | team | 508 | 280 | 55.1% (50.8% to 59.4%) | 61.7% | 0.89 (0.81 to 0.99) |
| darts | team | 2096 | 1164 | 55.5% (53.4% to 57.6%) | 60.8% | 0.91 (0.87 to 0.95) |
| football | player | 307949 | 176437 | 57.3% (57.1% to 57.5%) | 59.1% | 0.97 (0.97 to 0.97) |
| football | team | 39959 | 24394 | 61.0% (60.6% to 61.5%) | 54.9% | 1.11 (1.10 to 1.12) |

#### Pairs

| split | pair class | pairs | nights | both landed | both said | both calibrated | landed / said | landed / calibrated | residual rho |
|---|---|---|---|---|---|---|---|---|---|
| team + team | same game, same team or player, different stat | 112865 | 530 | 42278 | 35025 | 41684 | 1.21 (1.19 to 1.23) | 1.01 (1.00 to 1.03) | +0.033 (+0.027 to +0.039) |
| team + team | same game, opposite sides | 113225 | 380 | 41613 | 35123 | 41886 | 1.18 (1.16 to 1.21) | 0.99 (0.97 to 1.01) | +0.002 (-0.005 to +0.008) |
| team + team | cross game, same night | 7042936 | 431 | 2618180 | 2177716 | 2593374 | 1.20 (1.18 to 1.23) | 1.01 (0.99 to 1.03) | +0.000 (-0.000 to +0.001) |
| player + player | same game, same team or player, different stat | 438218 | 512 | 148453 | 153496 | 144084 | 0.97 (0.96 to 0.97) | 1.03 (1.02 to 1.04) | +0.047 (+0.043 to +0.050) |
| player + player | same game, same side, different player or team leg | 4359620 | 477 | 1432509 | 1526886 | 1433124 | 0.94 (0.93 to 0.95) | 1.00 (0.99 to 1.01) | +0.005 (+0.003 to +0.006) |
| player + player | same game, opposite sides | 4189841 | 453 | 1373552 | 1468261 | 1377834 | 0.94 (0.93 to 0.94) | 1.00 (0.99 to 1.01) | +0.003 (+0.002 to +0.004) |
| player + player | cross game, same night | 261278499 | 421 | 86181630 | 91458587 | 85859691 | 0.94 (0.93 to 0.95) | 1.00 (0.99 to 1.01) | +0.000 (-0.000 to +0.000) |
| team + player | same game, same side, different player or team leg | 1247652 | 416 | 440920 | 406090 | 437299 | 1.09 (1.08 to 1.10) | 1.01 (1.00 to 1.02) | +0.011 (+0.009 to +0.014) |
| team + player | same game, opposite sides | 1134395 | 403 | 394452 | 369048 | 397303 | 1.07 (1.06 to 1.08) | 0.99 (0.98 to 1.00) | -0.001 (-0.003 to +0.001) |
| team + player | cross game, same night | 81204460 | 416 | 28485969 | 26629168 | 28306204 | 1.07 (1.06 to 1.08) | 1.01 (1.00 to 1.02) | -0.000 (-0.000 to +0.000) |
| sport = american-football | same game, same team or player, different stat | 12803 | 163 | 4804 | 4638 | 4680 | 1.04 (0.98 to 1.08) | 1.03 (0.98 to 1.07) | +0.049 (+0.033 to +0.066) |
| sport = american-football | same game, opposite sides | 13860 | 116 | 5069 | 5013 | 5055 | 1.01 (0.96 to 1.06) | 1.00 (0.95 to 1.05) | -0.004 (-0.022 to +0.014) |
| sport = american-football | cross game, same night | 242792 | 78 | 89210 | 88110 | 88949 | 1.01 (0.96 to 1.07) | 1.00 (0.95 to 1.06) | -0.000 (-0.004 to +0.005) |
| sport = baseball | same game, same team or player, different stat | 464 | 34 | 174 | 177 | 141 | 0.98 (0.81 to 1.18) | 1.23 (1.02 to 1.49) | +0.292 (+0.198 to +0.406) |
| sport = baseball | same game, opposite sides | 402 | 24 | 120 | 153 | 122 | 0.78 (0.55 to 1.02) | 0.98 (0.69 to 1.29) | -0.029 (-0.143 to +0.092) |
| sport = baseball | cross game, same night | 5447 | 23 | 1564 | 2080 | 1657 | 0.75 (0.63 to 0.89) | 0.94 (0.79 to 1.11) | -0.000 (-0.021 to +0.034) |
| sport = darts | same game, same team or player, different stat | 3020 | 66 | 970 | 1115 | 930 | 0.87 (0.79 to 0.95) | 1.04 (0.94 to 1.14) | +0.051 (+0.016 to +0.085) |
| sport = darts | same game, opposite sides | 1860 | 35 | 612 | 702 | 580 | 0.87 (0.77 to 0.99) | 1.06 (0.93 to 1.21) | +0.037 (-0.001 to +0.086) |
| sport = darts | cross game, same night | 59691 | 50 | 18546 | 22123 | 18434 | 0.84 (0.75 to 0.92) | 1.01 (0.91 to 1.10) | +0.001 (-0.007 to +0.012) |
| sport = football | same game, same team or player, different stat | 534796 | 533 | 184783 | 182590 | 180016 | 1.01 (1.00 to 1.02) | 1.03 (1.02 to 1.03) | +0.044 (+0.041 to +0.047) |
| sport = football | same game, same side, different player or team leg | 5607272 | 477 | 1873429 | 1932975 | 1870423 | 0.97 (0.96 to 0.98) | 1.00 (0.99 to 1.01) | +0.006 (+0.005 to +0.007) |
| sport = football | same game, opposite sides | 5421339 | 458 | 1803816 | 1866563 | 1811265 | 0.97 (0.96 to 0.97) | 1.00 (0.99 to 1.00) | +0.002 (+0.001 to +0.003) |
| sport = football | cross game, same night | 340699638 | 437 | 114269252 | 117131818 | 113776485 | 0.98 (0.97 to 0.98) | 1.00 (1.00 to 1.01) | +0.000 (-0.000 to +0.000) |

#### Football team legs by stat pair, same team

The twenty most common pairs. Builders are made of these.

| stats | pairs | landed / calibrated | residual rho |
|---|---|---|---|
| Corner kicks + Shots on target | 7614 | 1.07 (1.04 to 1.10) | +0.069 (+0.045 to +0.092) |
| Shots on target + Total shots | 7541 | 1.17 (1.14 to 1.20) | +0.205 (+0.183 to +0.227) |
| Corner kicks + Total shots | 7540 | 1.11 (1.08 to 1.14) | +0.148 (+0.126 to +0.170) |
| Corner kicks + Yellow cards | 7194 | 0.97 (0.94 to 1.00) | -0.040 (-0.064 to -0.017) |
| Shots on target + Yellow cards | 7192 | 0.99 (0.96 to 1.02) | -0.030 (-0.052 to -0.007) |
| Total shots + Yellow cards | 7126 | 1.00 (0.97 to 1.03) | -0.025 (-0.047 to -0.005) |
| Corner kicks + Offsides | 3462 | 1.00 (0.96 to 1.03) | -0.020 (-0.051 to +0.011) |
| Offsides + Total shots | 3462 | 1.04 (1.00 to 1.08) | +0.008 (-0.024 to +0.041) |
| Offsides + Shots on target | 3458 | 1.03 (0.98 to 1.07) | +0.005 (-0.027 to +0.037) |
| Offsides + Yellow cards | 3295 | 1.02 (0.97 to 1.06) | +0.009 (-0.020 to +0.040) |
| Corner kicks + Fouls | 3137 | 0.97 (0.93 to 1.01) | +0.025 (-0.007 to +0.056) |
| Fouls + Total shots | 3137 | 0.97 (0.93 to 1.01) | -0.010 (-0.043 to +0.022) |
| Fouls + Shots on target | 3133 | 0.96 (0.92 to 1.00) | -0.040 (-0.070 to -0.010) |
| Fouls + Yellow cards | 2970 | 1.04 (0.99 to 1.09) | +0.106 (+0.064 to +0.145) |
| Fouls + Offsides | 2865 | 0.96 (0.92 to 1.01) | -0.008 (-0.045 to +0.028) |
| Corner kicks + Throw-ins | 1473 | 0.86 (0.79 to 0.93) | +0.023 (-0.032 to +0.078) |
| Shots on target + Throw-ins | 1473 | 0.88 (0.81 to 0.94) | +0.024 (-0.033 to +0.080) |
| Throw-ins + Total shots | 1473 | 0.87 (0.81 to 0.93) | -0.014 (-0.067 to +0.038) |
| Fouls + Throw-ins | 1466 | 0.81 (0.75 to 0.87) | -0.040 (-0.097 to +0.014) |
| Throw-ins + Yellow cards | 1377 | 0.90 (0.83 to 0.97) | +0.013 (-0.038 to +0.066) |

#### Random cross-game tickets, team legs, one leg per game

Forty tickets a night at each size, drawn with a fixed seed. First against the product of the legs' own prices, then against the product of calibrated legs, which leaves only correlation.

| legs | tickets | landed | rate (95% Wilson) | said | landed / said (95% by night) |
|---|---|---|---|---|---|
| 2 | 17240 | 6288 | 36.5% (35.8% to 37.2%) | 31.5% | 1.16 (1.11 to 1.20) |
| 3 | 14840 | 3210 | 21.6% (21.0% to 22.3%) | 17.6% | 1.23 (1.16 to 1.30) |
| 4 | 12520 | 1558 | 12.4% (11.9% to 13.0%) | 9.8% | 1.27 (1.17 to 1.38) |
| 5 | 10880 | 903 | 8.3% (7.8% to 8.8%) | 5.5% | 1.51 (1.38 to 1.66) |

| legs | tickets | landed | rate (95% Wilson) | said | landed / said (95% by night) |
|---|---|---|---|---|---|
| 2 | 17240 | 6288 | 36.5% (35.8% to 37.2%) | 36.6% | 1.00 (0.96 to 1.04) |
| 3 | 14840 | 3210 | 21.6% (21.0% to 22.3%) | 22.1% | 0.98 (0.92 to 1.03) |
| 4 | 12520 | 1558 | 12.4% (11.9% to 13.0%) | 13.4% | 0.93 (0.86 to 1.00) |
| 5 | 10880 | 903 | 8.3% (7.8% to 8.8%) | 8.2% | 1.02 (0.92 to 1.12) |

#### Same-team builders priced by co-occurrence

Every qualifying three-leg combination, and the one weekend.py would have shown per side ('shown'). 'said' is the joint count in the sample; 'multiplied' is the product of the three legs.

| sport | kind | tickets | landed | rate (95% Wilson) | said | landed / said (95% by night) | multiplied | landed / multiplied |
|---|---|---|---|---|---|---|---|---|
| american-football | every combination | 6374 | 1685 | 26.4% (25.4% to 27.5%) | 36.5% | 0.72 (0.66 to 0.80) | 22.8% | 1.16 (1.05 to 1.28) |
| american-football | shown | 851 | 287 | 33.7% (30.6% to 37.0%) | 45.9% | 0.73 (0.67 to 0.80) | 25.2% | 1.34 (1.22 to 1.46) |
| baseball | shown | 49 | 18 | 36.7% (24.7% to 50.7%) | 43.2% | 0.85 (0.48 to 1.15) | 27.5% | 1.34 (0.75 to 1.81) |
| darts | every combination | 399 | 84 | 21.1% (17.3% to 25.3%) | 36.5% | 0.58 (0.43 to 0.73) | 25.4% | 0.83 (0.62 to 1.05) |
| darts | shown | 343 | 103 | 30.0% (25.4% to 35.1%) | 42.3% | 0.71 (0.60 to 0.82) | 26.4% | 1.14 (0.96 to 1.30) |
| football | every combination | 31123 | 8416 | 27.0% (26.6% to 27.5%) | 36.3% | 0.74 (0.72 to 0.77) | 17.4% | 1.56 (1.49 to 1.62) |
| football | shown | 6158 | 1916 | 31.1% (30.0% to 32.3%) | 43.1% | 0.72 (0.69 to 0.75) | 17.9% | 1.74 (1.67 to 1.80) |

### 5. Corrections fitted before 2026-04-01, confirmed after

#### Residual correlation by pair class

rho fitted on nights before the cut, leg calibration refitted on those nights only, then applied to the later nights.

| pair class | multiplied by the page | rho fitted (earlier) | pairs (later) | landed / calibrated (later) | landed / corrected (later) | holds |
|---|---|---|---|---|---|---|
| same game, same team or player, different stat | no | +0.045 (+0.041 to +0.049) | 262880 | 1.03 (1.02 to 1.04) | 1.00 (0.99 to 1.01) | yes |
| same game, same side, different player or team leg | no | +0.005 (+0.004 to +0.007) | 2867607 | 1.01 (1.00 to 1.02) | 1.00 (0.99 to 1.01) | no |
| same game, opposite sides | yes | +0.002 (+0.001 to +0.004) | 2761881 | 1.00 (0.99 to 1.01) | 1.00 (0.99 to 1.01) | no |
| cross game, same night | yes | -0.000 (-0.000 to +0.000) | 200359989 | 1.01 (1.00 to 1.02) | 1.01 (1.00 to 1.02) | no |

Later-month random cross-game tickets, against the calibrated product and then with the fitted cross-game rho (-0.0001) applied:

| legs | tickets | landed | rate (95% Wilson) | said | landed / said (95% by night) |
|---|---|---|---|---|---|
| 2 | 6920 | 2434 | 35.2% (34.1% to 36.3%) | 36.8% | 0.96 (0.90 to 1.01) |
| 3 | 6400 | 1301 | 20.3% (19.4% to 21.3%) | 22.2% | 0.92 (0.83 to 1.00) |
| 4 | 5560 | 716 | 12.9% (12.0% to 13.8%) | 13.5% | 0.95 (0.86 to 1.05) |
| 5 | 5080 | 383 | 7.5% (6.8% to 8.3%) | 8.3% | 0.91 (0.78 to 1.04) |

| legs | tickets | landed | rate (95% Wilson) | said | landed / said (95% by night) |
|---|---|---|---|---|---|
| 2 | 6920 | 2434 | 35.2% (34.1% to 36.3%) | 36.8% | 0.96 (0.90 to 1.01) |
| 3 | 6400 | 1301 | 20.3% (19.4% to 21.3%) | 22.2% | 0.92 (0.83 to 1.00) |
| 4 | 5560 | 716 | 12.9% (12.0% to 13.8%) | 13.5% | 0.95 (0.86 to 1.05) |
| 5 | 5080 | 383 | 7.5% (6.8% to 8.3%) | 8.3% | 0.91 (0.78 to 1.04) |

#### Builder correction

logit P = a + b logit(joint count) + c logit(product of legs), fitted on the walk forward's shown builders before the cut: a=-0.083, b=0.812, c=0.376. Holds only if it beats the joint count on both test sets.

| test set | tickets | landed | said | corrected | landed / said | landed / corrected | log loss said | log loss corrected |
|---|---|---|---|---|---|---|---|---|
| walk forward, later months | 4275 | 31.1% | 42.1% | 29.1% | 0.74 (0.71 to 0.77) | 1.07 (1.03 to 1.11) | 0.6420 | 0.6176 |
| published builders | 63 | 54.0% | 49.4% | 39.5% | 1.09 (0.84 to 1.38) | 1.36 (1.04 to 1.74) | 0.7035 | 0.7408 |

Holds: no.

#### Cross-game pairs by month

| month | pairs | landed / calibrated | residual rho |
|---|---|---|---|
| 2024-09 | 2767 | 1.23 (1.12 to 1.41) | +0.001 (-0.014 to +0.022) |
| 2024-10 | 14732 | 0.82 (0.78 to 1.36) | +0.012 (-0.082 to +0.027) |
| 2024-11 | 1832 | 1.02 (0.78 to 1.25) | -0.026 (-0.065 to +0.059) |
| 2024-12 | 3797 | 0.83 (0.78 to 0.93) | -0.006 (-0.014 to +0.001) |
| 2025-01 | 2955 | 0.76 (0.71 to 1.25) | +0.011 (-0.087 to +0.045) |
| 2025-02 | 13631 | 1.17 (0.45 to 1.19) | +0.003 (-0.337 to +0.015) |
| 2025-03 | 26098 | 1.07 (1.02 to 1.18) | -0.009 (-0.049 to +0.005) |
| 2025-04 | 23736 | 1.04 (0.92 to 1.18) | -0.003 (-0.014 to +0.003) |
| 2025-05 | 196922 | 1.06 (1.01 to 1.11) | -0.000 (-0.003 to +0.004) |
| 2025-06 | 164927 | 1.13 (0.94 to 1.14) | +0.003 (-0.008 to +0.003) |
| 2025-07 | 1148684 | 0.96 (0.89 to 1.07) | +0.002 (+0.000 to +0.003) |
| 2025-08 | 2212409 | 0.96 (0.88 to 1.02) | +0.001 (-0.000 to +0.004) |
| 2025-09 | 6649435 | 1.00 (0.98 to 1.03) | -0.000 (-0.001 to -0.000) |
| 2025-10 | 10989641 | 1.02 (0.97 to 1.05) | +0.000 (-0.001 to +0.001) |
| 2025-11 | 18276244 | 1.00 (0.98 to 1.02) | -0.000 (-0.001 to +0.000) |
| 2025-12 | 14980191 | 0.99 (0.97 to 1.02) | -0.000 (-0.001 to +0.000) |
| 2026-01 | 23410077 | 1.03 (0.99 to 1.05) | +0.000 (-0.000 to +0.001) |
| 2026-02 | 30699736 | 0.99 (0.97 to 1.01) | -0.000 (-0.000 to +0.000) |
| 2026-03 | 40345736 | 0.98 (0.97 to 1.00) | -0.000 (-0.001 to +0.000) |
| 2026-04 | 52153363 | 1.02 (1.00 to 1.04) | +0.000 (-0.000 to +0.000) |
| 2026-05 | 49442605 | 0.98 (0.97 to 1.01) | -0.000 (-0.000 to +0.000) |
| 2026-06 | 203747 | 0.88 (0.77 to 0.99) | +0.012 (-0.005 to +0.030) |
| 2026-07 | 2984941 | 0.93 (0.90 to 0.99) | +0.001 (-0.002 to +0.004) |
| 2026-08 | 29800174 | 1.02 (0.99 to 1.05) | +0.000 (-0.001 to +0.001) |
| 2026-09 | 50889516 | 1.02 (1.01 to 1.04) | +0.000 (-0.000 to +0.000) |
| 2026-10 | 14885643 | 1.00 (0.96 to 1.02) | -0.000 (-0.000 to +0.001) |

