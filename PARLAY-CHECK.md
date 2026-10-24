# Parlay joint-count check

Does the per-side joint count that prices a same-game parlay share the selection optimism ACCA-CORRELATION.md found in the builders? And if it does, does a correction fitted on earlier months hold on later months and on the published parlays? Written 23 October 2026 on the `parlay-check` branch. Every number here is reproduced by

    python -B parlay_check.py walk --cache DIR --out WALK.json    # about 15 minutes, DIR an unpacked cache_backtest.tar.zst
    python -B parlay_check.py report --out WALK.json              # a few seconds; also writes calib/parlay_check.md

## Verdict

**Pricing is left alone.** In the walk-forward the joint count is optimistic, much as it was for the builders. But the pre-set correction, fitted on the earlier months of the parlays the page would actually have published, comes back as no change. The corrections that do help in the walk-forward do not help on the 86 published parlays.

1. **The joint count is optimistic where it is chosen from many.** Among each fixture's best parlay in the walk-forward, the tickets land at 0.57 of their stated chance (0.49 to 0.66) and their sides at 0.75 (0.70 to 0.79). Across every candidate the sides land at 0.82 (0.78 to 0.85). This is the builders' problem: the best of a few hundred combinations on 10 to 38 matches is partly the luckiest joint count.
2. **The parlay the page publishes is chosen more carefully, and is much less optimistic.** `best_parlay` ranks on the product of each side's Wilson lower bound at a selection-adjusted z, which favours bigger samples. The walk-forward slate pick (one per sport per night) lands at 0.83 of said (0.61 to 1.07): 37 of 144 against 31.0%. The published record is at 1.03 (0.46 to 1.71): 27 of 86 against 30.6%.
3. **The pre-set test finds nothing to correct.** Both corrections were fitted on slate picks before 1 April 2026 (79 tickets over 72 nights). The shrink towards the product of the legs fits k = 0, which is the page as it is. The recalibration fits a slope of 1.87, but it moves the later-month predictions by under a point and changes log loss by +0.0030 (−0.0060 to +0.0125) on later slate picks and +0.0004 (−0.0084 to +0.0171) on the published tickets.
4. **Fitted on the larger fixture-best set instead (exploratory), the corrections help the walk-forward and not the record.** The shrink goes all the way, k = infinity: drop the joint count and multiply the legs. It improves later fixture bests by −0.034 (−0.046 to −0.021) and later slate picks by −0.024 (−0.064 to +0.020), but makes the 86 published tickets worse by +0.009 (−0.044 to +0.073). The recalibration does the same, +0.033 on the published tickets. This is the builders' result again: it helps the walk-forward copy and hurts the real record.
5. **The one pattern worth watching is the split ticket.** Legs on both teams means two joint counts multiplied together. In the walk-forward, split slate picks landed 9 of 56 against about 30% said (1+3: 0.48, 0.12 to 0.95; 2+2: 0.58, 0.12 to 1.09). One-team 4-leg slate picks landed at 1.01 (0.69 to 1.34). The published record leans the same way: one-team tickets 17 of 44 against 30.2%, split tickets 10 of 42 against about 31%. Fitted on earlier split fixture bests, the shrink (k = 400) and the recalibration lower log loss on every split test set. Every interval except the walk-forward fixture bests crosses zero, though: published split shrink −0.019 (−0.075 to +0.052) on 13 rebuilt tickets, recalibration −0.004 (−0.112 to +0.130) on 42. I also picked this subgroup after seeing all the data, later months and the record included. So it is a hypothesis to test, not a confirmed result.

Nothing is wired in. To act on point 5, the test to set up in advance is: price a split parlay at the product of its legs, or shrink it with k fixed at 400, and score it on published split tickets settled from now on. On the present spread, a gain the size of the walk-forward's (about 0.03 in log loss) needs roughly 300 settled split tickets before its interval would clear zero.

## How parlays are built and priced

