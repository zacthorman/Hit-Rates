# Deep backtest: context, matchups, structure (2 Nov 2026)

Second stage of research/BACKTEST-2026-11-02.md, run on 1,353 NBA and 1,225 NFL box scores joined to every settled pplog row.

# Stage 2: conditional and structural edges against Paddy Power (NBA / NFL)

Data window priced: 20 Oct - 2 Nov 2026 (NBA 88 games, NFL 27 games). Raw history: NBA 1,353 games (Mar 2025 - 2 Nov 2026), NFL 1,225 games (2020 - 2026).
Scripts: `/home/claude/bt/deep/scripts/` (d0 build ... d20 overlap; `d99_assemble.py` writes this file). Cached tables: `/home/claude/bt/deep/data/`.

## Summary

* **Joins.** Every settled pplog row was matched to the raw box score and to pre-game features: NBA 28,950 of 28,950 settled rows (88 of 88 games), NFL 8,955 of 8,955 (27 of 27). The settled `value` equals the raw box-score stat in 100% of rows. The only unmatched rows are voids (players who did not play; NBA 683, NFL ~200).
* **Strongest structural finding (robust as a description, unproven as profit): Paddy's main line over-reacts to the last few games.** If you regress Paddy's NBA main line on the player's last-3, last-10 and last-20 means, it puts about twice the outcome-optimal weight on the last 3 games (points 0.27 vs 0.13; PRA 0.29 vs 0.18; P+A 0.33 vs 0.16), with less weight on the longer window.
  The same pattern shows up in five places: lines set above the player's baseline lose on the over and win on the under, minutes trends, players promoted to starter, NFL target trends, and the projection model's edge.
  A pre-specified rule built on it, **RULE U** (main under when Paddy's line is >= 0.25 sd above a baseline fitted only on raw history), made +5.0% at 1.60-2.20: n=1,669, 88 games, 90% CI -1.8% to +11.9%, H1 +2.5%, H2 +7.2%. All 18 of 18 robustness cells were positive and 11 of 18 positive in both halves.
  It is still +1.4% without its top 3 players. The CI includes zero. It does not replicate in NFL (small n).
* **Drift after a miss (live rule): no support from 1,300 games of history.** We reproduced 34 settled bets with 33 won (the live log says 35 / 34).
  A logit fitted on 93k raw-history rung-games expects 24.4 wins, and the book expects 24.2. The raw-history model is no better than the book on the wider k10>=8 population.
  In history a miss lowers the next-game hit rate (logit -0.21 beyond the 10-game count), and Paddy's own drift is too small. On the evidence, the perfect record is luck plus in-sample selection. Since it went live it is 3 of 4 (book expected 2.9).
* **Why the miss happened (raw history, no prices):** cold-shooting misses revert worst (71.7%) and low-shot-volume misses best (77.8%). Both are small effects.
  What matters is **today's role**: misses by players who start today hit 76.9% next game, misses by players on the bench today 63.8%. Players who usually start but came off the bench in the miss game hit 62.5%.
  Big misses (>= 1 sd short) hit 63.8% against 75.5% for the rest. So a role-change miss does not revert, as the user suspected. A cold-shooting miss is not more "random" than other misses.
* **Ladder: no structural edge.** Rungs below the main line carry about 11% more margin than the main line. Their hit rate matches the probability implied by Paddy's own devigged main line almost exactly (e.g. 0.713 vs 0.714). Every distance bucket loses.
* **Projection model:** worse than Paddy on Brier (0.252 vs 0.247), but it holds independent information. In a blend fitted on H1 the model's logit weight is 0.27 (SE 0.05).
  On H2 only, blend edge >= 3% made +11.8% (n=236, 34 games, CI -7% to +30%). Most of what it finds is the same reversion signal as RULE U (86% overlap).
* **Teammate absences ("Siakam question"):** outputs do rise when regulars are missing (+2.5 pts swing from none to 30+ pts absent). Paddy's line rises by the same amount (0.29 sd line vs 0.33 sd outcome), so nothing is left over.
* **NFL QB rushing unders: downgraded.** At the lines Paddy sets, raw history gives an under rate of 49-55%, against a 54.6% break-even. The +24% in the log is most likely variance.

Hypotheses tested in this stage: about 25 pre-stated hypotheses and about 450 table slices (raw and priced). At a 90% interval, about 45 slices would look "WORKING" by chance. Only findings that agree across independent angles, and that have a mechanism, are treated as more than noise here.


# 1. Why the miss happened (NBA drift after a miss)

**Hypothesis (pre-stated).** A player who cleared a rung in 8+ of 10 and then missed it rebounds more when the miss was circumstantial (low minutes from fouls or a blowout, cold shooting on normal volume). He does not rebound when it was a role change.
Reconstruction: for every played NBA game in the raw data, every ladder rung (points 9.5-34.5 by 5; reb/ast 1.5/3.5-11.5 by 2; 3PM 0.5-4.5; stl/blk 0.5/1.5; R+A, P+R, P+A, PRA ladders), we took k10 = clears in the previous 10 played games. We kept rows with k10>=8 and the previous game within 20 days.
Why-categories, applied in order of priority: A minutes < 75% of his previous-10 norm; C shot volume (FGA, or 3PA for threes) < 75% of norm; B FG% (3P%) >= 10 points below norm on normal volume; D other.
Hit rates here are raw-history evidence about frequencies, not profit.

## 1a. Next-game hit rate after a miss vs after a hit, matched on the 9 games before (k9). Raw history before 20 Oct 2026, all ladder rungs.

| slice | n | games | hit | ci90 | mean_line_gap |
|---|---|---|---|---|---|
| k9=9, prev HIT (k10=10) | 29993 | 1140 | 0.907 | [0.902, 0.912] | 1.99 |
| k9=9, prev MISS (k10=9) | 3177 | 852 | 0.802 | [0.785, 0.818] | 1.21 |
| k9=8, prev HIT (k10=9) | 27795 | 1146 | 0.826 | [0.821, 0.832] | 1.21 |
| k9=8, prev MISS (k10=8) | 6552 | 1101 | 0.713 | [0.700, 0.725] | 0.82 |
| k9=7, prev HIT (k10=8) | 25875 | 1153 | 0.732 | [0.726, 0.739] | 0.82 |

mean_line_gap = (player mean of last 10 - rung) / sd of last 10, how far the rung sits below his average.


Logit hit ~ miss_prev + gap + k9 + stat (cluster SE by game), n=93392: coef miss_prev = -0.210 (SE 0.042); i.e. a miss last game changes next-game hit probability by about -3.4 points at a base of 80%.


## 1b. After a miss (k10>=8 entering today, so k9>=8 before the miss): by WHY he missed (raw history)

| slice | n | games | hit | ci90 | mean_line_gap |
|---|---|---|---|---|---|
| all misses | 9729 | 1114 | 0.742 | [0.731, 0.753] | 0.95 |
| A low minutes | 2548 | 604 | 0.735 | [0.710, 0.759] | 0.96 |
| B cold shooting | 1506 | 542 | 0.717 | [0.687, 0.746] | 0.95 |
| C low shot volume | 1879 | 631 | 0.778 | [0.754, 0.801] | 0.95 |
| D normal minutes, other | 3796 | 1008 | 0.738 | [0.724, 0.754] | 0.95 |
| control: prev HIT, k9>=8 | 57788 | 1148 | 0.868 | [0.864, 0.873] | 1.61 |

### Extra conditions on the miss game / today (raw history, misses only)

| slice | n | games | hit | ci90 | mean_line_gap |
|---|---|---|---|---|---|
| prev game blowout |margin|>=20 | 2668 | 441 | 0.756 | [0.734, 0.778] | 0.97 |
|   not: prev game blowout |margin|>=20 | 7061 | 1000 | 0.737 | [0.724, 0.749] | 0.94 |
| prev game 5+ fouls | 667 | 258 | 0.73 | [0.688, 0.770] | 0.96 |
|   not: prev game 5+ fouls | 9062 | 1106 | 0.743 | [0.731, 0.754] | 0.95 |
| prev game was 2nd of b2b | 1369 | 313 | 0.77 | [0.741, 0.798] | 0.94 |
|   not: prev game was 2nd of b2b | 8360 | 1063 | 0.737 | [0.725, 0.749] | 0.95 |
| today is b2b | 1297 | 259 | 0.754 | [0.722, 0.786] | 0.95 |
|   not: today is b2b | 8432 | 1046 | 0.74 | [0.728, 0.752] | 0.95 |
| prev mins < 75% norm AND blowout | 891 | 215 | 0.728 | [0.687, 0.774] | 0.99 |
|   not: prev mins < 75% norm AND blowout | 8838 | 1102 | 0.743 | [0.732, 0.755] | 0.95 |
| prev mins < 75% norm, NOT blowout, NOT fouls | 1597 | 433 | 0.739 | [0.709, 0.770] | 0.94 |
|   not: prev mins < 75% norm, NOT blowout, NOT fouls | 8132 | 1110 | 0.742 | [0.731, 0.754] | 0.95 |
| started 80%+ of prior 10 but came off bench in miss game | 371 | 131 | 0.625 | [0.554, 0.697] | 0.95 |
|   not: started 80%+ of prior 10 but came off bench in miss game | 9358 | 1112 | 0.746 | [0.735, 0.758] | 0.95 |
| minutes trend down: last3 before miss < 85% of norm | 633 | 299 | 0.724 | [0.689, 0.756] | 0.89 |
|   not: minutes trend down: last3 before miss < 85% of norm | 9096 | 1108 | 0.743 | [0.731, 0.755] | 0.95 |
| near miss: within 1 of the rung | 4317 | 1085 | 0.748 | [0.736, 0.759] | 1.02 |
|   not: near miss: within 1 of the rung | 5412 | 958 | 0.737 | [0.722, 0.753] | 0.89 |
| big miss: >= 1 sd below the rung | 1076 | 460 | 0.638 | [0.603, 0.673] | 0.68 |
|   not: big miss: >= 1 sd below the rung | 8653 | 1113 | 0.755 | [0.744, 0.765] | 0.98 |
| rung >=1 sd below his mean (easy rung) | 3769 | 944 | 0.817 | [0.803, 0.830] | 1.25 |
|   not: rung >=1 sd below his mean (easy rung) | 5960 | 1090 | 0.694 | [0.681, 0.707] | 0.76 |
| rung within 0.5 sd of his mean (hard rung) | 459 | 327 | 0.556 | [0.514, 0.597] | 0.38 |
|   not: rung within 0.5 sd of his mean (hard rung) | 9270 | 1108 | 0.751 | [0.740, 0.762] | 0.98 |

### Today: still starting vs not (uses TODAY's starter flag, known ~30 min before tip)

| slice | n | games | hit | ci90 | mean_line_gap |
|---|---|---|---|---|---|
| misses: starts today | 7737 | 1078 | 0.769 | [0.757, 0.781] | 0.96 |
| misses: bench today | 1992 | 751 | 0.638 | [0.613, 0.661] | 0.9 |
| misses: started miss game, benched today | 291 | 138 | 0.646 | [0.576, 0.710] | 0.93 |

### By stat (misses vs hits, k9>=8)

| slice | n | games | hit | ci90 | mean_line_gap |
|---|---|---|---|---|---|
| assists after MISS | 1072 | 662 | 0.758 | [0.737, 0.781] | 0.97 |
| assists after HIT | 7062 | 1136 | 0.878 | [0.871, 0.885] | 1.6 |
| blocks after MISS | 189 | 175 | 0.646 | [0.587, 0.702] | 0.86 |
| blocks after HIT | 464 | 380 | 0.724 | [0.688, 0.759] | 1.22 |
| pa after MISS | 832 | 521 | 0.749 | [0.723, 0.775] | 0.95 |
| pa after HIT | 5627 | 1081 | 0.882 | [0.874, 0.890] | 1.75 |
| points after MISS | 1056 | 620 | 0.763 | [0.741, 0.785] | 0.94 |
| points after HIT | 6876 | 1117 | 0.876 | [0.869, 0.884] | 1.68 |
| pr after MISS | 1065 | 616 | 0.738 | [0.714, 0.763] | 0.96 |
| pr after HIT | 6847 | 1112 | 0.877 | [0.870, 0.886] | 1.7 |
| pra after MISS | 921 | 535 | 0.745 | [0.720, 0.769] | 0.95 |
| pra after HIT | 5852 | 1072 | 0.87 | [0.861, 0.880] | 1.7 |
| ra after MISS | 1823 | 807 | 0.758 | [0.738, 0.777] | 0.98 |
| ra after HIT | 12779 | 1141 | 0.885 | [0.879, 0.890] | 1.65 |
| rebounds after MISS | 952 | 586 | 0.725 | [0.699, 0.750] | 0.94 |
| rebounds after HIT | 5224 | 1106 | 0.863 | [0.853, 0.871] | 1.53 |
| steals after MISS | 538 | 417 | 0.673 | [0.640, 0.706] | 0.88 |
| steals after HIT | 1249 | 746 | 0.725 | [0.704, 0.746] | 1.19 |
| threes after MISS | 1281 | 743 | 0.739 | [0.717, 0.761] | 0.94 |
| threes after HIT | 5808 | 1120 | 0.833 | [0.824, 0.841] | 1.35 |

### why x stat family (misses only)

| slice | n | games | hit | ci90 | mean_line_gap |
|---|---|---|---|---|---|
| scoring / A low minutes | 1020 | 263 | 0.759 | [0.716, 0.800] | 0.97 |
| scoring / B cold shooting | 1125 | 363 | 0.718 | [0.681, 0.754] | 0.96 |
| scoring / C low shot volume | 1295 | 403 | 0.78 | [0.750, 0.812] | 0.94 |
| scoring / D normal minutes, other | 434 | 213 | 0.712 | [0.659, 0.763] | 0.89 |
| threes / A low minutes | 316 | 244 | 0.709 | [0.663, 0.755] | 0.93 |
| threes / B cold shooting | 381 | 308 | 0.714 | [0.672, 0.755] | 0.92 |
| threes / C low shot volume | 584 | 419 | 0.772 | [0.743, 0.799] | 0.97 |
| other / A low minutes | 1212 | 469 | 0.722 | [0.692, 0.750] | 0.96 |
| other / D normal minutes, other | 3362 | 987 | 0.742 | [0.726, 0.758] | 0.95 |

## 1c. Same reconstruction inside the pplog period (20 Oct - 2 Nov 2026, raw outcomes, no prices)

| slice | n | games | hit | ci90 | mean_line_gap |
|---|---|---|---|---|---|
| after MISS (k10>=8) | 752 | 75 | 0.677 | [0.631, 0.722] | 0.92 |
| after HIT (k9>=8) | 3725 | 78 | 0.853 | [0.833, 0.872] | 1.59 |
|   A low minutes | 284 | 58 | 0.507 | [0.448, 0.575] | 0.86 |
|   B cold shooting | 73 | 27 | 0.849 | [0.774, 0.919] | 0.99 |
|   C low shot volume | 156 | 44 | 0.814 | [0.734, 0.879] | 0.96 |
|   D normal minutes, other | 239 | 65 | 0.736 | [0.675, 0.795] | 0.94 |

**Reading 1a-1c.** Matched on the 9 games before, a miss last game is worth about the same as one fewer clear in the window, plus a small extra recency penalty (logit -0.21 with rung distance and stat held constant). The miss is informative, and it does not "revert" beyond the 10-game rate.
The why-categories barely separate (71.7% to 77.8%). The hypothesis that cold-shooting misses revert most is rejected: they revert slightly *least*. Role variables do separate: today's starting status (76.9% vs 63.8%), being benched in the miss game (62.5%), and the size of the miss.
In the pplog period itself (early season), low-minutes misses hit only 50.7% (n=284). Early-season minutes cuts are often real rotation changes.


## Priced side

## 1d. The live rule's 34 settled bets: what the raw-history model expected

Model fitted on 93392 raw-history rung-games before 20 Oct 2026: logit(hit) ~ miss_prev + gap + k9 + stat + bench-today.

| n | won | mean_book_implied | mean_hist_model | expected_wins_model | expected_wins_book | P_33plus_wins_if_model_right |
|---|---|---|---|---|---|---|
| 34 | 33 | 0.712 | 0.717 | 24.4 | 24.2 | 0.00013 |

Why each priced bet's previous game was a miss (raw box score of the miss game):

| why | n | won | avg_price | p_hist |
|---|---|---|---|---|
| A low minutes | 12 | 12 | 1.519 | 0.677 |
| B cold shooting | 1 | 0 | 1.4 | 0.685 |
| C low shot volume | 9 | 9 | 1.487 | 0.722 |
| D normal minutes, other | 12 | 12 | 1.326 | 0.756 |

Other context of the 34: starts today 0.79, rung below his 10-game mean by 0.81 sd on average, k10 (pplog) {8.0: 29, 9.0: 5}, k10 (raw recompute) {8: 27, 9: 4, 7: 3}.

| date | player | stat | line | f_price | prev_price | prev_y | mean10 | why | min_ratio | p_hist | value | result |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-10-23 | Ryan Rollins | Assists | 3.5 | 1.33 | 1.22 | 3 | 5.2 | D normal minutes, other | 0.76 | 0.77 | 6 | win |
| 2026-10-24 | Victor Wembanyama | Points | 19.5 | 1.29 | 1.22 | 12 | 24.5 | C low shot volume | 0.91 | 0.74 | 25 | win |
| 2026-10-24 | Tari Eason | Points | 9.5 | 2.2 | 2 | 2 | 12 | A low minutes | 0.1 | 0.49 | 12 | win |
| 2026-10-24 | Devin Vassell | Assists | 1.5 | 1.57 | 1.4 | 1 | 2.7 | D normal minutes, other | 0.87 | 0.76 | 2 | win |
| 2026-10-24 | Dejounte Murray | Rebounds | 3.5 | 1.25 | 1.14 | 3 | 5.2 | D normal minutes, other | 1.19 | 0.77 | 6 | win |
| 2026-10-24 | Zion Williamson | Rebounds | 3.5 | 1.29 | 1.17 | 3 | 4.9 | D normal minutes, other | 1.07 | 0.73 | 5 | win |
| 2026-10-24 | Bam Adebayo | Rebounds | 7.5 | 1.5 | 1.4 | 6 | 9.2 | A low minutes | 0.73 | 0.65 | 8 | win |
| 2026-10-24 | Bam Adebayo | Three pointers made | 0.5 | 1.22 | 1.14 | 0 | 1.6 | A low minutes | 0.73 | 0.72 | 2 | win |
| 2026-10-24 | Evan Mobley | Blocks | 0.5 | 1.2 | 1.12 | 0 | 2 | D normal minutes, other | 0.92 | 0.7 | 3 | win |
| 2026-10-24 | Ryan Rollins | Steals | 0.5 | 1.3 | 1.14 | 1 | 1.3 | D normal minutes, other | 1.13 | 0.68 | 1 | win |
| 2026-10-25 | Matas Buzelis | Points | 9.5 | 1.2 | 1.12 | 7 | 16.3 | A low minutes | 0.57 | 0.8 | 21 | win |
| 2026-10-25 | Jeremiah Fears | Points | 9.5 | 1.44 | 1.36 | 7 | 21.7 | A low minutes | 0.74 | 0.78 | 10 | win |
| 2026-10-25 | Collin Murray-Boyles | Assists | 1.5 | 1.67 | 1.44 | 0 | 2.2 | A low minutes | 0.71 | 0.61 | 2 | win |
| 2026-10-25 | Collin Murray-Boyles | Rebounds and assists | 6.5 | 1.62 | 1.3 | 3 | 8 | A low minutes | 0.71 | 0.58 | 9 | win |
| 2026-10-25 | Collin Murray-Boyles | Rebounds | 3.5 | 1.3 | 1.17 | 3 | 5.8 | A low minutes | 0.71 | 0.65 | 7 | win |
| 2026-10-27 | Ace Bailey | Points | 9.5 | 1.44 | 1.36 | 17 | 15.3 | C low shot volume | 0.97 | 0.84 | 17 | win |
| 2026-10-28 | Victor Wembanyama | Rebounds | 7.5 | 1.2 | 1.11 | 7 | 10.6 | D normal minutes, other | 0.78 | 0.8 | 10 | win |
| 2026-10-28 | Mikal Bridges | Assists | 1.5 | 1.29 | 1.22 | 1 | 3 | D normal minutes, other | 1.07 | 0.78 | 4 | win |
| 2026-10-29 | Tre Jones | Points | 9.5 | 2.25 | 1.91 | 8 | 16.4 | A low minutes | 0.62 | 0.63 | 11 | win |
| 2026-10-29 | Josh Giddey | Assists | 5.5 | 1.29 | 1.2 | 4 | 9 | D normal minutes, other | 0.76 | 0.82 | 11 | win |
| 2026-10-30 | James Harden | Rebounds | 3.5 | 1.5 | 1.36 | 2 | 4.9 | D normal minutes, other | 0.91 | 0.74 | 5 | win |
| 2026-10-30 | Jarrett Allen | Points | 9.5 | 1.33 | 1.22 | 8 | 13.5 | C low shot volume | 1.02 | 0.74 | 14 | win |
| 2026-10-30 | Trey Murphy III | Rebounds | 3.5 | 1.4 | 1.33 | 1 | 5.3 | D normal minutes, other | 0.87 | 0.77 | 5 | win |
| 2026-10-30 | Donovan Mitchell | Points | 19.5 | 1.33 | 1.25 | 19 | 25.2 | C low shot volume | 0.85 | 0.82 | 22 | win |
| 2026-10-30 | Jakob Poeltl | Rebounds | 3.5 | 1.2 | 1.11 | 2 | 5.4 | A low minutes | 0.5 | 0.72 | 11 | win |
| 2026-10-30 | Collin Murray-Boyles | Rebounds | 3.5 | 1.33 | 1.22 | 2 | 6.1 | A low minutes | 0.59 | 0.68 | 5 | win |
| 2026-10-31 | Kevin Durant | Points | 19.5 | 1.4 | 1.17 | 18 | 25.2 | C low shot volume | 0.85 | 0.81 | 28 | win |
| 2026-10-31 | Tari Eason | Points | 9.5 | 1.73 | 1.44 | 5 | 11.8 | C low shot volume | 1.07 | 0.5 | 11 | win |
| 2026-10-31 | Brandin Podziemski | Points | 14.5 | 1.8 | 1.53 | 8 | 17.9 | C low shot volume | 0.98 | 0.7 | 21 | win |
| 2026-10-31 | Brandin Podziemski | Three pointers made | 1.5 | 1.44 | 1.36 | 0 | 2.2 | C low shot volume | 0.98 | 0.7 | 4 | win |
| 2026-11-01 | Kyle Kuzma | Assists | 1.5 | 1.3 | 1.22 | 1 | 3.2 | A low minutes | 0.7 | 0.81 | 3 | win |
| 2026-11-01 | Pascal Siakam | Points | 19.5 | 1.4 | 1.33 | 13 | 22.9 | B cold shooting | 0.93 | 0.69 | 17 | lose |
| 2026-11-02 | RJ Barrett | Rebounds | 3.5 | 1.3 | 1.2 | 3 | 6.5 | D normal minutes, other | 0.92 | 0.76 | 10 | win |
| 2026-11-02 | RJ Barrett | Points | 19.5 | 1.62 | 1.44 | 9 | 22 | C low shot volume | 0.92 | 0.66 | 22 | win |

## 1e. Priced population: NBA alt overs, n10=10, k10>=8, 1.15-3.0, one rung per player-stat-game (closest to 2.0)

| slice | n | games | hit | avg_p | be_hit | roi | ci90 | roi_H1 | n_H1 | roi_H2 | n_H2 | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| no prev logged | 211 | 41 | 0.682 | 1.371 | 0.746 | -0.083 | [-0.155, -0.003] | -0.079 | 196 | -0.126 | 15 | LOSER |
| other | 10 | 5 | 0.7 | 1.307 | 0.771 | -0.113 | [-0.542, +0.156] |  | 0 | -0.113 | 10 | tiny |
| prev MISS, drift>=5% | 33 | 21 | 0.97 | 1.437 | 0.713 | 0.395 | [+0.283, +0.481] | 0.421 | 15 | 0.373 | 18 | WORKING |
| prev MISS, no drift | 50 | 33 | 0.68 | 1.338 | 0.758 | -0.098 | [-0.256, +0.055] | -0.232 | 20 | -0.008 | 30 | noise |
| prev WIN, drift>=5% | 78 | 41 | 0.692 | 1.337 | 0.754 | -0.081 | [-0.204, +0.026] | -0.05 | 40 | -0.114 | 38 | noise |
| prev WIN, no drift | 392 | 72 | 0.712 | 1.315 | 0.769 | -0.073 | [-0.133, -0.019] | -0.043 | 175 | -0.098 | 217 | LOSER |
| all | 774 | 87 | 0.711 | 1.339 | 0.758 | -0.059 | [-0.098, -0.020] | -0.052 | 446 | -0.068 | 328 | LOSER |

All qualifying rungs (not deduped):

| slice | n | games | hit | avg_p | be_hit | roi | ci90 | roi_H1 | n_H1 | roi_H2 | n_H2 | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| no prev logged | 280 | 41 | 0.704 | 1.36 | 0.753 | -0.054 | [-0.133, +0.035] | -0.046 | 259 | -0.148 | 21 | noise |
| other | 11 | 5 | 0.727 | 1.294 | 0.779 | -0.088 | [-0.542, +0.158] |  | 0 | -0.088 | 11 | tiny |
| prev MISS, drift>=5% | 38 | 21 | 0.974 | 1.416 | 0.724 | 0.379 | [+0.283, +0.454] | 0.407 | 18 | 0.354 | 20 | WORKING |
| prev MISS, no drift | 55 | 33 | 0.673 | 1.33 | 0.762 | -0.112 | [-0.266, +0.033] | -0.241 | 22 | -0.027 | 33 | noise |
| prev WIN, drift>=5% | 81 | 41 | 0.691 | 1.332 | 0.756 | -0.085 | [-0.207, +0.024] | -0.038 | 42 | -0.137 | 39 | noise |
| prev WIN, no drift | 434 | 72 | 0.71 | 1.318 | 0.769 | -0.079 | [-0.147, -0.017] | -0.06 | 203 | -0.096 | 231 | LOSER |

## 1f. Mechanism: after a MISS, rungs that drifted vs did not (priced population, one rung per player-stat-game)

| prev | drift | n | hit | avg_p | main_line_move | share_main_line_down | rung_minus_main | ml_known | lead_h | prev_lead_h | days |
|---|---|---|---|---|---|---|---|---|---|---|---|
| lose | False | 51 | 0.667 | 1.338 | 0.2 | 0.06 | -1.84 | 0.96 | 9.3 | 9.4 | 2.1 |
| lose | True | 33 | 0.97 | 1.437 | -0.8 | 0.55 | -1.9 | 0.91 | 9.8 | 9.8 | 2 |
| void | False | 5 | 0.6 | 1.347 | 0.2 | 0 | -1.6 | 1 | 2.4 | 9.9 | 1.7 |
| void | True | 5 | 0.8 | 1.267 | -1.6 | 0.8 | -2.2 | 1 | 9.4 | 2.4 | 3 |
| win | False | 400 | 0.718 | 1.313 | 0.22 | 0.08 | -2.01 | 0.98 | 9 | 9.4 | 2 |
| win | True | 79 | 0.696 | 1.336 | -0.65 | 0.46 | -2.05 | 0.99 | 8.1 | 9.9 | 2 |

main_line_move = today's Paddy main line minus the previous game's for the same player-stat; rung_minus_main = rung - today's main line.


### After a miss: by how the main line moved (one rung per player-stat-game)

| slice | n | games | hit | avg_p | be_hit | roi | ci90 | roi_H1 | n_H1 | roi_H2 | n_H2 | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| main line down | 21 | 15 | 0.905 | 1.505 | 0.69 | 0.375 | [+0.163, +0.568] | 0.358 | 10 | 0.39 | 11 | tiny |
| main line same | 48 | 34 | 0.771 | 1.304 | 0.772 | -0.006 | [-0.164, +0.123] | -0.064 | 18 | 0.029 | 30 | noise |
| main line up | 10 | 9 | 0.5 | 1.384 | 0.731 | -0.307 | [-0.676, +0.094] | -0.72 | 5 | 0.107 | 5 | tiny |
| no main line | 5 | 4 | 1 | 1.526 | 0.66 | 0.526 | [+0.392, +0.613] | 0.618 | 3 | 0.388 | 2 | tiny |

### After a WIN: by how the main line moved

| slice | n | games | hit | avg_p | be_hit | roi | ci90 | roi_H1 | n_H1 | roi_H2 | n_H2 | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| main line down | 67 | 43 | 0.761 | 1.302 | 0.775 | -0.022 | [-0.122, +0.069] | -0.066 | 38 | 0.034 | 29 | noise |
| main line same | 301 | 69 | 0.708 | 1.303 | 0.775 | -0.085 | [-0.149, -0.021] | -0.01 | 131 | -0.143 | 170 | LOSER |
| main line up | 90 | 52 | 0.678 | 1.359 | 0.747 | -0.092 | [-0.219, +0.027] | -0.127 | 41 | -0.062 | 49 | noise |
| no main line | 21 | 18 | 0.81 | 1.386 | 0.728 | 0.115 | [-0.115, +0.312] | 0.086 | 11 | 0.146 | 10 | tiny |

## 1g. Raw-history logit applied to the whole priced k10>=8 alt-over population (one rung per player-stat-game)

n=563: mean p_hist 0.763, mean implied 0.764, actual hit 0.723.

| slice | n | games | hit | avg_p | be_hit | roi | ci90 | roi_H1 | n_H1 | roi_H2 | n_H2 | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| p_hist*price >= 1.05 | 169 | 57 | 0.669 | 1.436 | 0.708 | -0.044 | [-0.136, +0.053] | -0.026 | 79 | -0.059 | 90 | noise |
| 1.00-1.05 | 90 | 50 | 0.689 | 1.314 | 0.767 | -0.096 | [-0.215, +0.020] | -0.049 | 46 | -0.144 | 44 | noise |
| < 1.00 | 304 | 70 | 0.763 | 1.265 | 0.795 | -0.04 | [-0.089, +0.004] | -0.028 | 127 | -0.049 | 177 | noise |
| p_hist*price >= 1.05 and prev MISS | 17 | 14 | 0.882 | 1.588 | 0.651 | 0.418 | [+0.147, +0.631] | 0.278 | 8 | 0.543 | 9 | tiny |

Drift rule since going live (31 Oct 12:00 UTC): 4 bets, 3 won, book expected 2.9, ROI +0.054; P(>= that many wins if book fair) = 0.684.

**Conclusions (direction 1).**
* The rule's record (33 of 34 here) is far above what any history-based model expects (24.4 expected; P(>=33) = 0.0001 if the model is right). But the rule was chosen because it was perfect on 20-30 Oct, so that p-value means nothing. After selection it is 3 of 4 at book-expected 2.9.
* Mechanism check: the drift is Paddy lowering its main line in 55% of cases. Across the full priced population, alt overs after the main line went down made +24% when k10>=8 (n=46, overlapping the rule).
  But the general version, RULE A (alt over below main when Paddy's line is below the history baseline), loses -8%. The raw-history logit gives no edge on the 563-row priced k10>=8 population. Nothing we can measure explains the record.
* The bets' why-categories: 12 low minutes (12 of 12 won), 9 low shot volume (9 of 9), 12 other (12 of 12), and 1 cold shooting (lost, Siakam). There is nothing to filter on with n=34.
* Verdict: **promising-but-unproven; most likely luck.** Keep it at a small fixed stake as a tracked rule. Do not scale it. History supports filtering out players not starting today, but all 7 such priced bets won. So log the split rather than filter.


# 2. Paddy's ladder vs reality

**Hypothesis.** Certain rungs, such as just below the main line, high-variance players, or skewed stats, are mispriced relative to outcomes or to Paddy's own main line.
Method: for each alt over, the distance (rung - main line) in the player's last-10 sd. The 'ladder-consistent' probability is computed by taking Paddy's devigged main-line probability, solving a negative-binomial mean with the per-stat dispersion from the projection fit, and reading off the rung's probability.

## 2a. NBA alt overs by distance from the main line (rung - main line, in the player's last-10 sd). All rungs, first price.

| slice | n | games | hit | avg_p | be_hit | roi | ci90 | roi_H1 | n_H1 | roi_H2 | n_H2 | verdict | hit-impl |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| (-99.0, -1.5] | 664 | 88 | 0.889 | 1.087 | 0.924 | -0.039 | [-0.073, -0.008] | -0.054 | 333 | -0.024 | 331 | LOSER | -0.036 |
| (-1.5, -1.0] | 1092 | 88 | 0.81 | 1.153 | 0.874 | -0.072 | [-0.098, -0.046] | -0.054 | 562 | -0.09 | 530 | LOSER | -0.063 |
| (-1.0, -0.5] | 1979 | 88 | 0.713 | 1.263 | 0.801 | -0.108 | [-0.136, -0.081] | -0.126 | 1041 | -0.088 | 938 | LOSER | -0.087 |
| (-0.5, -0.01] | 1093 | 88 | 0.597 | 1.508 | 0.669 | -0.107 | [-0.149, -0.063] | -0.082 | 607 | -0.138 | 486 | LOSER | -0.072 |
| (-0.01, 0.5] | 1169 | 88 | 0.343 | 2.617 | 0.393 | -0.126 | [-0.193, -0.062] | -0.14 | 648 | -0.108 | 521 | LOSER | -0.05 |
| (0.5, 1.0] | 2409 | 88 | 0.223 | 3.972 | 0.274 | -0.186 | [-0.257, -0.115] | -0.205 | 1296 | -0.164 | 1113 | LOSER | -0.051 |
| (1.0, 1.5] | 2023 | 88 | 0.13 | 6.915 | 0.172 | -0.245 | [-0.342, -0.143] | -0.274 | 1056 | -0.213 | 967 | LOSER | -0.042 |
| (1.5, 2.5] | 2945 | 88 | 0.065 | 12.411 | 0.105 | -0.434 | [-0.520, -0.347] | -0.434 | 1487 | -0.435 | 1458 | LOSER | -0.04 |
| (2.5, 99.0] | 2292 | 88 | 0.024 | 31.241 | 0.05 | -0.694 | [-0.777, -0.604] | -0.721 | 1147 | -0.667 | 1145 | LOSER | -0.027 |

### NBA: Paddy alt implied vs its own main line (NB-consistent probability), by distance

| dist | n | games | hit | impl | ladder_consistent | impl_over_cons | roi |
|---|---|---|---|---|---|---|---|
| (-99.0, -1.5] | 664 | 88 | 0.889 | 0.924 | 0.828 | 1.108 | -0.039 |
| (-1.5, -1.0] | 1092 | 88 | 0.81 | 0.874 | 0.781 | 1.11 | -0.072 |
| (-1.0, -0.5] | 1979 | 88 | 0.713 | 0.801 | 0.714 | 1.118 | -0.108 |
| (-0.5, -0.01] | 1093 | 88 | 0.597 | 0.669 | 0.603 | 1.109 | -0.107 |
| (-0.01, 0.5] | 1169 | 88 | 0.343 | 0.393 | 0.394 | 1.006 | -0.126 |
| (0.5, 1.0] | 2409 | 88 | 0.223 | 0.274 | 0.287 | 0.987 | -0.186 |
| (1.0, 1.5] | 2023 | 88 | 0.13 | 0.172 | 0.199 | 0.933 | -0.245 |
| (1.5, 2.5] | 2945 | 88 | 0.065 | 0.105 | 0.131 | 0.899 | -0.434 |
| (2.5, 99.0] | 2292 | 88 | 0.024 | 0.05 | 0.067 | 0.988 | -0.694 |

### NBA alt overs priced <= 3.0 by implied / ladder-consistent ratio (<1 = alt cheaper than its main line implies)

| slice | n | games | hit | avg_p | be_hit | roi | ci90 | roi_H1 | n_H1 | roi_H2 | n_H2 | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| (0.0, 0.9] | 161 | 69 | 0.248 | 2.776 | 0.362 | -0.316 | [-0.499, -0.137] | -0.232 | 104 | -0.467 | 57 | LOSER |
| (0.9, 0.97] | 360 | 82 | 0.325 | 2.608 | 0.388 | -0.15 | [-0.261, -0.035] | -0.147 | 183 | -0.153 | 177 | LOSER |
| (0.97, 1.03] | 728 | 88 | 0.372 | 2.47 | 0.418 | -0.112 | [-0.179, -0.043] | -0.106 | 410 | -0.119 | 318 | LOSER |
| (1.03, 1.1] | 2278 | 88 | 0.691 | 1.487 | 0.744 | -0.077 | [-0.104, -0.050] | -0.09 | 1177 | -0.062 | 1101 | LOSER |
| (1.1, 1.25] | 2905 | 88 | 0.699 | 1.319 | 0.783 | -0.111 | [-0.146, -0.077] | -0.108 | 1533 | -0.116 | 1372 | LOSER |
| (1.25, 99.0] | 98 | 32 | 0.776 | 1.212 | 0.835 | -0.075 | [-0.228, +0.072] | -0.161 | 65 | 0.093 | 33 | noise |

### NBA by stat x side of main line (rungs below vs above), prices <= 3.0

| slice | n | games | hit | avg_p | be_hit | roi | ci90 | roi_H1 | n_H1 | roi_H2 | n_H2 | verdict | hit-impl |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Assists | above main | 228 | 84 | 0.316 | 2.678 | 0.377 | -0.173 | [-0.305, -0.033] | -0.271 | 125 | -0.053 | 103 | LOSER | -0.061 |
| Assists | below main | 823 | 88 | 0.783 | 1.241 | 0.821 | -0.049 | [-0.087, -0.014] | -0.058 | 429 | -0.039 | 394 | LOSER | -0.039 |
| Blocks | below main | 61 | 32 | 0.689 | 1.236 | 0.816 | -0.159 | [-0.277, -0.042] | -0.141 | 37 | -0.185 | 24 | LOSER | -0.128 |
| Points | above main | 775 | 88 | 0.342 | 2.5 | 0.406 | -0.157 | [-0.246, -0.071] | -0.15 | 427 | -0.167 | 348 | LOSER | -0.064 |
| Points | below main | 1596 | 88 | 0.702 | 1.313 | 0.782 | -0.103 | [-0.147, -0.060] | -0.074 | 859 | -0.137 | 737 | LOSER | -0.08 |
| Rebounds | above main | 400 | 87 | 0.34 | 2.616 | 0.387 | -0.125 | [-0.230, -0.017] | -0.073 | 207 | -0.18 | 193 | LOSER | -0.047 |
| Rebounds | below main | 987 | 88 | 0.737 | 1.286 | 0.794 | -0.074 | [-0.111, -0.038] | -0.079 | 504 | -0.069 | 483 | LOSER | -0.057 |
| Rebounds and assists | above main | 128 | 22 | 0.352 | 2.597 | 0.389 | -0.105 | [-0.275, +0.084] | -0.144 | 83 | -0.032 | 45 | noise | -0.038 |
| Rebounds and assists | below main | 325 | 22 | 0.729 | 1.295 | 0.785 | -0.071 | [-0.163, +0.008] | -0.141 | 205 | 0.049 | 120 | noise | -0.055 |
| Steals | below main | 153 | 52 | 0.745 | 1.253 | 0.801 | -0.071 | [-0.133, -0.006] | -0.081 | 74 | -0.062 | 79 | LOSER | -0.056 |
| Three pointers made | above main | 165 | 78 | 0.303 | 2.733 | 0.368 | -0.175 | [-0.315, -0.034] | -0.223 | 84 | -0.124 | 81 | LOSER | -0.065 |
| Three pointers made | below main | 883 | 88 | 0.742 | 1.192 | 0.848 | -0.128 | [-0.160, -0.098] | -0.14 | 435 | -0.117 | 448 | LOSER | -0.106 |

### NBA alt overs below the main line (dist < 0), prices <= 3.0, by player volatility (sd/mean of last 10, quartiles)

| slice | n | games | hit | avg_p | be_hit | roi | ci90 | roi_H1 | n_H1 | roi_H2 | n_H2 | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| (0.0798, 0.34] | 1436 | 88 | 0.767 | 1.269 | 0.806 | -0.05 | [-0.095, -0.009] | -0.033 | 775 | -0.07 | 661 | LOSER |
| (0.34, 0.465] | 1238 | 88 | 0.733 | 1.28 | 0.799 | -0.086 | [-0.125, -0.047] | -0.059 | 660 | -0.116 | 578 | LOSER |
| (0.465, 0.621] | 1099 | 88 | 0.698 | 1.282 | 0.797 | -0.127 | [-0.167, -0.085] | -0.166 | 571 | -0.084 | 528 | LOSER |
| (0.621, 1.844] | 1055 | 87 | 0.725 | 1.242 | 0.816 | -0.111 | [-0.143, -0.079] | -0.131 | 537 | -0.091 | 518 | LOSER |

## 2a. NFL alt overs by distance from the main line (rung - main line, in the player's last-10 sd). All rungs, first price.

| slice | n | games | hit | avg_p | be_hit | roi | ci90 | roi_H1 | n_H1 | roi_H2 | n_H2 | verdict | hit-impl |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| (-99.0, -1.5] | 151 | 27 | 0.828 | 1.063 | 0.945 | -0.13 | [-0.236, -0.024] | -0.085 | 76 | -0.175 | 75 | LOSER | -0.117 |
| (-1.5, -1.0] | 283 | 27 | 0.823 | 1.14 | 0.881 | -0.069 | [-0.142, -0.000] | -0.074 | 142 | -0.064 | 141 | noise | -0.058 |
| (-1.0, -0.5] | 947 | 27 | 0.743 | 1.224 | 0.822 | -0.095 | [-0.145, -0.049] | -0.081 | 467 | -0.11 | 480 | LOSER | -0.078 |
| (-0.5, -0.01] | 1017 | 27 | 0.592 | 1.504 | 0.673 | -0.118 | [-0.185, -0.051] | -0.087 | 518 | -0.151 | 499 | LOSER | -0.081 |
| (-0.01, 0.5] | 923 | 27 | 0.375 | 2.348 | 0.438 | -0.143 | [-0.237, -0.052] | -0.109 | 462 | -0.177 | 461 | LOSER | -0.063 |
| (0.5, 1.0] | 1067 | 27 | 0.278 | 3.711 | 0.289 | -0.04 | [-0.173, +0.101] | 0.027 | 539 | -0.108 | 528 | noise | -0.011 |
| (1.0, 1.5] | 879 | 27 | 0.167 | 5.863 | 0.194 | -0.132 | [-0.344, +0.108] | -0.152 | 452 | -0.111 | 427 | noise | -0.027 |
| (1.5, 2.5] | 930 | 27 | 0.108 | 17.332 | 0.135 | -0.269 | [-0.466, -0.025] | -0.281 | 472 | -0.256 | 458 | LOSER | -0.027 |
| (2.5, 99.0] | 401 | 27 | 0.06 | 114 | 0.08 | -0.435 | [-0.664, -0.135] | -0.48 | 210 | -0.385 | 191 | LOSER | -0.02 |

### NFL by stat, rungs below vs above main line (all prices)

| slice | n | games | hit | avg_p | be_hit | roi | ci90 | roi_H1 | n_H1 | roi_H2 | n_H2 | verdict | hit-impl |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Passing and rushing yards | above main | 514 | 26 | 0.103 | 108 | 0.129 | -0.48 | [-0.812, +0.038] | -0.704 | 263 | -0.246 | 251 | noise | -0.026 |
| Passing and rushing yards | below main | 308 | 26 | 0.786 | 1.187 | 0.866 | -0.093 | [-0.194, +0.006] | -0.032 | 155 | -0.156 | 153 | noise | -0.08 |
| Passing touchdowns | above main | 89 | 27 | 0.169 | 7.535 | 0.175 | -0.159 | [-0.571, +0.332] | -0.282 | 44 | -0.038 | 45 | noise | -0.006 |
| Passing yards | above main | 230 | 27 | 0.252 | 4.657 | 0.279 | -0.147 | [-0.476, +0.194] | -0.12 | 116 | -0.173 | 114 | noise | -0.027 |
| Passing yards | below main | 190 | 27 | 0.695 | 1.302 | 0.787 | -0.116 | [-0.261, +0.016] | -0.048 | 98 | -0.188 | 92 | noise | -0.093 |
| Receiving receptions | above main | 793 | 27 | 0.187 | 5.29 | 0.23 | -0.23 | [-0.408, -0.053] | -0.281 | 407 | -0.176 | 386 | LOSER | -0.044 |
| Receiving receptions | below main | 368 | 27 | 0.712 | 1.27 | 0.795 | -0.105 | [-0.170, -0.044] | -0.111 | 185 | -0.098 | 183 | LOSER | -0.083 |
| Receiving yards | above main | 1525 | 27 | 0.254 | 4.598 | 0.28 | -0.083 | [-0.232, +0.063] | -0.011 | 787 | -0.16 | 738 | noise | -0.025 |
| Receiving yards | below main | 890 | 27 | 0.672 | 1.374 | 0.743 | -0.094 | [-0.157, -0.033] | -0.105 | 441 | -0.084 | 449 | LOSER | -0.071 |
| Rushing and receiving yards | above main | 353 | 27 | 0.258 | 4.894 | 0.276 | -0.059 | [-0.354, +0.261] | 0.103 | 174 | -0.217 | 179 | noise | -0.018 |
| Rushing and receiving yards | below main | 253 | 27 | 0.731 | 1.359 | 0.753 | -0.031 | [-0.117, +0.054] | 0.034 | 122 | -0.091 | 131 | noise | -0.021 |
| Rushing yards | above main | 698 | 27 | 0.234 | 4.711 | 0.272 | -0.121 | [-0.316, +0.094] | -0.045 | 346 | -0.195 | 352 | noise | -0.038 |
| Rushing yards | below main | 358 | 27 | 0.623 | 1.364 | 0.749 | -0.176 | [-0.245, -0.099] | -0.14 | 186 | -0.214 | 172 | LOSER | -0.126 |

### NFL QB rushing-yard alt overs by distance

| slice | n | games | hit | avg_p | be_hit | roi | ci90 | roi_H1 | n_H1 | roi_H2 | n_H2 | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| (-1.5, -1.0] | 6 | 6 | 0.667 | 1.144 | 0.875 | -0.242 | [-0.622, +0.135] | -0.141 | 4 | -0.444 | 2 | tiny |
| (-1.0, -0.5] | 31 | 23 | 0.548 | 1.222 | 0.823 | -0.337 | [-0.526, -0.121] | -0.283 | 17 | -0.402 | 14 | LOSER |
| (-0.5, -0.01] | 54 | 23 | 0.5 | 1.506 | 0.672 | -0.26 | [-0.468, -0.064] | -0.069 | 26 | -0.438 | 28 | LOSER |
| (-0.01, 0.5] | 42 | 23 | 0.238 | 2.291 | 0.444 | -0.479 | [-0.740, -0.164] | -0.286 | 19 | -0.639 | 23 | LOSER |
| (0.5, 1.0] | 49 | 25 | 0.163 | 3.45 | 0.308 | -0.505 | [-0.816, -0.106] | -0.458 | 24 | -0.549 | 25 | LOSER |
| (1.0, 1.5] | 42 | 27 | 0.119 | 4.929 | 0.228 | -0.516 | [-0.902, -0.039] | -0.44 | 23 | -0.608 | 19 | LOSER |
| (1.5, 2.5] | 48 | 25 | 0.083 | 6.913 | 0.158 | -0.552 | [-0.912, -0.070] | -0.795 | 22 | -0.346 | 26 | LOSER |
| (2.5, 99.0] | 26 | 17 | 0.038 | 7.885 | 0.139 | -0.692 | [-1.000, +0.000] | -1 | 15 | -0.273 | 11 | tiny |

**Conclusions (direction 2).** No structural ladder edge. Below the main line, Paddy's alt prices sit about 11% shorter than its own main line implies (impl/consistent = 1.11). The hit rate tracks the ladder-consistent probability (0.597 vs 0.603, 0.713 vs 0.714, 0.81 vs 0.78). In other words, **the main line is well calibrated and the ladder simply adds margin**.
Above the main line Paddy's alts are slightly longer than the NB tail, but the true tail is thinner still, and they lose 13-69%. Alts that are 'cheap' relative to the main line lose more, not less. Low-volatility players lose least (-5%), still negative. NFL shows the same pattern (every distance negative). QB rushing alt overs lose 26-69%.


# 3. Projection vs line (walk-forward)

Model: LightGBM (Poisson objective) per stat on usfeatures' pre-game features (form windows, minutes/volume, team and opponent style, opponent concession to position, Elo, rest, home, h2h). The spread is negative binomial with per-stat dispersion fitted on the last 15% of each training window.
Walk-forward folds: train < 20 Oct, predict 20-26 Oct; retrain < 27 Oct, predict 27 Oct - 2 Nov (NFL: < 17 Oct / < 25 Oct).
Two versions: **with line-up info** (today's actual starter flag and actual absentees) and **no line-up info** (starter = usual role, no absentee features). The second matches what is knowable at Paddy's first price, which is logged about 9 h before tip (median); the last price is about 1.2 h before, before line-ups.
**Pre-game audit of usfeatures.** Form windows, rest, Elo, team style and opponent concession all come from earlier games only. Same-tip-off games are held back via `pending`, and Elo is taken before each game.
Two groups are line-up-level rather than pre-game: `starter` (today's actual flag) and `miss_*` / `mate_*` (who actually played). The combo targets (pra/pr/pa/ra) must be added to P before `features()`, or they come out as 0. The NFL model was run only with line-up info; its no-line-up variant was not run for time.
Test MAE, averaged over folds (lower is better): points 4.62 with line-ups / 4.86 without / 5.08 for the last-10 mean; PRA 6.03 / 6.47 / 6.75. Line-up news is worth about as much as the rest of the model.

## 3. NBA projection (no line-up info: starter = usual role, no actual absentees) vs Paddy, pplog period, walk-forward

| set | n | games | brier_model | brier_paddy_devig | logloss_model | logloss_paddy | brier_blend50 | corr_model_paddy |
|---|---|---|---|---|---|---|---|---|
| main lines (over side) | 5953 | 88 | 0.252 | 0.247 | 0.699 | 0.687 | 0.246 | 0.33 |

### Calibration on main lines (over side): model vs Paddy devigged

| who | bin | n | pred | actual |
|---|---|---|---|---|
| model | (0.0, 0.3] | 607 | 0.244 | 0.392 |
| model | (0.3, 0.4] | 1814 | 0.358 | 0.441 |
| model | (0.4, 0.45] | 1369 | 0.424 | 0.451 |
| model | (0.45, 0.5] | 959 | 0.473 | 0.487 |
| model | (0.5, 0.55] | 621 | 0.523 | 0.52 |
| model | (0.55, 0.6] | 318 | 0.572 | 0.553 |
| model | (0.6, 0.7] | 222 | 0.638 | 0.595 |
| model | (0.7, 1.0] | 43 | 0.742 | 0.535 |
| paddy | (0.0, 0.3] | 2 | 0.259 | 0 |
| paddy | (0.3, 0.4] | 324 | 0.364 | 0.373 |
| paddy | (0.4, 0.45] | 869 | 0.432 | 0.407 |
| paddy | (0.45, 0.5] | 2492 | 0.481 | 0.463 |
| paddy | (0.5, 0.55] | 1689 | 0.529 | 0.477 |
| paddy | (0.55, 0.6] | 510 | 0.567 | 0.59 |
| paddy | (0.6, 0.7] | 65 | 0.628 | 0.615 |
| paddy | (0.7, 1.0] | 2 | 0.746 | 1 |

### ROI by model edge, main lines, both sides

| slice | n | games | hit | avg_p | be_hit | roi | ci90 | roi_H1 | n_H1 | roi_H2 | n_H2 | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| (-1.0, -0.2] | 3385 | 88 | 0.445 | 1.881 | 0.537 | -0.174 | [-0.223, -0.125] | -0.172 | 1732 | -0.175 | 1653 | LOSER |
| (-0.2, -0.1] | 2007 | 88 | 0.498 | 1.87 | 0.542 | -0.08 | [-0.116, -0.042] | -0.065 | 983 | -0.093 | 1024 | LOSER |
| (-0.1, -0.05] | 998 | 85 | 0.511 | 1.857 | 0.547 | -0.076 | [-0.098, -0.056] | -0.072 | 476 | -0.08 | 522 | LOSER |
| (-0.05, 0.0] | 1013 | 88 | 0.519 | 1.846 | 0.549 | -0.056 | [-0.103, -0.005] | -0.091 | 509 | -0.021 | 504 | LOSER |
| (0.0, 0.05] | 1029 | 88 | 0.51 | 1.844 | 0.549 | -0.073 | [-0.128, -0.018] | -0.097 | 480 | -0.051 | 549 | LOSER |
| (0.05, 0.1] | 877 | 87 | 0.556 | 1.879 | 0.539 | 0.031 | [-0.031, +0.095] | 0.067 | 399 | 0.002 | 478 | promising |
| (0.1, 0.2] | 1295 | 88 | 0.526 | 1.893 | 0.534 | -0.013 | [-0.070, +0.047] | 0.002 | 629 | -0.028 | 666 | noise |
| (0.2, 9.0] | 1286 | 88 | 0.553 | 1.94 | 0.521 | 0.065 | [-0.014, +0.145] | 0.052 | 732 | 0.083 | 554 | promising |

### ROI by model edge, alt overs priced <= 3.0 (all rungs)

| slice | n | games | hit | avg_p | be_hit | roi | ci90 | roi_H1 | n_H1 | roi_H2 | n_H2 | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| (-1.0, -0.2] | 3142 | 88 | 0.616 | 1.6 | 0.692 | -0.12 | [-0.167, -0.077] | -0.13 | 1712 | -0.109 | 1430 | LOSER |
| (-0.2, -0.1] | 2107 | 88 | 0.688 | 1.465 | 0.75 | -0.084 | [-0.113, -0.055] | -0.084 | 1004 | -0.084 | 1103 | LOSER |
| (-0.1, -0.05] | 692 | 86 | 0.669 | 1.536 | 0.726 | -0.067 | [-0.117, -0.019] | -0.057 | 363 | -0.078 | 329 | LOSER |
| (-0.05, 0.0] | 372 | 80 | 0.543 | 1.812 | 0.624 | -0.154 | [-0.236, -0.072] | -0.13 | 223 | -0.191 | 149 | LOSER |
| (0.0, 0.05] | 184 | 66 | 0.527 | 2.088 | 0.531 | -0.027 | [-0.151, +0.094] | 0.187 | 117 | -0.401 | 67 | noise |
| (0.05, 0.1] | 135 | 66 | 0.407 | 2.245 | 0.488 | -0.217 | [-0.365, -0.061] | -0.35 | 91 | 0.058 | 44 | LOSER |
| (0.1, 0.2] | 132 | 58 | 0.394 | 2.436 | 0.435 | -0.127 | [-0.289, +0.041] | -0.13 | 88 | -0.121 | 44 | noise |
| (0.2, 9.0] | 109 | 48 | 0.358 | 2.631 | 0.392 | -0.113 | [-0.332, +0.124] | -0.123 | 80 | -0.085 | 29 | noise |

### Main lines by (projection - Paddy line) / sd10, betting the side the projection favours

| slice | n | games | hit | avg_p | be_hit | roi | ci90 | roi_H1 | n_H1 | roi_H2 | n_H2 | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| (-9.0, -0.5] -> unders | 738 | 83 | 0.58 | 1.773 | 0.569 | 0.022 | [-0.074, +0.125] | -0.015 | 406 | 0.068 | 332 | noise |
| (-0.5, -0.25] -> unders | 902 | 87 | 0.583 | 1.783 | 0.566 | 0.034 | [-0.049, +0.115] | 0.052 | 446 | 0.016 | 456 | promising |
| (-0.25, -0.1] -> unders | 806 | 87 | 0.56 | 1.783 | 0.567 | -0.01 | [-0.068, +0.046] | 0.022 | 373 | -0.037 | 433 | noise |
| (-0.1, 0.1] overs | 1298 | 87 | 0.461 | 1.924 | 0.525 | -0.119 | [-0.181, -0.054] | -0.126 | 566 | -0.113 | 732 | LOSER |
| (-0.1, 0.1] unders | 1297 | 87 | 0.539 | 1.825 | 0.553 | -0.023 | [-0.084, +0.037] | -0.018 | 566 | -0.027 | 731 | noise |
| (0.1, 0.25] -> overs | 802 | 85 | 0.486 | 1.871 | 0.539 | -0.092 | [-0.163, -0.023] | -0.056 | 382 | -0.125 | 420 | LOSER |
| (0.25, 0.5] -> overs | 871 | 86 | 0.528 | 1.827 | 0.552 | -0.044 | [-0.122, +0.034] | -0.005 | 452 | -0.086 | 419 | noise |
| (0.5, 9.0] -> overs | 527 | 79 | 0.539 | 1.806 | 0.559 | -0.034 | [-0.134, +0.068] | -0.045 | 344 | -0.014 | 183 | noise |

### Main lines with model edge >= 5%, by stat

| slice | n | games | hit | avg_p | be_hit | roi | ci90 | roi_H1 | n_H1 | roi_H2 | n_H2 | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Points rebounds and assists | 430 | 87 | 0.563 | 1.877 | 0.534 | 0.054 | [-0.019, +0.126] | 0.016 | 212 | 0.091 | 218 | promising |
| Rebounds | 455 | 88 | 0.527 | 1.931 | 0.525 | 0.007 | [-0.071, +0.084] | 0.041 | 247 | -0.034 | 208 | noise |
| Rebounds and assists | 325 | 85 | 0.526 | 1.91 | 0.527 | 0.003 | [-0.091, +0.094] | -0.008 | 172 | 0.014 | 153 | noise |
| Points and rebounds | 526 | 88 | 0.557 | 1.864 | 0.538 | 0.038 | [-0.034, +0.110] | -0.002 | 259 | 0.078 | 267 | noise |
| Points | 542 | 88 | 0.557 | 1.882 | 0.533 | 0.048 | [-0.015, +0.114] | 0.078 | 273 | 0.018 | 269 | promising |
| Assists | 362 | 88 | 0.517 | 1.937 | 0.527 | -0.03 | [-0.114, +0.061] | 0.01 | 185 | -0.072 | 177 | noise |
| Points and assists | 396 | 87 | 0.548 | 1.874 | 0.535 | 0.025 | [-0.048, +0.103] | 0.013 | 185 | 0.036 | 211 | promising |
| Three pointers made | 333 | 87 | 0.538 | 2.035 | 0.508 | 0.077 | [-0.024, +0.178] | 0.124 | 171 | 0.027 | 162 | promising |
| Steals | 70 | 40 | 0.571 | 1.848 | 0.568 | -0.032 | [-0.226, +0.153] | 0.164 | 45 | -0.384 | 25 | noise |
| all | 3458 | 88 | 0.544 | 1.907 | 0.53 | 0.027 | [-0.021, +0.073] | 0.038 | 1760 | 0.016 | 1698 | promising |

### Blend fitted on H1 main lines: logit(p) = +0.002 + 0.268*logit(model) + 0.742*logit(paddy devig) (SE model 0.046). Tested on H2:

| slice | n | games | hit | avg_p | be_hit | roi | ci90 | roi_H1 | n_H1 | roi_H2 | n_H2 | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| H2 blend edge >= 0 | 620 | 39 | 0.555 | 1.935 | 0.522 | 0.062 | [-0.068, +0.184] |  | 0 | 0.062 | 620 | noise |
| H2 blend edge >= 0.03 | 236 | 34 | 0.572 | 1.968 | 0.515 | 0.118 | [-0.073, +0.304] |  | 0 | 0.118 | 236 | noise |
| H2 blend edge >= 0.05 | 119 | 28 | 0.605 | 1.991 | 0.512 | 0.19 | [-0.055, +0.400] |  | 0 | 0.19 | 119 | noise |
| H2 blend edge >= 0.1 | 25 | 12 | 0.56 | 2.181 | 0.49 | 0.15 | [-0.310, +0.552] |  | 0 | 0.15 | 25 | tiny |

### With line-up info (not bettable at the first price; shown for scale)

## 3. NBA projection (with actual starters / absentees) vs Paddy, pplog period, walk-forward

| set | n | games | brier_model | brier_paddy_devig | logloss_model | logloss_paddy | brier_blend50 | corr_model_paddy |
|---|---|---|---|---|---|---|---|---|
| main lines (over side) | 5953 | 88 | 0.252 | 0.247 | 0.7 | 0.687 | 0.246 | 0.36 |

### NFL (with line-up info)

## 3. NFL projection (with actual starters / absentees) vs Paddy, pplog period, walk-forward

| set | n | games | brier_model | brier_paddy_devig | logloss_model | logloss_paddy | brier_blend50 | corr_model_paddy |
|---|---|---|---|---|---|---|---|---|
| main lines (over side) | 967 | 27 | 0.249 | 0.247 | 0.691 | 0.687 | 0.245 | 0.3 |

### Calibration on main lines (over side): model vs Paddy devigged

| who | bin | n | pred | actual |
|---|---|---|---|---|
| model | (0.0, 0.3] | 75 | 0.249 | 0.307 |
| model | (0.3, 0.4] | 253 | 0.358 | 0.447 |
| model | (0.4, 0.45] | 190 | 0.425 | 0.453 |
| model | (0.45, 0.5] | 163 | 0.474 | 0.521 |
| model | (0.5, 0.55] | 118 | 0.524 | 0.542 |
| model | (0.55, 0.6] | 68 | 0.57 | 0.574 |
| model | (0.6, 0.7] | 82 | 0.639 | 0.549 |
| model | (0.7, 1.0] | 18 | 0.732 | 0.556 |
| paddy | (0.3, 0.4] | 38 | 0.379 | 0.368 |
| paddy | (0.4, 0.45] | 78 | 0.425 | 0.333 |
| paddy | (0.45, 0.5] | 701 | 0.496 | 0.485 |
| paddy | (0.5, 0.55] | 82 | 0.526 | 0.549 |
| paddy | (0.55, 0.6] | 45 | 0.573 | 0.556 |
| paddy | (0.6, 0.7] | 23 | 0.623 | 0.652 |

### ROI by model edge, main lines, both sides

| slice | n | games | hit | avg_p | be_hit | roi | ci90 | roi_H1 | n_H1 | roi_H2 | n_H2 | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| (-1.0, -0.2] | 604 | 27 | 0.437 | 1.848 | 0.545 | -0.2 | [-0.275, -0.125] | -0.253 | 315 | -0.143 | 289 | LOSER |
| (-0.2, -0.1] | 318 | 27 | 0.5 | 1.83 | 0.552 | -0.095 | [-0.166, -0.021] | -0.006 | 153 | -0.177 | 165 | LOSER |
| (-0.1, -0.05] | 146 | 25 | 0.521 | 1.836 | 0.549 | -0.05 | [-0.121, +0.010] | 0.011 | 73 | -0.111 | 73 | noise |
| (-0.05, 0.0] | 171 | 27 | 0.515 | 1.834 | 0.55 | -0.067 | [-0.178, +0.038] | -0.25 | 82 | 0.101 | 89 | noise |
| (0.0, 0.05] | 164 | 27 | 0.494 | 1.82 | 0.553 | -0.111 | [-0.214, -0.003] | -0.057 | 78 | -0.16 | 86 | LOSER |
| (0.05, 0.1] | 143 | 27 | 0.594 | 1.826 | 0.552 | 0.078 | [-0.058, +0.213] | 0.03 | 78 | 0.135 | 65 | promising |
| (0.1, 0.2] | 213 | 27 | 0.526 | 1.846 | 0.545 | -0.038 | [-0.134, +0.050] | -0.049 | 112 | -0.027 | 101 | noise |
| (0.2, 9.0] | 172 | 27 | 0.576 | 1.894 | 0.532 | 0.078 | [-0.055, +0.207] | 0.214 | 90 | -0.07 | 82 | noise |

### ROI by model edge, alt overs priced <= 3.0 (all rungs)

| slice | n | games | hit | avg_p | be_hit | roi | ci90 | roi_H1 | n_H1 | roi_H2 | n_H2 | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| (-1.0, -0.2] | 1685 | 27 | 0.539 | 1.748 | 0.63 | -0.157 | [-0.227, -0.087] | -0.166 | 879 | -0.147 | 806 | LOSER |
| (-0.2, -0.1] | 1008 | 27 | 0.668 | 1.538 | 0.714 | -0.066 | [-0.141, +0.010] | -0.012 | 490 | -0.116 | 518 | noise |
| (-0.1, -0.05] | 382 | 27 | 0.665 | 1.614 | 0.688 | -0.012 | [-0.112, +0.088] | -0.022 | 180 | -0.003 | 202 | noise |
| (-0.05, 0.0] | 221 | 27 | 0.52 | 1.595 | 0.684 | -0.259 | [-0.381, -0.137] | -0.306 | 101 | -0.22 | 120 | LOSER |
| (0.0, 0.05] | 139 | 25 | 0.604 | 1.806 | 0.611 | 0 | [-0.174, +0.175] | 0.219 | 63 | -0.181 | 76 | noise |
| (0.05, 0.1] | 83 | 22 | 0.494 | 1.832 | 0.588 | -0.142 | [-0.361, +0.089] | 0.053 | 42 | -0.342 | 41 | noise |
| (0.1, 0.2] | 80 | 23 | 0.488 | 2.095 | 0.508 | -0.034 | [-0.251, +0.180] | 0.178 | 47 | -0.335 | 33 | noise |
| (0.2, 9.0] | 86 | 21 | 0.407 | 2.329 | 0.45 | -0.056 | [-0.303, +0.207] | 0.177 | 47 | -0.338 | 39 | noise |

### Main lines by (projection - Paddy line) / sd10, betting the side the projection favours

| slice | n | games | hit | avg_p | be_hit | roi | ci90 | roi_H1 | n_H1 | roi_H2 | n_H2 | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| (-9.0, -0.5] -> unders | 73 | 21 | 0.658 | 1.726 | 0.584 | 0.124 | [-0.053, +0.289] | 0.09 | 38 | 0.161 | 35 | promising |
| (-0.5, -0.25] -> unders | 126 | 26 | 0.548 | 1.777 | 0.566 | -0.028 | [-0.224, +0.157] | 0.042 | 72 | -0.122 | 54 | noise |
| (-0.25, -0.1] -> unders | 132 | 27 | 0.492 | 1.806 | 0.556 | -0.116 | [-0.277, +0.061] | -0.073 | 66 | -0.16 | 66 | noise |
| (-0.1, 0.1] overs | 201 | 27 | 0.453 | 1.862 | 0.541 | -0.164 | [-0.292, -0.041] | -0.265 | 106 | -0.051 | 95 | LOSER |
| (-0.1, 0.1] unders | 200 | 27 | 0.545 | 1.815 | 0.554 | -0.017 | [-0.134, +0.107] | 0.062 | 105 | -0.103 | 95 | noise |
| (0.1, 0.25] -> overs | 156 | 27 | 0.462 | 1.841 | 0.547 | -0.154 | [-0.287, -0.015] | 0.045 | 70 | -0.315 | 86 | LOSER |
| (0.25, 0.5] -> overs | 165 | 27 | 0.509 | 1.845 | 0.545 | -0.071 | [-0.185, +0.038] | -0.154 | 84 | 0.015 | 81 | noise |
| (0.5, 9.0] -> overs | 112 | 25 | 0.607 | 1.781 | 0.567 | 0.078 | [-0.067, +0.228] | 0.257 | 54 | -0.089 | 58 | noise |

### Main lines with model edge >= 5%, by stat

| slice | n | games | hit | avg_p | be_hit | roi | ci90 | roi_H1 | n_H1 | roi_H2 | n_H2 | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Receiving yards | 169 | 27 | 0.544 | 1.837 | 0.545 | -0 | [-0.134, +0.138] | 0.12 | 90 | -0.137 | 79 | noise |
| Receiving receptions | 154 | 27 | 0.63 | 1.892 | 0.539 | 0.16 | [+0.048, +0.281] | 0.235 | 82 | 0.075 | 72 | WORKING |
| Rushing yards | 99 | 27 | 0.525 | 1.842 | 0.544 | -0.035 | [-0.169, +0.095] | -0.008 | 48 | -0.06 | 51 | noise |
| Rushing and receiving yards | 38 | 21 | 0.605 | 1.835 | 0.545 | 0.111 | [-0.105, +0.333] | 0.1 | 20 | 0.124 | 18 | promising |
| Passing touchdowns | 26 | 23 | 0.615 | 1.896 | 0.544 | 0.14 | [-0.168, +0.437] | -0.103 | 15 | 0.47 | 11 | tiny |
| Passing yards | 25 | 17 | 0.4 | 1.833 | 0.546 | -0.267 | [-0.542, -0.000] | -0.436 | 13 | -0.084 | 12 | tiny |
| all | 528 | 27 | 0.561 | 1.856 | 0.543 | 0.031 | [-0.045, +0.106] | 0.058 | 280 | 0.001 | 248 | promising |

### Blend fitted on H1 main lines: logit(p) = -0.002 + 0.618*logit(model) + 1.105*logit(paddy devig) (SE model 0.130). Tested on H2:

| slice | n | games | hit | avg_p | be_hit | roi | ci90 | roi_H1 | n_H1 | roi_H2 | n_H2 | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| H2 blend edge >= 0 | 255 | 13 | 0.553 | 1.778 | 0.566 | -0.022 | [-0.145, +0.094] |  | 0 | -0.022 | 255 | noise |
| H2 blend edge >= 0.03 | 195 | 13 | 0.538 | 1.774 | 0.568 | -0.053 | [-0.190, +0.074] |  | 0 | -0.053 | 195 | noise |
| H2 blend edge >= 0.05 | 149 | 13 | 0.523 | 1.762 | 0.572 | -0.088 | [-0.246, +0.068] |  | 0 | -0.088 | 149 | noise |
| H2 blend edge >= 0.1 | 81 | 13 | 0.593 | 1.762 | 0.571 | 0.03 | [-0.147, +0.200] |  | 0 | 0.03 | 81 | noise |

**Conclusions (direction 3).** The model is overconfident at the extremes (a predicted 24% comes in at 39-41%) and loses to Paddy on Brier and log-loss in both sports. Used alone, its edges are small: main lines with edge >= 5% made +2.7% (no line-ups) and +3.2% (with), CIs spanning zero. Its alt-over edges lose.
It does carry independent information: in a blend fitted on H1 the model takes about 27% of the weight, which is significant. **On H2 only**, blend edge >= 3% made +11.8% (n=236, 34 games, CI -7% to +30%). This is promising and unproven, and it mostly re-finds the reversion signal in direction 5.
NFL: blend fails out of sample. Receptions with edge >= 5% made +16% (n=154), but that is one of about 15 NFL slices.


# 4. Matchups, absences, roles

**Hypotheses.** (a) When regular team-mates are out, the remaining players' outputs rise and Paddy under-adjusts (the "Siakam question"). (b) Paddy lags role changes such as minutes trends and promotion to starter.
`miss_points` = recent points of the team's top-7 regulars who did not play (from the actual line-up, close to the injury report).

## 4a. Raw history: output vs own last-10 mean when regular team-mates are absent (miss_points = sum of absent top-7 regulars' recent points)

| missing_pts | n | pts_minus_m10 | ast_minus_m10 | reb_minus_m10 | mins_minus_m10 | fga_share |
|---|---|---|---|---|---|---|
| none | 4021 | -1.19 | -0.25 | -0.3 | -1.38 | 0.124 |
| 0-15 | 2741 | -0.8 | -0.12 | -0.19 | -0.53 | 0.134 |
| 15-30 | 3797 | 0.03 | -0 | 0.02 | -0.04 | 0.135 |
| 30+ | 3494 | 1.26 | 0.25 | 0.2 | 0.94 | 0.149 |

### Raw history, when 15+ points of regulars are missing: change in points vs last-10 mean by the player's scoring rank among those who played

| rank_present | n_missing | pts_vs_m10_missing | n_full | pts_vs_m10_full | uplift |
|---|---|---|---|---|---|
| 1 | 1235 | 0.28 | 576 | -1.36 | 1.64 |
| 2 | 1206 | 0.69 | 553 | -1.62 | 2.31 |
| 3 | 1174 | 0.46 | 543 | -0.98 | 1.44 |
| 4 | 1133 | 0.89 | 523 | -1.5 | 2.38 |
| 5 | 1021 | 0.97 | 510 | -0.78 | 1.75 |

## 4b. pplog main lines (over side, players with 20+ min): Paddy line vs last-10 mean, and the outcome, by absent team-mate points

| missing_pts | n | games | line_minus_m10_sd | value_minus_m10_sd | value_minus_line_sd | over_hit | over_roi |
|---|---|---|---|---|---|---|---|
| none | 3270 | 66 | 0.029 | -0.012 | -0.041 | 0.454 | -0.139 |
| 0-15 | 869 | 27 | -0.012 | -0.027 | -0.015 | 0.482 | -0.091 |
| 15-30 | 996 | 30 | 0.073 | 0.067 | -0.006 | 0.501 | -0.054 |
| 30+ | 467 | 17 | 0.294 | 0.325 | 0.03 | 0.469 | -0.11 |

### Priced: main overs / unders when 15+ points of regulars are absent (points-type stats only)

| slice | n | games | hit | avg_p | be_hit | roi | ci90 | roi_H1 | n_H1 | roi_H2 | n_H2 | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| over, absent>=15 | 810 | 40 | 0.491 | 1.859 | 0.539 | -0.089 | [-0.202, +0.018] | 0.004 | 171 | -0.114 | 639 | noise |
| over, nobody absent | 1756 | 66 | 0.457 | 1.86 | 0.539 | -0.15 | [-0.210, -0.090] | -0.125 | 1123 | -0.194 | 633 | LOSER |
| under, absent>=15 | 810 | 40 | 0.509 | 1.853 | 0.541 | -0.059 | [-0.166, +0.053] | -0.153 | 171 | -0.034 | 639 | noise |
| under, nobody absent | 1751 | 66 | 0.543 | 1.852 | 0.542 | 0.005 | [-0.053, +0.065] | -0.017 | 1120 | 0.046 | 631 | noise |
| over, absent>=20, player is top-2 scorer present | 328 | 37 | 0.534 | 1.859 | 0.539 | -0.008 | [-0.168, +0.144] | 0.183 | 86 | -0.076 | 242 | noise |
| under, absent>=20, player is top-2 scorer present | 328 | 37 | 0.466 | 1.851 | 0.542 | -0.135 | [-0.285, +0.022] | -0.334 | 86 | -0.065 | 242 | noise |

## 4c. Role change: minutes last 3 vs last 10, and starting status vs usual

| slice | n | games | hit | avg_p | be_hit | roi | ci90 | roi_H1 | n_H1 | roi_H2 | n_H2 | verdict | line-m10 (sd) | value-line (sd) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| over, mins3/mins10 <0.85 | 575 | 54 | 0.492 | 1.92 | 0.527 | -0.066 | [-0.198, +0.071] | -0.074 | 319 | -0.055 | 256 | noise | -0.087 | 0.074 |
| over, mins3/mins10 0.85-0.95 | 1455 | 78 | 0.491 | 1.918 | 0.528 | -0.068 | [-0.146, +0.007] | -0.073 | 754 | -0.063 | 701 | noise | 0.021 | 0.001 |
| over, mins3/mins10 flat | 2044 | 84 | 0.475 | 1.918 | 0.528 | -0.102 | [-0.167, -0.038] | -0.076 | 989 | -0.126 | 1055 | LOSER | 0.042 | 0.038 |
| over, mins3/mins10 1.05-1.15 | 1158 | 77 | 0.418 | 1.921 | 0.527 | -0.208 | [-0.295, -0.117] | -0.209 | 636 | -0.207 | 522 | LOSER | 0.14 | -0.162 |
| over, mins3/mins10 >1.15 | 721 | 62 | 0.449 | 1.919 | 0.529 | -0.148 | [-0.258, -0.030] | -0.103 | 277 | -0.176 | 444 | LOSER | 0.374 | -0.085 |
| under, mins3/mins10 <0.85 | 574 | 54 | 0.509 | 1.831 | 0.551 | -0.078 | [-0.207, +0.050] | -0.06 | 318 | -0.1 | 256 | noise | -0.087 | 0.074 |
| under, mins3/mins10 0.85-0.95 | 1449 | 78 | 0.509 | 1.841 | 0.55 | -0.073 | [-0.148, +0.004] | -0.066 | 751 | -0.081 | 698 | noise | 0.021 | 0.001 |
| under, mins3/mins10 flat | 2039 | 84 | 0.525 | 1.839 | 0.549 | -0.044 | [-0.107, +0.019] | -0.068 | 984 | -0.022 | 1055 | noise | 0.042 | 0.037 |
| under, mins3/mins10 1.05-1.15 | 1157 | 77 | 0.583 | 1.835 | 0.551 | 0.059 | [-0.028, +0.145] | 0.06 | 636 | 0.058 | 521 | promising | 0.141 | -0.162 |
| under, mins3/mins10 >1.15 | 718 | 62 | 0.55 | 1.842 | 0.549 | 0.005 | [-0.113, +0.113] | -0.036 | 276 | 0.031 | 442 | noise | 0.374 | -0.08 |

### Raw history: next-game minutes and points vs m3 and m10 by minutes trend (does a trend persist?)

| trend | n | mins_next_minus_m3 | mins_next_minus_m10 | pts_next_minus_m3 | pts_next_minus_m10 |
|---|---|---|---|---|---|
| <0.85 | 1335 | 2.99 | -2.71 | 2.02 | -0.91 |
| 0.85-0.95 | 2902 | 1.52 | -1.03 | 1.06 | -0.41 |
| flat | 5340 | -0.48 | -0.44 | -0.22 | -0.24 |
| 1.05-1.15 | 3212 | -1.92 | 0.62 | -1.45 | -0.06 |
| >1.15 | 1264 | -3.18 | 2.43 | -1.84 | 1.11 |

### Starting status today vs usual (today's starter flag is line-up news, ~30 min before tip; first prices are ~9h before)

| slice | n | games | hit | avg_p | be_hit | roi | ci90 | roi_H1 | n_H1 | roi_H2 | n_H2 | verdict | line-m10 (sd) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| over, demoted to bench | 437 | 55 | 0.487 | 1.918 | 0.529 | -0.082 | [-0.216, +0.056] | -0.094 | 290 | -0.058 | 147 | noise | -0.421 |
| over, promoted to starter | 351 | 44 | 0.376 | 1.906 | 0.531 | -0.291 | [-0.408, -0.185] | -0.452 | 142 | -0.182 | 209 | LOSER | 0.408 |
| over, usual role | 5165 | 88 | 0.471 | 1.92 | 0.528 | -0.107 | [-0.147, -0.066] | -0.088 | 2543 | -0.126 | 2622 | LOSER | 0.104 |
| under, demoted to bench | 437 | 55 | 0.513 | 1.846 | 0.549 | -0.068 | [-0.201, +0.063] | -0.061 | 290 | -0.08 | 147 | noise | -0.421 |
| under, promoted to starter | 351 | 44 | 0.624 | 1.846 | 0.547 | 0.146 | [+0.044, +0.258] | 0.284 | 142 | 0.052 | 209 | WORKING | 0.408 |
| under, usual role | 5149 | 88 | 0.529 | 1.837 | 0.55 | -0.037 | [-0.077, +0.001] | -0.052 | 2533 | -0.023 | 2616 | noise | 0.104 |

**Conclusions (direction 4).**
* (a) Rejected as an edge. The effect is real (+1.3 pts vs the last-10 mean with 30+ pts missing, against -1.2 with nobody missing), and the second- to fourth-best scorers gain most (+2.3). But Paddy's line moves with it (line - m10 = +0.29 sd against outcome +0.33 sd). For the top-2 scorers when 20+ pts are missing, overs made -0.8%.
* (b) The reverse of "Paddy lags": **Paddy over-follows role and minutes trends.** When minutes over the last 3 are up 5-15%, the line is set +0.14 sd above m10 and outcomes fall 0.16 sd short. Unders made +5.9% and overs -20.8%. In raw history next-game minutes revert about halfway (trend >1.15: next game -3.2 min vs m3, +2.4 vs m10).
  Players promoted to starter today: line +0.41 sd above m10, unders +14.6% (n=351, 44 games, CI +4% to +26%, both halves positive). But that uses today's starter flag, which is line-up news. These are the same mechanism as RULE U (section 5).
* Matchup / opponent concession is inside the projection model. We tested it no further as a separate rule.


# 5. Streaks, recency and line moves (the main finding)

**Hypothesis (stated before the tests).** Paddy's line over-weights the last few games relative to how outcomes actually depend on them. If so, lines that sit above the player's longer-run level should favour unders, and lines below it should favour overs (subject to the over-side margin).

## 5a. Weight on recent games: true outcomes (raw history) vs Paddy's main line (pplog)

OLS of y on [m3, m10, m20] (raw history, 2025-26 season, players with 20+ prior games and 20+ min/game) vs OLS of Paddy main line on the same features (pplog, first main line per player-stat-game). Coefficients sum to ~1; a bigger m3 weight for Paddy than for outcomes = over-reaction to the last few games.

| stat | n_hist | out_m3 | out_m10 | out_m20 | n_pp | paddy_m3 | paddy_m10 | paddy_m20 | pp_out_m3 | pp_out_m10 | pp_out_m20 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| points | 11513 | 0.129 | 0.227 | 0.551 | 809 | 0.268 | -0.054 | 0.73 | 0.157 | 0.069 | 0.721 |
| rebounds | 11513 | 0.106 | 0.099 | 0.71 | 770 | 0.178 | 0.012 | 0.767 | 0.14 | -0.016 | 0.765 |
| assists | 11513 | 0.199 | 0.139 | 0.588 | 567 | 0.263 | 0.06 | 0.559 | 0.329 | -0.012 | 0.48 |
| threes | 11513 | 0.093 | 0.069 | 0.707 | 657 | 0.109 | 0.119 | 0.441 | 0.095 | 0.122 | 0.541 |
| pra | 11513 | 0.177 | 0.242 | 0.503 | 651 | 0.288 | -0.048 | 0.717 | 0.139 | 0.202 | 0.585 |
| pr | 11513 | 0.149 | 0.222 | 0.54 | 780 | 0.25 | -0.017 | 0.725 | 0.129 | 0.182 | 0.623 |
| pa | 11513 | 0.16 | 0.261 | 0.504 | 601 | 0.325 | -0.08 | 0.687 | 0.187 | 0.098 | 0.648 |
| ra | 11513 | 0.186 | 0.123 | 0.606 | 564 | 0.218 | 0.08 | 0.628 | 0.197 | 0.089 | 0.538 |

## 5b. Main lines by Paddy's line move vs the player's previous logged game (first price, one row per player-stat-game-side)

| slice | n | games | hit | avg_p | be_hit | roi | ci90 | roi_H1 | n_H1 | roi_H2 | n_H2 | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| main over, line DOWN | 1052 | 73 | 0.524 | 1.818 | 0.553 | -0.051 | [-0.130, +0.020] | -0.03 | 433 | -0.066 | 619 | noise |
| main over, line same | 2072 | 74 | 0.469 | 1.958 | 0.519 | -0.094 | [-0.155, -0.033] | -0.052 | 846 | -0.123 | 1226 | LOSER |
| main over, line UP | 1136 | 73 | 0.423 | 1.93 | 0.522 | -0.19 | [-0.272, -0.109] | -0.136 | 409 | -0.221 | 727 | LOSER |
| main under, line DOWN | 1045 | 73 | 0.478 | 1.912 | 0.526 | -0.092 | [-0.165, -0.009] | -0.112 | 429 | -0.078 | 616 | LOSER |
| main under, line same | 2069 | 74 | 0.531 | 1.815 | 0.558 | -0.047 | [-0.102, +0.010] | -0.08 | 845 | -0.024 | 1224 | noise |
| main under, line UP | 1135 | 73 | 0.578 | 1.804 | 0.557 | 0.04 | [-0.037, +0.118] | -0.014 | 408 | 0.07 | 727 | noise |

### Main lines: previous game over/under the previous line x move

| slice | n | games | hit | avg_p | be_hit | roi | ci90 | roi_H1 | n_H1 | roi_H2 | n_H2 | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| main over; prev went OVER; line DOWN | 285 | 55 | 0.474 | 1.813 | 0.554 | -0.138 | [-0.285, +0.003] | -0.141 | 114 | -0.136 | 171 | noise |
| main over; prev went OVER; line same | 961 | 74 | 0.483 | 1.907 | 0.531 | -0.088 | [-0.169, -0.009] | -0.034 | 383 | -0.123 | 578 | LOSER |
| main over; prev went OVER; line UP | 810 | 71 | 0.415 | 1.924 | 0.524 | -0.207 | [-0.288, -0.123] | -0.173 | 297 | -0.226 | 513 | LOSER |
| main over; prev went UNDER; line DOWN | 767 | 73 | 0.542 | 1.82 | 0.552 | -0.019 | [-0.101, +0.057] | 0.01 | 319 | -0.039 | 448 | noise |
| main over; prev went UNDER; line same | 1111 | 74 | 0.457 | 2.003 | 0.508 | -0.099 | [-0.170, -0.026] | -0.067 | 463 | -0.122 | 648 | LOSER |
| main over; prev went UNDER; line UP | 326 | 59 | 0.442 | 1.943 | 0.519 | -0.149 | [-0.292, -0.006] | -0.037 | 112 | -0.208 | 214 | LOSER |
| main under; prev went OVER; line DOWN | 280 | 55 | 0.529 | 1.91 | 0.526 | 0.01 | [-0.131, +0.159] | 0.039 | 111 | -0.009 | 169 | noise |
| main under; prev went OVER; line same | 959 | 74 | 0.518 | 1.855 | 0.546 | -0.049 | [-0.124, +0.027] | -0.093 | 382 | -0.02 | 577 | noise |
| main under; prev went OVER; line UP | 810 | 71 | 0.585 | 1.809 | 0.556 | 0.056 | [-0.023, +0.136] | 0.022 | 297 | 0.076 | 513 | promising |
| main under; prev went UNDER; line DOWN | 765 | 73 | 0.459 | 1.913 | 0.526 | -0.129 | [-0.207, -0.044] | -0.165 | 318 | -0.104 | 447 | LOSER |
| main under; prev went UNDER; line same | 1110 | 74 | 0.542 | 1.78 | 0.569 | -0.045 | [-0.112, +0.021] | -0.07 | 463 | -0.027 | 647 | noise |
| main under; prev went UNDER; line UP | 325 | 58 | 0.56 | 1.791 | 0.561 | -0.001 | [-0.142, +0.137] | -0.112 | 111 | 0.056 | 214 | noise |

## 5c. Alt overs 1.15-3.0 (one rung per player-stat-game, closest to 2.0) by main-line move

| slice | n | games | hit | avg_p | be_hit | roi | ci90 | roi_H1 | n_H1 | roi_H2 | n_H2 | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| alt over, main line DOWN | 340 | 71 | 0.559 | 1.946 | 0.551 | 0.009 | [-0.084, +0.104] | -0.009 | 147 | 0.023 | 193 | noise |
| alt over, main line same | 1223 | 74 | 0.591 | 1.666 | 0.652 | -0.096 | [-0.141, -0.053] | -0.077 | 508 | -0.11 | 715 | LOSER |
| alt over, main line UP | 434 | 72 | 0.525 | 1.71 | 0.616 | -0.159 | [-0.226, -0.087] | -0.166 | 161 | -0.154 | 273 | LOSER |
| alt over, line DOWN, k10>=8 | 46 | 32 | 0.891 | 1.401 | 0.734 | 0.241 | [+0.109, +0.365] | 0.19 | 20 | 0.281 | 26 | WORKING |
| alt over, line DOWN, k10<8 | 294 | 70 | 0.507 | 2.031 | 0.523 | -0.028 | [-0.128, +0.078] | -0.041 | 127 | -0.018 | 167 | noise |

### Same, by stat (line DOWN only)

| slice | n | games | hit | avg_p | be_hit | roi | ci90 | roi_H1 | n_H1 | roi_H2 | n_H2 | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Points | 186 | 63 | 0.543 | 1.92 | 0.546 | -0.016 | [-0.131, +0.095] | 0.014 | 76 | -0.037 | 110 | noise |
| Assists | 53 | 37 | 0.679 | 1.791 | 0.615 | 0.137 | [-0.074, +0.342] | 0.212 | 23 | 0.08 | 30 | promising |
| Rebounds | 63 | 41 | 0.635 | 1.978 | 0.555 | 0.151 | [-0.057, +0.355] | 0.047 | 30 | 0.245 | 33 | promising |
| Three pointers made | 23 | 20 | 0.348 | 2.337 | 0.471 | -0.287 | [-0.611, +0.100] | -0.503 | 10 | -0.121 | 13 | tiny |

## 5d. Main lines by where Paddy sets the line vs the player's last-10 mean (in sd of last 10)

| slice | n | games | hit | avg_p | be_hit | roi | ci90 | roi_H1 | n_H1 | roi_H2 | n_H2 | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| main over, line-m10 (-9.0, -0.5] | 704 | 85 | 0.527 | 1.81 | 0.557 | -0.058 | [-0.140, +0.034] | -0.084 | 461 | -0.008 | 243 | noise |
| main over, line-m10 (-0.5, -0.2] | 1039 | 88 | 0.529 | 1.871 | 0.54 | -0.016 | [-0.078, +0.046] | -0.006 | 562 | -0.027 | 477 | noise |
| main over, line-m10 (-0.2, 0.2] | 1921 | 88 | 0.467 | 1.918 | 0.528 | -0.111 | [-0.165, -0.057] | -0.102 | 870 | -0.118 | 1051 | LOSER |
| main over, line-m10 (0.2, 0.5] | 1150 | 88 | 0.425 | 1.963 | 0.516 | -0.175 | [-0.245, -0.106] | -0.187 | 524 | -0.166 | 626 | LOSER |
| main over, line-m10 (0.5, 9.0] | 1139 | 87 | 0.413 | 1.986 | 0.511 | -0.195 | [-0.274, -0.115] | -0.155 | 558 | -0.232 | 581 | LOSER |
| main under, line-m10 (-9.0, -0.5] | 702 | 85 | 0.474 | 1.945 | 0.52 | -0.091 | [-0.187, -0.005] | -0.066 | 461 | -0.139 | 241 | LOSER |
| main under, line-m10 (-0.5, -0.2] | 1034 | 87 | 0.472 | 1.878 | 0.538 | -0.122 | [-0.181, -0.058] | -0.123 | 558 | -0.12 | 476 | LOSER |
| main under, line-m10 (-0.2, 0.2] | 1919 | 88 | 0.533 | 1.834 | 0.551 | -0.029 | [-0.079, +0.022] | -0.033 | 869 | -0.025 | 1050 | noise |
| main under, line-m10 (0.2, 0.5] | 1149 | 88 | 0.574 | 1.796 | 0.562 | 0.025 | [-0.038, +0.091] | 0.031 | 524 | 0.021 | 625 | promising |
| main under, line-m10 (0.5, 9.0] | 1133 | 87 | 0.587 | 1.785 | 0.566 | 0.041 | [-0.034, +0.120] | 0.007 | 553 | 0.074 | 580 | promising |

## 5e. Early-season check: outcome weights on recent form, early 2025-26 vs rest (m3 and m10 only, players with 10+ prior games; the early-season m10 reaches back into last season)

| period | stat | n | w_m3 | se_m3 | w_m10 |
|---|---|---|---|---|---|
| early season 21 Oct-20 Nov 2025 | points | 604 | 0.156 | 0.081 | 0.78 |
| early season 21 Oct-20 Nov 2025 | rebounds | 604 | 0.075 | 0.082 | 0.809 |
| early season 21 Oct-20 Nov 2025 | assists | 604 | 0.234 | 0.079 | 0.626 |
| early season 21 Oct-20 Nov 2025 | pra | 604 | 0.191 | 0.079 | 0.752 |
| rest of 2025-26 (before 20 Oct 2026) | points | 13444 | 0.111 | 0.018 | 0.782 |
| rest of 2025-26 (before 20 Oct 2026) | rebounds | 13444 | 0.116 | 0.018 | 0.754 |
| rest of 2025-26 (before 20 Oct 2026) | assists | 13444 | 0.184 | 0.018 | 0.701 |
| rest of 2025-26 (before 20 Oct 2026) | pra | 13444 | 0.166 | 0.018 | 0.748 |

## Composite: Paddy main line vs a raw-history baseline (weights fitted before the pplog period)

Baseline weights [const, m3, m10, m20]: points [0.77, 0.17, 0.26, 0.5]; rebounds [0.29, 0.15, 0.14, 0.64]; assists [0.16, 0.2, 0.19, 0.55]; threes [0.14, 0.12, 0.1, 0.67]; steals [0.21, 0.08, 0.07, 0.58]; blocks [0.08, 0.08, 0.09, 0.68]; pra [1.05, 0.23, 0.27, 0.44]; pr [1.0, 0.2, 0.26, 0.48]; pa [0.81, 0.2, 0.29, 0.45]; ra [0.43, 0.21, 0.18, 0.54]

| slice | n | games | hit | avg_p | be_hit | roi | ci90 | roi_H1 | n_H1 | roi_H2 | n_H2 | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| main under, z (-9.0, -0.5] | 442 | 77 | 0.416 | 1.962 | 0.516 | -0.191 | [-0.306, -0.080] | -0.139 | 289 | -0.289 | 153 | LOSER |
| main under, z (-0.5, -0.25] | 771 | 86 | 0.492 | 1.926 | 0.525 | -0.066 | [-0.145, +0.015] | -0.103 | 446 | -0.014 | 325 | noise |
| main under, z (-0.25, 0.0] | 1353 | 87 | 0.52 | 1.859 | 0.543 | -0.041 | [-0.105, +0.016] | -0.001 | 640 | -0.078 | 713 | noise |
| main under, z (0.0, 0.25] | 1424 | 88 | 0.529 | 1.818 | 0.555 | -0.044 | [-0.101, +0.014] | -0.068 | 675 | -0.022 | 749 | noise |
| main under, z (0.25, 0.5] | 977 | 88 | 0.572 | 1.779 | 0.568 | 0.012 | [-0.060, +0.084] | 0.037 | 445 | -0.009 | 532 | noise |
| main under, z (0.5, 9.0] | 986 | 81 | 0.606 | 1.774 | 0.569 | 0.069 | [-0.024, +0.159] | 0.004 | 480 | 0.131 | 506 | promising |
| main over, z (-9.0, -0.5] | 442 | 77 | 0.584 | 1.798 | 0.561 | 0.046 | [-0.055, +0.151] | -0.009 | 289 | 0.15 | 153 | noise |
| main over, z (-0.5, -0.25] | 771 | 86 | 0.508 | 1.825 | 0.553 | -0.082 | [-0.160, -0.004] | -0.036 | 446 | -0.145 | 325 | LOSER |
| main over, z (-0.25, 0.0] | 1353 | 87 | 0.48 | 1.886 | 0.535 | -0.1 | [-0.159, -0.035] | -0.141 | 640 | -0.064 | 713 | LOSER |
| main over, z (0.0, 0.25] | 1424 | 88 | 0.471 | 1.935 | 0.523 | -0.094 | [-0.155, -0.034] | -0.071 | 675 | -0.116 | 749 | LOSER |
| main over, z (0.25, 0.5] | 977 | 88 | 0.428 | 1.986 | 0.51 | -0.161 | [-0.239, -0.083] | -0.177 | 445 | -0.147 | 532 | LOSER |
| main over, z (0.5, 9.0] | 986 | 81 | 0.394 | 2.002 | 0.508 | -0.227 | [-0.319, -0.130] | -0.168 | 480 | -0.283 | 506 | LOSER |

### Alt overs below the main line (1.15-3.0, one rung per player-stat-game) by z

| slice | n | games | hit | avg_p | be_hit | roi | ci90 | roi_H1 | n_H1 | roi_H2 | n_H2 | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| alt over, z (-9.0, -0.5] | 101 | 49 | 0.703 | 1.409 | 0.72 | -0.009 | [-0.100, +0.083] | -0.038 | 63 | 0.04 | 38 | noise |
| alt over, z (-0.5, -0.25] | 243 | 79 | 0.65 | 1.393 | 0.727 | -0.11 | [-0.188, -0.028] | -0.065 | 147 | -0.179 | 96 | LOSER |
| alt over, z (-0.25, 0.0] | 557 | 85 | 0.686 | 1.395 | 0.726 | -0.059 | [-0.112, -0.003] | -0.05 | 269 | -0.067 | 288 | LOSER |
| alt over, z (0.0, 0.25] | 610 | 87 | 0.662 | 1.379 | 0.734 | -0.097 | [-0.136, -0.058] | -0.085 | 299 | -0.109 | 311 | LOSER |
| alt over, z (0.25, 0.5] | 473 | 87 | 0.641 | 1.397 | 0.724 | -0.112 | [-0.159, -0.065] | -0.104 | 226 | -0.12 | 247 | LOSER |
| alt over, z (0.5, 9.0] | 422 | 80 | 0.628 | 1.424 | 0.712 | -0.116 | [-0.182, -0.046] | -0.101 | 211 | -0.131 | 211 | LOSER |

### Pre-stated rules

| slice | n | games | hit | avg_p | be_hit | roi | ci90 | roi_H1 | n_H1 | roi_H2 | n_H2 | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| RULE U: main under, z >= +0.25 | 1963 | 88 | 0.589 | 1.776 | 0.569 | 0.041 | [-0.022, +0.102] | 0.02 | 925 | 0.059 | 1038 | promising |
| RULE U, 1.60-2.20 | 1669 | 88 | 0.578 | 1.823 | 0.551 | 0.05 | [-0.018, +0.119] | 0.025 | 791 | 0.072 | 878 | promising |
| RULE A: alt over below main, z <= -0.25 | 344 | 82 | 0.666 | 1.398 | 0.725 | -0.08 | [-0.145, -0.010] | -0.057 | 210 | -0.117 | 134 | LOSER |
| RULE A and k10>=8 | 204 | 72 | 0.696 | 1.362 | 0.743 | -0.064 | [-0.135, +0.011] | -0.046 | 136 | -0.099 | 68 | noise |
|   RULE U Assists | 189 | 79 | 0.635 | 1.758 | 0.575 | 0.098 | [-0.021, +0.209] | 0.142 | 91 | 0.057 | 98 | promising |
|   RULE U Three pointers made | 201 | 75 | 0.647 | 1.6 | 0.633 | 0.035 | [-0.065, +0.132] | 0.1 | 97 | -0.026 | 104 | noise |
|   RULE U Points and rebounds | 279 | 85 | 0.559 | 1.834 | 0.547 | 0.026 | [-0.073, +0.120] | 0 | 134 | 0.05 | 145 | noise |
|   RULE U Points | 262 | 83 | 0.557 | 1.848 | 0.543 | 0.032 | [-0.062, +0.127] | -0.013 | 124 | 0.071 | 138 | noise |
|   RULE U Points and assists | 219 | 81 | 0.603 | 1.837 | 0.546 | 0.107 | [+0.012, +0.205] | 0.056 | 98 | 0.148 | 121 | WORKING |
|   RULE U Points rebounds and assists | 257 | 85 | 0.549 | 1.852 | 0.541 | 0.014 | [-0.083, +0.109] | -0.06 | 122 | 0.081 | 135 | noise |
|   RULE U Rebounds and assists | 197 | 79 | 0.533 | 1.816 | 0.554 | -0.033 | [-0.140, +0.070] | -0.037 | 91 | -0.029 | 106 | noise |
|   RULE U Rebounds | 252 | 83 | 0.607 | 1.753 | 0.576 | 0.064 | [-0.024, +0.148] | 0.022 | 118 | 0.101 | 134 | promising |
|   RULE U Steals | 90 | 45 | 0.722 | 1.484 | 0.678 | 0.063 | [-0.073, +0.183] | 0.069 | 41 | 0.057 | 49 | promising |

Rule U overlap: share with today-starter promoted 0.11, share minutes trend up (m3/m10>1.05) 0.38.


### By ISO week

| slice | n | games | hit | avg_p | be_hit | roi | ci90 | roi_H1 | n_H1 | roi_H2 | n_H2 | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| RULE U W43 | 695 | 38 | 0.586 | 1.784 | 0.566 | 0.04 | [-0.052, +0.135] | 0.04 | 695 |  | 0 | noise |
| RULE U W44 | 1216 | 48 | 0.592 | 1.774 | 0.569 | 0.044 | [-0.038, +0.124] | -0.043 | 230 | 0.065 | 986 | noise |
| RULE U W45 | 52 | 2 | 0.577 | 1.709 | 0.593 | -0.045 | [-0.152, +0.141] |  | 0 | -0.045 | 52 | tiny |
| RULE A W43 | 157 | 36 | 0.662 | 1.401 | 0.722 | -0.083 | [-0.182, +0.021] | -0.083 | 157 |  | 0 | noise |
| RULE A W44 | 180 | 44 | 0.672 | 1.393 | 0.728 | -0.072 | [-0.167, +0.019] | 0.019 | 53 | -0.109 | 127 | noise |
| RULE A W45 | 7 | 2 | 0.571 | 1.428 | 0.708 | -0.248 | [-1.000, +0.053] |  | 0 | -0.248 | 7 | tiny |

RULE U without its top-3 profit players (Darius Garland, Donovan Clingan, Jalen Johnson): {'n': 1867, 'roi': np.float64(0.014), 'ci90': '[-0.047, +0.073]'}

RULE A without its top-3 profit players (VJ Edgecombe, Toumani Camara, Jaden McDaniels): {'n': 322, 'roi': np.float64(-0.11), 'ci90': '[-0.180, -0.037]'}

## 5f. RULE U robustness grid (18 cells, pre-stated)

| slice | n | games | hit | avg_p | be_hit | roi | ci90 | roi_H1 | n_H1 | roi_H2 | n_H2 | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| fitted z>=0.25 all | 1963 | 88 | 0.589 | 1.776 | 0.569 | 0.041 | [-0.022, +0.102] | 0.02 | 925 | 0.059 | 1038 | promising |
| fitted z>=0.25 1.60-2.20 | 1669 | 88 | 0.578 | 1.823 | 0.551 | 0.05 | [-0.018, +0.119] | 0.025 | 791 | 0.072 | 878 | promising |
| fitted z>=0.5 all | 986 | 81 | 0.606 | 1.774 | 0.569 | 0.069 | [-0.024, +0.159] | 0.004 | 480 | 0.131 | 506 | promising |
| fitted z>=0.5 1.60-2.20 | 843 | 81 | 0.593 | 1.821 | 0.552 | 0.079 | [-0.025, +0.180] | -0.009 | 407 | 0.16 | 436 | noise |
| fitted z>=0.75 all | 453 | 73 | 0.605 | 1.767 | 0.571 | 0.061 | [-0.051, +0.179] | -0.005 | 246 | 0.14 | 207 | noise |
| fitted z>=0.75 1.60-2.20 | 383 | 67 | 0.593 | 1.819 | 0.552 | 0.074 | [-0.070, +0.213] | -0.025 | 206 | 0.189 | 177 | noise |
| m10 z>=0.25 all | 2074 | 88 | 0.578 | 1.788 | 0.565 | 0.026 | [-0.036, +0.084] | 0.013 | 989 | 0.038 | 1085 | promising |
| m10 z>=0.25 1.60-2.20 | 1790 | 88 | 0.563 | 1.831 | 0.549 | 0.028 | [-0.038, +0.090] | 0.012 | 847 | 0.043 | 943 | promising |
| m10 z>=0.5 all | 1152 | 88 | 0.585 | 1.781 | 0.567 | 0.035 | [-0.041, +0.109] | -0.005 | 568 | 0.075 | 584 | noise |
| m10 z>=0.5 1.60-2.20 | 994 | 86 | 0.572 | 1.826 | 0.551 | 0.043 | [-0.044, +0.126] | -0.001 | 482 | 0.084 | 512 | noise |
| m10 z>=0.75 all | 558 | 81 | 0.608 | 1.773 | 0.57 | 0.072 | [-0.044, +0.176] | 0.041 | 284 | 0.105 | 274 | promising |
| m10 z>=0.75 1.60-2.20 | 483 | 76 | 0.598 | 1.817 | 0.553 | 0.085 | [-0.035, +0.210] | 0.043 | 248 | 0.13 | 235 | promising |
| m20 z>=0.25 all | 1652 | 88 | 0.586 | 1.776 | 0.569 | 0.033 | [-0.035, +0.100] | -0.005 | 733 | 0.064 | 919 | noise |
| m20 z>=0.25 1.60-2.20 | 1393 | 88 | 0.572 | 1.823 | 0.551 | 0.04 | [-0.036, +0.115] | -0.008 | 616 | 0.078 | 777 | noise |
| m20 z>=0.5 all | 831 | 77 | 0.613 | 1.765 | 0.572 | 0.07 | [-0.019, +0.151] | 0.027 | 361 | 0.103 | 470 | promising |
| m20 z>=0.5 1.60-2.20 | 698 | 74 | 0.595 | 1.816 | 0.553 | 0.075 | [-0.030, +0.170] | 0.02 | 294 | 0.114 | 404 | promising |
| m20 z>=0.75 all | 425 | 70 | 0.635 | 1.772 | 0.57 | 0.115 | [-0.015, +0.230] | 0.072 | 191 | 0.151 | 234 | promising |
| m20 z>=0.75 1.60-2.20 | 357 | 66 | 0.625 | 1.823 | 0.551 | 0.133 | [-0.007, +0.268] | 0.074 | 155 | 0.178 | 202 | promising |

18/18 cells positive; 11/18 positive in both halves.

### Mirror (overs when the line is BELOW the baseline)

| slice | n | games | hit | avg_p | be_hit | roi | ci90 | roi_H1 | n_H1 | roi_H2 | n_H2 | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| mirror: main OVER, fitted z<=-0.25 | 1213 | 87 | 0.536 | 1.815 | 0.556 | -0.035 | [-0.102, +0.034] | -0.025 | 735 | -0.051 | 478 | noise |
| mirror: main OVER, fitted z<=-0.5 | 442 | 77 | 0.584 | 1.798 | 0.561 | 0.046 | [-0.055, +0.151] | -0.009 | 289 | 0.15 | 153 | noise |
| mirror: main OVER, m10 z<=-0.25 | 1551 | 88 | 0.525 | 1.841 | 0.549 | -0.041 | [-0.101, +0.020] | -0.057 | 927 | -0.018 | 624 | noise |
| mirror: main OVER, m10 z<=-0.5 | 704 | 85 | 0.527 | 1.81 | 0.557 | -0.058 | [-0.140, +0.034] | -0.084 | 461 | -0.008 | 243 | noise |
| mirror: main OVER, m20 z<=-0.25 | 1659 | 87 | 0.524 | 1.838 | 0.549 | -0.045 | [-0.109, +0.020] | -0.022 | 949 | -0.076 | 710 | noise |
| mirror: main OVER, m20 z<=-0.5 | 741 | 85 | 0.549 | 1.811 | 0.557 | -0.008 | [-0.096, +0.086] | -0.03 | 431 | 0.021 | 310 | noise |

**Conclusions (direction 5).**
* 5a is structural: Paddy's NBA main line weights the last 3 games about twice as much as outcomes justify, in every scoring stat, and not because the early season is special (5e). It is measured on about 800 Paddy lines against 11.5k raw outcomes.
* 5d and the composite show a monotone gradient. Unders go from -19% at z <= -0.5 to +6.9% at z >= 0.5. Overs mirror it, from +4.6% to -22.7%, but are hurt by Paddy's over-side shading.
* **RULE U** (main under, z >= 0.25 vs the raw-fitted baseline) made +4.1% overall and +5.0% at 1.60-2.20. 18 of 18 grid cells were positive, 11 of 18 in both halves, and it is positive in W43 and W44. It is +1.4% without its top 3 players. No cell's CI excludes zero on its own, and the cells overlap heavily. **Verdict: the most credible lead, promising-but-unproven. Track it.**
* Paddy's main-line moves vs the previous game: when the line went UP, overs made -19% and unders +4%. When it went DOWN, alt overs made +0.9% and +24% for k10>=8 (n=46). This is consistent with the mechanism, but the cells are small.


# 6. NFL

## 6a. NFL skew (raw history before the pplog period): share of games BELOW the player's own last-10 mean and below his last-10 median; mean-median gap

| pos | stat | n | below_mean10 | below_med10 | mean_minus_median | skew_proxy |
|---|---|---|---|---|---|---|
| QB | pass_yds | 1889 | 0.522 | 0.532 | -1.7 | -0.024 |
| QB | rush_yds | 1702 | 0.612 | 0.532 | 2.5 | 0.19 |
| QB | pass_rush_yds | 1889 | 0.526 | 0.538 | -2.74 | -0.035 |
| QB | pass_td | 1822 | 0.548 | 0.405 | 0.1 | 0.089 |
| RB | rush_yds | 2782 | 0.606 | 0.555 | 4.28 | 0.125 |
| RB | rec_yds | 4142 | 0.642 | 0.475 | 3.95 | 0.29 |
| RB | rec | 4043 | 0.574 | 0.426 | 0.24 | 0.157 |
| RB | rush_rec_yds | 2782 | 0.596 | 0.554 | 4.16 | 0.107 |
| WR | rec_yds | 5144 | 0.606 | 0.543 | 4.69 | 0.148 |
| WR | rec | 5144 | 0.58 | 0.497 | 0.19 | 0.089 |
| TE | rec_yds | 1851 | 0.599 | 0.532 | 3.85 | 0.149 |
| TE | rec | 1851 | 0.58 | 0.484 | 0.18 | 0.084 |

## 6b. pplog main lines: where Paddy sets the line vs the player's last-10 mean and median, and under results, by position x stat

| slice | n | games | hit | avg_p | be_hit | roi | ci90 | roi_H1 | n_H1 | roi_H2 | n_H2 | verdict | line-mean10 | line-med10 | value-line |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| QB Passing and rushing yards UNDER | 49 | 26 | 0.51 | 1.833 | 0.546 | -0.065 | [-0.290, +0.150] | -0.267 | 25 | 0.146 | 24 | noise | 14.4 | 12.1 | -0.5 |
| QB Passing touchdowns UNDER | 53 | 27 | 0.547 | 1.865 | 0.555 | -0.014 | [-0.272, +0.255] | 0.023 | 27 | -0.053 | 26 | noise | -0 | 0 | -0.5 |
| QB Passing yards UNDER | 53 | 27 | 0.434 | 1.833 | 0.546 | -0.205 | [-0.423, +0.022] | -0.321 | 27 | -0.084 | 26 | noise | 10.8 | 8.1 | 13.5 |
| QB Rushing yards UNDER | 53 | 27 | 0.679 | 1.834 | 0.546 | 0.242 | [+0.038, +0.433] | 0.147 | 27 | 0.341 | 26 | WORKING | -2.8 | -0.7 | -2.5 |
| RB Receiving receptions UNDER | 73 | 27 | 0.507 | 1.783 | 0.571 | -0.121 | [-0.275, +0.063] | -0.135 | 40 | -0.106 | 33 | noise | 0 | 0.3 | -0.5 |
| RB Receiving yards UNDER | 73 | 27 | 0.479 | 1.83 | 0.547 | -0.123 | [-0.303, +0.066] | -0.129 | 40 | -0.114 | 33 | noise | -2.4 | 1.5 | 0.5 |
| RB Rushing and receiving yards UNDER | 69 | 27 | 0.493 | 1.833 | 0.546 | -0.096 | [-0.252, +0.065] | -0.162 | 35 | -0.028 | 34 | noise | -0.5 | 4.3 | 1.5 |
| RB Rushing yards UNDER | 93 | 27 | 0.505 | 1.833 | 0.545 | -0.074 | [-0.221, +0.076] | -0.104 | 47 | -0.044 | 46 | noise | -3.1 | 1.4 | -0.5 |
| TE Receiving receptions UNDER | 78 | 27 | 0.526 | 1.813 | 0.562 | -0.057 | [-0.242, +0.142] | -0.067 | 39 | -0.046 | 39 | noise | -0.1 | 0.1 | -0.5 |
| TE Receiving yards UNDER | 77 | 27 | 0.377 | 1.828 | 0.547 | -0.313 | [-0.492, -0.114] | -0.233 | 38 | -0.392 | 39 | LOSER | -3.4 | -0.6 | 4.5 |
| WR Receiving receptions UNDER | 145 | 27 | 0.552 | 1.802 | 0.564 | -0.029 | [-0.146, +0.080] | 0.101 | 73 | -0.161 | 72 | noise | 0.1 | 0.3 | -0.5 |
| WR Receiving yards UNDER | 145 | 27 | 0.559 | 1.831 | 0.546 | 0.023 | [-0.097, +0.136] | 0.055 | 73 | -0.009 | 72 | noise | -2.2 | 2.9 | -2.5 |

### Pre-stated: main UNDER when Paddy's line > player's last-10 median by >= 10% of the line (yards stats)

| slice | n | games | hit | avg_p | be_hit | roi | ci90 | roi_H1 | n_H1 | roi_H2 | n_H2 | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| under, line >= median +10% | 247 | 27 | 0.498 | 1.827 | 0.548 | -0.09 | [-0.201, +0.021] | -0.098 | 130 | -0.081 | 117 | noise |
| under, line < median +10% | 371 | 27 | 0.518 | 1.835 | 0.545 | -0.051 | [-0.142, +0.040] | -0.105 | 182 | 0.001 | 189 | noise |
| under, line >= median +10%, non-QB | 199 | 27 | 0.518 | 1.829 | 0.547 | -0.053 | [-0.180, +0.064] | 0.014 | 103 | -0.125 | 96 | noise |
| QB rushing under (stage-1 candidate) | 53 | 27 | 0.679 | 1.834 | 0.546 | 0.242 | [+0.038, +0.433] | 0.147 | 27 | 0.341 | 26 | WORKING |
| QB rushing under, line >= median | 28 | 21 | 0.714 | 1.821 | 0.551 | 0.305 | [+0.046, +0.557] | 0.14 | 16 | 0.525 | 12 | tiny |
| QB rushing under, line < median | 25 | 19 | 0.64 | 1.849 | 0.541 | 0.172 | [-0.120, +0.450] | 0.157 | 11 | 0.184 | 14 | tiny |

### Raw history: QB rushing yards, share below last-10 mean / median by rushing profile

| profile | n | mean10 | below_mean | below_med |
|---|---|---|---|---|
| <2.5 att | 603 | 5.3 | 0.61 | 0.461 |
| 2.5-4.5 | 778 | 15.1 | 0.599 | 0.518 |
| 4.5-7 | 320 | 28.4 | 0.6 | 0.566 |
| 7+ (runner) | 188 | 46.2 | 0.628 | 0.569 |

## 6c. Game script (pre-game Elo expected margin, ~25 Elo per point) x position x stat, main lines

| slice | n | games | hit | avg_p | be_hit | roi | ci90 | roi_H1 | n_H1 | roi_H2 | n_H2 | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| QB Passing yards | underdog 4+ | OVER | 13 | 13 | 0.462 | 1.833 | 0.546 | -0.154 | [-0.577, +0.269] | -0.267 | 5 | -0.083 | 8 | tiny |
| QB Passing yards | underdog 4+ | UNDER | 13 | 13 | 0.538 | 1.833 | 0.546 | -0.013 | [-0.436, +0.410] | 0.1 | 5 | -0.083 | 8 | tiny |
| QB Passing yards | close | OVER | 26 | 13 | 0.654 | 1.833 | 0.546 | 0.198 | [-0.154, +0.551] | 0.26 | 16 | 0.1 | 10 | tiny |
| QB Passing yards | close | UNDER | 26 | 13 | 0.346 | 1.833 | 0.546 | -0.366 | [-0.718, -0.013] | -0.427 | 16 | -0.267 | 10 | tiny |
| QB Passing yards | favourite 4+ | OVER | 14 | 14 | 0.5 | 1.833 | 0.546 | -0.084 | [-0.476, +0.309] | 0.222 | 6 | -0.313 | 8 | tiny |
| QB Passing yards | favourite 4+ | UNDER | 14 | 14 | 0.5 | 1.833 | 0.546 | -0.083 | [-0.476, +0.309] | -0.389 | 6 | 0.146 | 8 | tiny |
| QB Rushing yards | underdog 4+ | OVER | 13 | 13 | 0.231 | 1.846 | 0.542 | -0.577 | [-0.859, -0.154] | -0.267 | 5 | -0.771 | 8 | tiny |
| QB Rushing yards | underdog 4+ | UNDER | 13 | 13 | 0.769 | 1.825 | 0.548 | 0.402 | [-0.013, +0.692] | 0.079 | 5 | 0.604 | 8 | tiny |
| QB Rushing yards | close | OVER | 26 | 13 | 0.346 | 1.841 | 0.545 | -0.363 | [-0.579, -0.164] | -0.438 | 16 | -0.244 | 10 | tiny |
| QB Rushing yards | close | UNDER | 26 | 13 | 0.654 | 1.848 | 0.543 | 0.205 | [+0.014, +0.416] | 0.254 | 16 | 0.126 | 10 | tiny |
| QB Rushing yards | favourite 4+ | OVER | 14 | 14 | 0.357 | 1.866 | 0.537 | -0.345 | [-0.738, +0.047] | -0.084 | 6 | -0.542 | 8 | tiny |
| QB Rushing yards | favourite 4+ | UNDER | 14 | 14 | 0.643 | 1.817 | 0.551 | 0.163 | [-0.222, +0.553] | -0.084 | 6 | 0.347 | 8 | tiny |
| RB Receiving receptions | underdog 4+ | OVER | 19 | 14 | 0.737 | 1.941 | 0.522 | 0.428 | [+0.033, +0.720] | 0.083 | 7 | 0.629 | 12 | tiny |
| RB Receiving receptions | underdog 4+ | UNDER | 19 | 14 | 0.263 | 1.753 | 0.578 | -0.553 | [-0.811, -0.218] | -0.258 | 7 | -0.725 | 12 | tiny |
| RB Receiving receptions | close | OVER | 34 | 13 | 0.441 | 1.907 | 0.535 | -0.198 | [-0.467, +0.044] | -0.09 | 25 | -0.5 | 9 | noise |
| RB Receiving receptions | close | UNDER | 34 | 13 | 0.559 | 1.819 | 0.561 | -0.021 | [-0.268, +0.265] | -0.163 | 25 | 0.374 | 9 | noise |
| RB Receiving receptions | favourite 4+ | OVER | 20 | 13 | 0.35 | 1.984 | 0.515 | -0.347 | [-0.680, +0.013] | -0.317 | 8 | -0.366 | 12 | tiny |
| RB Receiving receptions | favourite 4+ | UNDER | 20 | 13 | 0.65 | 1.749 | 0.582 | 0.117 | [-0.222, +0.444] | 0.062 | 8 | 0.154 | 12 | tiny |
| RB Receiving yards | underdog 4+ | OVER | 19 | 14 | 0.684 | 1.833 | 0.546 | 0.254 | [-0.084, +0.527] | 0.047 | 7 | 0.375 | 12 | tiny |
| RB Receiving yards | underdog 4+ | UNDER | 19 | 14 | 0.316 | 1.833 | 0.546 | -0.421 | [-0.695, -0.084] | -0.214 | 7 | -0.542 | 12 | tiny |
| RB Receiving yards | close | OVER | 34 | 13 | 0.471 | 1.843 | 0.543 | -0.132 | [-0.389, +0.146] | -0.04 | 25 | -0.389 | 9 | noise |
| RB Receiving yards | close | UNDER | 34 | 13 | 0.529 | 1.827 | 0.548 | -0.033 | [-0.309, +0.222] | -0.12 | 25 | 0.21 | 9 | noise |
| RB Receiving yards | favourite 4+ | OVER | 20 | 13 | 0.45 | 1.837 | 0.544 | -0.171 | [-0.487, +0.162] | -0.074 | 8 | -0.236 | 12 | tiny |
| RB Receiving yards | favourite 4+ | UNDER | 20 | 13 | 0.55 | 1.831 | 0.546 | 0.008 | [-0.325, +0.324] | -0.084 | 8 | 0.069 | 12 | tiny |
| RB Rushing yards | underdog 4+ | OVER | 26 | 14 | 0.462 | 1.833 | 0.546 | -0.154 | [-0.431, +0.146] | 0.1 | 10 | -0.313 | 16 | tiny |
| RB Rushing yards | underdog 4+ | UNDER | 26 | 14 | 0.538 | 1.833 | 0.546 | -0.013 | [-0.313, +0.264] | -0.267 | 10 | 0.146 | 16 | tiny |
| RB Rushing yards | close | OVER | 42 | 13 | 0.476 | 1.832 | 0.546 | -0.128 | [-0.321, +0.082] | -0.149 | 28 | -0.086 | 14 | noise |
| RB Rushing yards | close | UNDER | 42 | 13 | 0.524 | 1.835 | 0.545 | -0.04 | [-0.250, +0.152] | -0.018 | 28 | -0.084 | 14 | noise |
| RB Rushing yards | favourite 4+ | OVER | 25 | 14 | 0.56 | 1.836 | 0.545 | 0.026 | [-0.340, +0.393] | 0.018 | 9 | 0.031 | 16 | tiny |
| RB Rushing yards | favourite 4+ | UNDER | 25 | 14 | 0.44 | 1.832 | 0.546 | -0.195 | [-0.560, +0.173] | -0.189 | 9 | -0.198 | 16 | tiny |
| TE Receiving receptions | underdog 4+ | OVER | 24 | 14 | 0.5 | 1.917 | 0.533 | -0.073 | [-0.414, +0.269] | 0.222 | 8 | -0.22 | 16 | tiny |
| TE Receiving receptions | underdog 4+ | UNDER | 24 | 14 | 0.5 | 1.811 | 0.566 | -0.129 | [-0.439, +0.192] | -0.25 | 8 | -0.068 | 16 | tiny |
| TE Receiving receptions | close | OVER | 36 | 13 | 0.5 | 1.884 | 0.543 | -0.044 | [-0.377, +0.299] | 0.005 | 24 | -0.142 | 12 | noise |
| TE Receiving receptions | close | UNDER | 36 | 13 | 0.5 | 1.842 | 0.554 | -0.078 | [-0.389, +0.242] | -0.094 | 24 | -0.047 | 12 | noise |
| TE Receiving receptions | favourite 4+ | OVER | 18 | 14 | 0.389 | 1.92 | 0.528 | -0.251 | [-0.619, +0.167] | -0.417 | 7 | -0.145 | 11 | tiny |
| TE Receiving receptions | favourite 4+ | UNDER | 18 | 14 | 0.611 | 1.759 | 0.574 | 0.082 | [-0.300, +0.411] | 0.232 | 7 | -0.014 | 11 | tiny |
| TE Receiving yards | underdog 4+ | OVER | 24 | 14 | 0.667 | 1.853 | 0.541 | 0.235 | [-0.035, +0.481] | 0.146 | 8 | 0.28 | 16 | tiny |
| TE Receiving yards | underdog 4+ | UNDER | 24 | 14 | 0.333 | 1.825 | 0.549 | -0.393 | [-0.633, -0.129] | -0.313 | 8 | -0.434 | 16 | tiny |
| TE Receiving yards | close | OVER | 35 | 13 | 0.6 | 1.833 | 0.546 | 0.1 | [-0.206, +0.399] | 0.116 | 23 | 0.069 | 12 | promising |
| TE Receiving yards | close | UNDER | 35 | 13 | 0.4 | 1.833 | 0.546 | -0.267 | [-0.566, +0.039] | -0.283 | 23 | -0.236 | 12 | noise |
| TE Receiving yards | favourite 4+ | OVER | 18 | 14 | 0.611 | 1.848 | 0.542 | 0.12 | [-0.325, +0.544] | -0.214 | 7 | 0.333 | 11 | tiny |
| TE Receiving yards | favourite 4+ | UNDER | 18 | 14 | 0.389 | 1.824 | 0.549 | -0.296 | [-0.719, +0.140] | 0.024 | 7 | -0.5 | 11 | tiny |
| WR Receiving receptions | underdog 4+ | OVER | 42 | 14 | 0.524 | 1.845 | 0.55 | -0.039 | [-0.286, +0.215] | -0.316 | 18 | 0.169 | 24 | noise |
| WR Receiving receptions | underdog 4+ | UNDER | 42 | 14 | 0.476 | 1.832 | 0.553 | -0.131 | [-0.364, +0.104] | 0.129 | 18 | -0.327 | 24 | noise |
| WR Receiving receptions | close | OVER | 62 | 13 | 0.435 | 1.921 | 0.529 | -0.181 | [-0.383, +0.025] | -0.262 | 38 | -0.054 | 24 | noise |
| WR Receiving receptions | close | UNDER | 62 | 13 | 0.565 | 1.783 | 0.57 | -0.007 | [-0.192, +0.170] | 0.092 | 38 | -0.164 | 24 | noise |
| WR Receiving receptions | favourite 4+ | OVER | 41 | 14 | 0.39 | 1.902 | 0.535 | -0.307 | [-0.500, -0.092] | -0.396 | 17 | -0.244 | 24 | LOSER |
| WR Receiving receptions | favourite 4+ | UNDER | 41 | 14 | 0.61 | 1.798 | 0.565 | 0.043 | [-0.156, +0.231] | 0.093 | 17 | 0.008 | 24 | promising |
| WR Receiving yards | underdog 4+ | OVER | 42 | 14 | 0.405 | 1.841 | 0.544 | -0.254 | [-0.455, -0.038] | -0.185 | 18 | -0.306 | 24 | LOSER |
| WR Receiving yards | underdog 4+ | UNDER | 42 | 14 | 0.595 | 1.828 | 0.547 | 0.089 | [-0.127, +0.291] | 0.018 | 18 | 0.141 | 24 | promising |
| WR Receiving yards | close | OVER | 62 | 13 | 0.435 | 1.836 | 0.545 | -0.199 | [-0.348, -0.033] | -0.276 | 38 | -0.077 | 24 | LOSER |
| WR Receiving yards | close | UNDER | 62 | 13 | 0.565 | 1.831 | 0.546 | 0.035 | [-0.129, +0.181] | 0.109 | 38 | -0.084 | 24 | noise |
| WR Receiving yards | favourite 4+ | OVER | 41 | 14 | 0.488 | 1.833 | 0.546 | -0.106 | [-0.318, +0.108] | -0.137 | 17 | -0.084 | 24 | noise |
| WR Receiving yards | favourite 4+ | UNDER | 41 | 14 | 0.512 | 1.833 | 0.546 | -0.061 | [-0.275, +0.151] | -0.03 | 17 | -0.084 | 24 | noise |

### Raw history: output minus own last-10 mean by script (starters with volume)

| pos | stat | script | n | y_minus_m10 |
|---|---|---|---|---|
| RB | rush_yds | underdog 4+ | 315 | -7.2 |
| RB | rush_yds | close | 1260 | -5.11 |
| RB | rush_yds | favourite 4+ | 354 | -1.44 |
| QB | pass_yds | underdog 4+ | 290 | -16.52 |
| QB | pass_yds | close | 1156 | -7.08 |
| QB | pass_yds | favourite 4+ | 356 | -8.72 |
| QB | rush_yds | underdog 4+ | 290 | -2.4 |
| QB | rush_yds | close | 1156 | -0.47 |
| QB | rush_yds | favourite 4+ | 356 | -2.1 |
| WR | rec_yds | underdog 4+ | 546 | -3.86 |
| WR | rec_yds | close | 2068 | -3.88 |
| WR | rec_yds | favourite 4+ | 586 | -2.53 |
| TE | rec_yds | underdog 4+ | 239 | -1.5 |
| TE | rec_yds | close | 889 | -2.87 |
| TE | rec_yds | favourite 4+ | 254 | -0.93 |

## 6d. Receiving: targets last-3 vs last-10 (volume trend) and the main line

| slice | n | games | hit | avg_p | be_hit | roi | ci90 | roi_H1 | n_H1 | roi_H2 | n_H2 | verdict | line-m10 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| targets trend down, under | 96 | 23 | 0.396 | 1.845 | 0.549 | -0.282 | [-0.459, -0.082] | -0.27 | 42 | -0.292 | 54 | LOSER | -1.93 |
| targets trend down, over | 96 | 23 | 0.604 | 1.86 | 0.544 | 0.108 | [-0.099, +0.298] | 0.108 | 42 | 0.108 | 54 | promising | -1.93 |
| targets trend flat, under | 295 | 27 | 0.505 | 1.811 | 0.556 | -0.089 | [-0.193, +0.021] | -0.052 | 155 | -0.13 | 140 | noise | -1.68 |
| targets trend flat, over | 295 | 27 | 0.495 | 1.872 | 0.539 | -0.076 | [-0.192, +0.031] | -0.111 | 155 | -0.038 | 140 | noise | -1.68 |
| targets trend up, under | 200 | 27 | 0.58 | 1.806 | 0.558 | 0.031 | [-0.078, +0.141] | 0.082 | 106 | -0.028 | 94 | noise | -0.29 |
| targets trend up, over | 200 | 27 | 0.42 | 1.88 | 0.537 | -0.229 | [-0.338, -0.117] | -0.284 | 106 | -0.167 | 94 | LOSER | -0.29 |

## 6e. QB rushing: raw-history under rate at Paddy-like lines

| line_rule | sub | n | under_rate | ci90 | breakeven_at_1_83 |
|---|---|---|---|---|---|
| line = mean10 - 2.8 | all starters | 1889 | 0.515 | [0.496, 0.534] | 0.546 |
| line = mean10 - 2.8 | 2.5+ rush att | 1335 | 0.554 | [0.531, 0.578] | 0.546 |
| line = mean10 - 2.8 | <2.5 rush att | 554 | 0.422 | [0.388, 0.456] | 0.546 |
| line = median10 - 0.7 | all starters | 1889 | 0.492 | [0.472, 0.511] | 0.546 |
| line = median10 - 0.7 | 2.5+ rush att | 1335 | 0.524 | [0.502, 0.548] | 0.546 |
| line = median10 - 0.7 | <2.5 rush att | 554 | 0.413 | [0.379, 0.447] | 0.546 |
| line = 0.5*(mean10+median10) - 1.5 | all starters | 1889 | 0.518 | [0.499, 0.537] | 0.546 |
| line = 0.5*(mean10+median10) - 1.5 | 2.5+ rush att | 1335 | 0.548 | [0.525, 0.572] | 0.546 |
| line = 0.5*(mean10+median10) - 1.5 | <2.5 rush att | 554 | 0.446 | [0.410, 0.480] | 0.546 |

Priced QB rushing unders (n=53): mean empirical under rate from each QB's own last 20 games at Paddy's line = 0.519; book implied 0.546; actual 0.679.

| slice | n | games | hit | avg_p | be_hit | roi | ci90 | roi_H1 | n_H1 | roi_H2 | n_H2 | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| own-history under rate >= 55% | 24 | 20 | 0.625 | 1.813 | 0.553 | 0.135 | [-0.179, +0.435] | -0.033 | 13 | 0.334 | 11 | tiny |
| own-history under rate < 55% | 28 | 22 | 0.714 | 1.852 | 0.541 | 0.313 | [+0.057, +0.557] | 0.274 | 13 | 0.347 | 15 | tiny |

## 6f. NFL check of the reversion rule (z = (line - last-10 mean)/sd10)

| slice | n | games | hit | avg_p | be_hit | roi | ci90 | roi_H1 | n_H1 | roi_H2 | n_H2 | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| NFL main under, z(m10) >= 0.25 | 231 | 27 | 0.55 | 1.782 | 0.564 | -0.029 | [-0.186, +0.123] | 0.006 | 116 | -0.064 | 115 | noise |
| NFL main under, z >= 0.5 | 118 | 26 | 0.551 | 1.763 | 0.571 | -0.043 | [-0.235, +0.143] | -0.009 | 60 | -0.078 | 58 | noise |
| NFL main over, z <= -0.25 | 282 | 27 | 0.496 | 1.829 | 0.55 | -0.098 | [-0.206, +0.012] | -0.031 | 147 | -0.17 | 135 | noise |
| NFL main over, z <= -0.5 | 110 | 25 | 0.536 | 1.815 | 0.555 | -0.04 | [-0.221, +0.144] | -0.029 | 58 | -0.051 | 52 | noise |
| NFL main under, |z| < 0.25 (control) | 400 | 27 | 0.51 | 1.819 | 0.553 | -0.076 | [-0.171, +0.028] | -0.057 | 200 | -0.095 | 200 | noise |

**Conclusions (direction 6).**
* Skew is real in raw history: QB rushing goes under its own 10-game mean 61% of the time, and RB/WR/TE yards about 60%. But Paddy already sets those lines below the mean (by 2-3 yds), and the pre-stated "line above median" under rule lost -9%.
* QB rushing unders: at Paddy-like lines raw history gives 49-55% under rates (2.5+ attempt QBs: 52-55%; low-rushing QBs: 41-45%), against a 54.6% break-even at 1.83. The QBs' own last-20 games give 52% at Paddy's actual lines. **Downgrade to "probably noise"**: if anything, restrict to QBs with 2.5+ rushes per game and expect about break-even.
* Game script (pre-game Elo margin): every priced cell is tiny. In raw history underdog QBs fall furthest below their passing mean (-16.5 vs -7 yds), but nothing is bettable at this n.
* Target trend: targets down over the last 3 → overs +10.8% / unders -28%; targets up → overs -22.9%. This is the same "Paddy follows recent volume" pattern as the NBA (n of about 100-300, 23-27 games). The plain NFL version of RULE U does not replicate (unders z >= 0.25: -2.9%, n=231).


# 7. What to change / what to bet / what to track

**Change**
1. `nba_alt_drift_miss`: keep it as a **tracked, small fixed-stake** rule. Do not scale it or advertise it as proven. Score it against the book's expected wins, not 100%.
   Raw history says misses by players on the bench today revert worst (63.8% vs 76.9%). But in the priced record all 7 bench-today bets **won** (7 of 7; starters 26 of 27). Applying that filter now would be fitting against the only priced evidence.
   Instead, **log the split** (starting today yes/no, why-category of the miss) and decide after 50+ more bets.
2. Downgrade the NFL QB rushing-under candidate to tracking only. If kept: main under, QB with >= 2.5 rush attempts per game over his last 10, price 1.70-2.00.
3. Stop treating "teammate out → bet the next scorer's over" as an angle; Paddy prices it fully.
4. Stop alt-ladder hunting: every rung distance loses about 4-70% and below-main rungs carry about 11% more margin than the main line.

**Track (code these as paper rules; evaluate at first price with game-clustered intervals; ~4-6 more weeks needed)**

* **RULE U, `nba_under_reversion`** (lead candidate): NBA main line, under side, first price 1.60-2.20, stat in {points, rebounds, assists, threes, PRA, P+R, P+A, R+A}. Compute
  `base = c0 + w3*m3 + w10*m10 + w20*m20` using these weights, fitted on raw history before 20 Oct 2026:
  points [0.77, 0.17, 0.26, 0.50]; rebounds [0.29, 0.15, 0.14, 0.64]; assists [0.16, 0.20, 0.19, 0.55]; threes [0.14, 0.12, 0.10, 0.67]; pra [1.05, 0.23, 0.27, 0.44]; pr [1.00, 0.20, 0.26, 0.48]; pa [0.81, 0.20, 0.29, 0.45]; ra [0.43, 0.21, 0.18, 0.54].
  m3, m10 and m20 are his played-game means; sd10 is the sd of his last 10. Bet if `(Paddy main line - base) / sd10 >= 0.25`. Use one bet per player-stat-game. Priced history: +5.0%, n=1,669, 88 games.
  A stricter variant, `nba_under_reversion_strong`, uses z >= 0.75 against the m20 baseline: +13.3%, n=357, 66 games, CI -0.7% to +26.8%.
* **`nba_under_promoted`**: same as RULE U but restricted to players starting today with start_rate < 0.5 over the last 10. This can only be bet after line-ups, at the last price. History +14.6% at first price (n=351); check at the last price.
* **`nba_minutes_trend_under`**: main under, 1.60-2.20, mins_m3 / mins_m10 >= 1.05. History +5.9% (1.05-1.15) and +0.5% (>1.15). Mostly overlaps RULE U, so track it as a diagnostic, not a separate stake.
* **`nba_blend_value`**: p = logistic(0.002 + 0.27*logit(model) + 0.74*logit(Paddy devigged fair)), where the model is the no-line-up LightGBM + NB from `d9_proj.py`. Bet a main line when p*price >= 1.03. H2 out-of-sample +11.8% (n=236). Refit the blend weights each week on settled data only.
* **`nfl_targets_down_over`**: NFL receiving yards / receptions main over when targets_m3 / targets_m10 <= 0.8. History +10.8% (n=96, 23 games). Tiny; track it.

**Bet now:** nothing at more than a small stake. RULE U is the only candidate supported by both history (the structural over-weighting of recent games) and the price log (monotone gradient, both halves, all variants positive). Its interval still includes zero.

**Track as data (to make the next stage stronger)**
* Log Paddy's main line and price at a fixed time (e.g. T-90 min) as well as first/last, so that line-up-dependent rules can be scored honestly.
* Keep the per-player m3/m10/m20 and the RULE U z in pplog at logging time, so the rule is scored live without recomputation.
* Log whether the player is in the confirmed starting five at the time of each price snapshot.