`parlay.py`, called from `weekend.picks` once per sport for every snapshot (`besttrack.py snapshot`, fixtures in the next 48 hours):

- **Legs.** One alt-line rung per player and stat, on the markets the book ladders (`LADDERED`, narrowed to the competition's board). Each rung is the highest one the player clears in at least 65% of his recent appearances (`LEG_FLOOR`), with a Wilson guard of 0.45 and a floor of 0.6 of his median. Each player keeps his longest-priced rung (at least 1.30), and each team keeps its five longest-priced players (`POOL_PER_TEAM`).
- **Tickets.** Every 4-leg combination of the two teams' pools. Each team's legs are counted jointly over the matches that carry all of them (`team_joint`), and each side needs at least 10 matches and 4 joint hits. The two sides' rates are multiplied, and a ticket must price at 3.0 or more. The quoted fair price is one over that product, with no smoothing or calibration.
- **The pick.** `best_parlay` takes the candidate with the highest product of each side's Wilson lower bound, at a z adjusted for how many distinct player-and-stat questions the slate asked (`weekend.selection_z`).
- **Settlement** (`besttrack.py`): a player with no statistics or no minutes voids his leg, and any appearance counts.

## Method

**The walk-forward is the live code.** For every finished match with lineups in the cache, `parlay_check.py walk` builds the fixture as `run.py` would. Each side's player records come from `hitrates.player_form` with `before` set to kick-off, 38 matches for football and 20 for the NFL and MLB (update.py's windows). Then it calls `parlay.parlays_for` for the candidates and `parlay.best_parlay` for the picks. Parlays carry no strength adjustment, so unlike the builders' copy this is the page's own code on the inputs it would have had. Two departures from live are unavoidable:

- **Squad.** The live build keeps only today's squad (`current_squad_only`), which in the past would be a look-ahead. The replay keeps players who appeared in one of the side's last three matches before kick-off (`recent_squad`). Without that filter, men who had left the club filled the pools and most football tickets came back void.
- **Slate.** Live picks one parlay per sport from whatever kicks off in the next 48 hours, at every snapshot. The replay picks one per sport per calendar night.

Each candidate is settled from its own match's lineup by besttrack's rule. A ticket with any void leg is left out rather than repriced, as in ACCA-CORRELATION.md.

**What the walk-forward covers.** 7,787 finished matches with lineups (football, NFL, MLB) produced candidates on 1,606 fixtures: 90,640 candidates, of which 39,692 settled with no void leg, over 225 nights. Fixtures without candidates are mostly the older ones, where the cached history is too thin for a 10-match joint count. Football voids are common, because a 4-leg ticket on a rotated cup side often has one unused substitute.

**The published record.** `best_bets.json`: 86 distinct parlays settled with no void leg, over 18 nights between 27 September and 21 October 2026 (47 NFL, 20 MLB, 10 football, 9 NBA). The record stores the ticket price and each leg's own record, but not each side's joint count. The walk-forward rebuilt 22 of the 86 exactly (same four legs at the same joint price), and only those can carry the per-side shrink. The rest differ because the live build had different data when it ran. The recalibration and the multiply-the-legs price need only the ticket price and its legs, so they are scored on all 86. The 22 rebuilt tickets landed 5 times, so they are not a representative subset.

**The corrections.**
- **Shrink:** each side's joint count is pulled towards the product of that side's own leg rates, p = (hits + k q) / (total + k), and the sides are then multiplied. k = 0 is the page as it is; k = infinity multiplies the legs. k is chosen on log loss from a grid.
- **Recalibration:** logit P = a + b logit(said) + c logit(product of the legs), the shape used for the builders, starting from the page (0, 1, 0).

Both are fitted on nights before 1 April 2026 and scored on nights from then on, and on the published tickets. A correction counts as holding only if it lowers log loss on every test set.

**Intervals.** Rates carry a Wilson 95% interval. Ratios and log-loss differences carry a bootstrap 95% interval that resamples whole nights (2,000 draws, seed 20261023).

## Limits

- The replay's slate (one pick per sport per night) is close to the live snapshot, not the same. The live window is 48 hours and is redrawn at every publish, which is why 146 published entries come down to 86 distinct settled tickets.
- `recent_squad` is a proxy. A player injured for the last three matches drops out of the replay's pool and stays in the live one.
- The walk-forward is two-thirds football (96 of 144 slate picks), while the published record is mostly NFL and MLB. Basketball has no lineups with statistics in the cache, so its 9 published tickets have no walk-forward behind them.
- 86 published tickets over 18 nights cannot separate a ratio of 0.8 from 1.0. Every interval on them is wide.

## Files

- `parlay_check.py`: the walk-forward and the report. It reads the cache and `best_bets.json` and writes only its own output (`--out`, and `calib/parlay_check.md`). The walk's rows (about 90 MB) are not committed.
- `tests/test_parlay_check.py`: 16 tests, synthetic data only.
- `calib/parlay_check.md`: the generated tables, reproduced below.

Running the existing test suite rewrites `learned.json` as a side effect of `learner.model()`. That file was restored and is not part of this change.

## Every table

The output of `python -B parlay_check.py report`.

Generated by `python -B parlay_check.py report` on 2026-10-23 15:12 UTC. Intervals resample whole nights, 2000 draws, seed 20261023.

### 1. Landed against said

| set | tickets | nights | landed | rate (95% Wilson) | said | landed / said (95% by night) |
|---|---:|---:|---:|---:|---:|---:|
| walk forward, every candidate | 39692 | 225 | 6380 | 16.1% (15.7% to 16.4%) | 24.1% | 0.67 (0.59 to 0.76) |
| walk forward, each fixture's best | 730 | 193 | 127 | 17.4% (14.8% to 20.3%) | 30.3% | 0.57 (0.49 to 0.66) |
| walk forward, each slate's pick (what is published) | 144 | 130 | 37 | 25.7% (19.3% to 33.4%) | 31.0% | 0.83 (0.61 to 1.07) |
| slate picks, football | 96 | 96 | 24 | 25.0% (17.4% to 34.5%) | 31.2% | 0.80 (0.53 to 1.07) |
| slate picks, american-football | 41 | 41 | 11 | 26.8% (15.7% to 41.9%) | 30.6% | 0.88 (0.47 to 1.34) |
| slate picks, baseball | 7 | 7 | 2 | 28.6% (8.2% to 64.1%) | 30.6% | 0.93 (0.00 to 2.01) |
| published, settled with no void leg | 86 | 18 | 27 | 31.4% (22.6% to 41.8%) | 30.6% | 1.03 (0.46 to 1.71) |
| candidates, priced by multiplying legs | 39692 | 225 | 6380 | 16.1% (15.7% to 16.4%) | 23.4% | 0.69 (0.60 to 0.78) |
| slate picks, priced by multiplying legs | 144 | 130 | 37 | 25.7% (19.3% to 33.4%) | 25.4% | 1.01 (0.74 to 1.31) |
| published, priced by multiplying legs | 86 | 18 | 27 | 31.4% (22.6% to 41.8%) | 24.3% | 1.29 (0.58 to 2.14) |

### 2. Per side: the joint count on its own

One row per side of a ticket: did every leg on that side land, against the side's joint count (hits / total).

| set | tickets | nights | landed | rate (95% Wilson) | said | landed / said (95% by night) |
|---|---:|---:|---:|---:|---:|---:|
| sides of every candidate | 78731 | 225 | 32235 | 40.9% (40.6% to 41.3%) | 50.1% | 0.82 (0.78 to 0.85) |
| sides of each fixture's best | 1228 | 193 | 469 | 38.2% (35.5% to 40.9%) | 51.1% | 0.75 (0.70 to 0.79) |
| sides of slate picks | 200 | 130 | 72 | 36.0% (29.7% to 42.9%) | 45.3% | 0.80 (0.65 to 0.95) |
| sides of slate picks, 4 legs on one side | 88 | 84 | 28 | 31.8% (23.0% to 42.1%) | 31.5% | 1.01 (0.69 to 1.34) |
| sides of slate picks, 2 or 3 legs | 85 | 53 | 28 | 32.9% (23.9% to 43.5%) | 50.7% | 0.65 (0.46 to 0.87) |
| sides of slate picks, 1 leg | 27 | 27 | 16 | 59.3% (40.7% to 75.5%) | 72.8% | 0.81 (0.56 to 1.06) |

### 3. Calibration of the slate picks

| stated | tickets | said | landed |
|---|---:|---:|---:|
| 20-30% | 38 | 0.271 | 0.158 |
| 30-40% | 106 | 0.324 | 0.292 |

### 4. Corrections, fitted before 2026-04-01 on slate picks

The published record holds 86 settled tickets with no void leg; the walk forward rebuilt 22 of them exactly (same four legs, same joint price), and only those can carry per-side joint counts for the shrink.

Shrink: k = 0 pseudo-matches towards the product of the side's own legs. Recalibration: logit P = +0.642 +1.866 logit(said) -0.042 logit(multiplied). Training set: 79 slate picks over 72 nights.

| test set | correction | tickets | nights | landed | said | corrected | log loss said | log loss corrected | corrected minus said (95% by night) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| walk forward, later slate picks | shrink | 65 | 58 | 0.200 | 0.315 | 0.315 | 0.5322 | 0.5322 | -0.0000 (-0.0000 to +0.0000) |
| walk forward, later slate picks | recalibration | 65 | 58 | 0.200 | 0.315 | 0.319 | 0.5322 | 0.5352 | +0.0030 (-0.0060 to +0.0125) |
| walk forward, later fixture bests | shrink | 424 | 99 | 0.156 | 0.304 | 0.304 | 0.4910 | 0.4910 | +0.0000 (-0.0000 to +0.0000) |
| walk forward, later fixture bests | recalibration | 424 | 99 | 0.156 | 0.304 | 0.300 | 0.4910 | 0.4902 | -0.0008 (-0.0054 to +0.0037) |
| published | shrink | 22 | 14 | 0.227 | 0.298 | 0.298 | 0.5407 | 0.5407 | +0.0000 (+0.0000 to +0.0000) |
| published | recalibration | 86 | 18 | 0.314 | 0.306 | 0.303 | 0.6196 | 0.6200 | +0.0004 (-0.0084 to +0.0171) |

Holds on every test set: shrink no, recalibration no.

### 5. By shape: one team or split across both

| set | tickets | nights | landed | rate (95% Wilson) | said | landed / said (95% by night) |
|---|---:|---:|---:|---:|---:|---:|
| walk forward, every candidate, 4 | 653 | 136 | 130 | 19.9% (17.0% to 23.1%) | 27.9% | 0.71 (0.56 to 0.87) |
| walk forward, every candidate, 1+3 | 16854 | 205 | 2770 | 16.4% (15.9% to 17.0%) | 24.6% | 0.67 (0.59 to 0.76) |
| walk forward, every candidate, 2+2 | 22185 | 204 | 3480 | 15.7% (15.2% to 16.2%) | 23.7% | 0.66 (0.58 to 0.75) |
| walk forward, each fixture's best, 4 | 232 | 113 | 49 | 21.1% (16.4% to 26.8%) | 30.9% | 0.68 (0.51 to 0.88) |
| walk forward, each fixture's best, 1+3 | 231 | 116 | 38 | 16.5% (12.2% to 21.8%) | 30.6% | 0.54 (0.38 to 0.70) |
| walk forward, each fixture's best, 2+2 | 267 | 127 | 40 | 15.0% (11.2% to 19.8%) | 29.6% | 0.51 (0.37 to 0.66) |
| walk forward, slate picks, 4 | 88 | 84 | 28 | 31.8% (23.0% to 42.1%) | 31.5% | 1.01 (0.69 to 1.34) |
| walk forward, slate picks, 1+3 | 27 | 27 | 4 | 14.8% (5.9% to 32.5%) | 30.6% | 0.48 (0.12 to 0.95) |
| walk forward, slate picks, 2+2 | 29 | 27 | 5 | 17.2% (7.6% to 34.5%) | 29.8% | 0.58 (0.12 to 1.09) |
| published, 4 | 44 | 13 | 17 | 38.6% (25.7% to 53.4%) | 30.2% | 1.28 (0.34 to 2.16) |
| published, 1+3 | 20 | 8 | 6 | 30.0% (14.5% to 51.9%) | 31.6% | 0.95 (0.17 to 1.50) |
| published, 2+2 | 22 | 8 | 4 | 18.2% (7.3% to 38.5%) | 30.4% | 0.60 (0.00 to 1.96) |

### 6. Exploratory: the same corrections fitted on earlier fixture bests

Not the pre-set test. Section 4 fits on the earlier slate picks because that is what is published; these fits use the larger set of each fixture's best, and the split-ticket rows were chosen after section 5 had been seen, so none of this counts as confirmation.

All shapes: k = 1e+06; recalibration -0.711 +1.359 -0.436. Holds: shrink no, recalibration no.

| test set | correction | tickets | nights | landed | said | corrected | log loss said | log loss corrected | corrected minus said (95% by night) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| walk forward, later slate picks | shrink (k infinite: multiply the legs) | 65 | 58 | 0.200 | 0.315 | 0.240 | 0.5322 | 0.5083 | -0.0238 (-0.0638 to +0.0199) |
| walk forward, later slate picks | recalibration | 65 | 58 | 0.200 | 0.315 | 0.221 | 0.5322 | 0.4998 | -0.0324 (-0.0778 to +0.0197) |
| walk forward, later fixture bests | shrink (k infinite: multiply the legs) | 424 | 99 | 0.156 | 0.304 | 0.242 | 0.4910 | 0.4574 | -0.0336 (-0.0459 to -0.0208) |
| walk forward, later fixture bests | recalibration | 424 | 99 | 0.156 | 0.304 | 0.209 | 0.4910 | 0.4413 | -0.0497 (-0.0640 to -0.0343) |
| published | shrink (k infinite: multiply the legs) | 86 | 18 | 0.314 | 0.306 | 0.243 | 0.6196 | 0.6284 | +0.0088 (-0.0436 to +0.0734) |
| published | recalibration | 86 | 18 | 0.314 | 0.306 | 0.210 | 0.6196 | 0.6521 | +0.0325 (-0.0594 to +0.1400) |

Split tickets only: k = 400; recalibration -1.085 +2.014 -1.162. Holds: shrink yes, recalibration yes.

| test set | correction | tickets | nights | landed | said | corrected | log loss said | log loss corrected | corrected minus said (95% by night) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| walk forward, later slate picks | shrink | 25 | 23 | 0.200 | 0.310 | 0.255 | 0.5267 | 0.5133 | -0.0134 (-0.0597 to +0.0448) |
| walk forward, later slate picks | recalibration | 25 | 23 | 0.200 | 0.310 | 0.196 | 0.5267 | 0.4893 | -0.0374 (-0.1148 to +0.0649) |
| walk forward, later fixture bests | shrink | 308 | 91 | 0.153 | 0.303 | 0.249 | 0.4890 | 0.4585 | -0.0305 (-0.0437 to -0.0164) |
| walk forward, later fixture bests | recalibration | 308 | 91 | 0.153 | 0.303 | 0.192 | 0.4890 | 0.4345 | -0.0545 (-0.0798 to -0.0288) |
| published | shrink | 13 | 10 | 0.154 | 0.300 | 0.246 | 0.4743 | 0.4550 | -0.0193 (-0.0745 to +0.0515) |
| published | recalibration | 42 | 11 | 0.238 | 0.310 | 0.206 | 0.5610 | 0.5565 | -0.0044 (-0.1119 to +0.1303) |
