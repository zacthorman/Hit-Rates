# Super Sub calibration check

Does Paddy Power's Super Sub chance from `supersub.py` (bookie-imports), computed on top of the recalibrated to-score chance from scorer-audit (rule-review), stay calibrated against Super Sub settlement? Written 23 October 2026 on the `supersub-check` branch, which holds only the analysis. Live code is not touched.

    python -B scorer_audit.py build                       # in a checkout with rule-review and bookie-imports merged, cache/ unpacked
    python -B supersub_check.py --code CHECKOUT --cache CACHE --audit CHECKOUT/cache/scorer_audit.pkl --rows ROWS.json
    python -B supersub_check.py --from-rows ROWS.json      # the same tables again, in seconds

The second command prints every table below. It takes about seven minutes.

## Verdict

**The Super Sub chance is calibrated, and no live fix is warranted.**

1. **On 21,119 starters where Super Sub adds to the chance (1 July to 19 October 2026), the Super Sub chance said 13.1% and 13.5% was settled as Super Sub wins.** That is landed/said 1.03 (1.00 to 1.06 by night). Without the uplift, the own chance scores worse against the same settlement: log loss 0.3477 against 0.3457, a difference of −0.0020 (−0.0029 to −0.0010). The uplift is worth having.
2. **By position.** Forwards 1.05 (1.01 to 1.09), midfielders 1.03 (0.98 to 1.07), defenders 1.02 (0.94 to 1.12). The uplift improves log loss for forwards and midfielders, with intervals clear of zero, and makes no difference for defenders. Goalkeepers have no uplift and score almost never.
3. **By fair price.** Every price band lies between 0.98 and 1.08 landed/said, and every interval includes 1. The calibration table runs within a point or two of said up to 50%. The 89 starters above 50% landed 65.2% against 53.2% said, which is the shortest-priced forwards, slightly cautious.
4. **The uplift on its own runs low, but too little to matter.** Among starters who did not score, the replacement won the bet 2.12% of the time against 1.86% said: 1.14 (1.04 to 1.23). It is most understated for players whose record says they are rarely taken off: 1.92 (1.35 to 2.53) where s is under 20%. Two things cause it.
   - **s is not conditional.** The formula multiplies (1 − own) by s, his share of starts ending before 85 minutes. But a starter who has not scored is more likely to be taken off than one who has: forwards who did not score went off 61.8% of the time against an s of 57.9%.
   - **Thin records.** With as few as five starts, s often reads 0 for a player who is in fact sometimes taken off.

   The uplift is a small part of the chance, though (about 1.6 points on average), so this barely moves the total.
5. **A fix was tried and does nothing.** It had two parts, fitted on July and August and scored on September and October: shrink s towards the position's rate (k = 5 pseudo-starts), and scale the uplift (c = 1.1). Log loss changes by +0.00002 (−0.00010 to +0.00014) overall and by less than 0.0002 for every position. The page should keep `supersub.chance` as it is.

## How many Paddy Power lines would cross the 5% avoid edge

**Almost none, because of how the verdict is ordered.** #13 (rule-review) marks a Paddy Power player line avoid when the price beats our chance by 5% or more. But `report.py verdictOf` returns "long shot" for any chance under 50% before it looks at that edge. Super Sub raises the to-score chance by about 1.6 points on average, and only 89 of the 21,119 starters it applies to reached 50% with it (62 did without it). So the +5% avoid can only ever catch a handful of to-score lines.

**There are no Paddy Power goalscorer prices to replay.** `pplog/` is gitignored and not in the repository, `pp-results.html` holds one settled to-score line (Nicolò Tresoldi, 2.10, ours 54%, edge +13%, lost), and `market_prices.json` carries no goalscorer markets. So the count is a scenario. Assume Paddy Power prices off the starter's own chance with a margin m, price = 1 / (own (1 + m)), and give each line `verdictOf`'s verdict on its own chance and on its Super Sub chance (section 7 below). Over the fourteen weeks:

| Paddy Power margin | Into the +5% avoid because of Super Sub | Out of the −5% avoid because of Super Sub |
|---:|---:|---:|
| 0% | 16 (13 from long shot, 3 from acceptable) | 0 |
| 5% | 0 | 0 |
| 10% | 0 | 17,337 (17,316 to long shot, 21 to acceptable) |
| 15% | 0 | 13,256 |
| 20% | 0 | 9,898 |
| 30% | 0 | 5,434 |

At any margin a bookmaker actually charges, Super Sub never creates a +5% avoid. What it does is the opposite. A price about 9% short of the own chance is marked avoid as a bad price, and the uplift lifts most of those above −5%, where a sub-50% line reads "long shot". That is the right direction, because the Super Sub chance is the calibrated one (points 1 to 3 above).

For the 89 starters at 50% or more, the Super Sub chance was if anything cautious: they landed 65.2% against 53.2% said. A +5% edge on such a line is not a sign of the Super Sub chance being too high. 89 is too few to act on.

**No live fix is warranted.** The chance is calibrated, the fix in point 5 does nothing out of sample, and #13's rule barely interacts with Super Sub. One note for whoever next reads `pplog/`: the logged `chance` on a Paddy Power to-score snapshot includes Super Sub, and `supersub` holds the uplift. Any re-run of `rule_review.py` on those lines should score them against Super Sub settlement (`supersub.settle_row`), not the player's own goals, or the record will understate them again.

## Method

**The to-score chance.** For a starter, the recalibrated chance is fmodel's. Scorer-audit set tonight.html's weight on fmodel to 1.0 for to score, and `pplog.snapshot` uses fmodel wherever fmodel has a chance. `scorer_audit.py build` replays every starter in the cache through the live feature code with only what was known before kick-off. Run on the merged checkout here, it reproduces scorer-audit's own figures: 25,280 starters from 1 July, fmodel said 10.36%, 10.39% scored. This check uses the 25,269 of them whose line-up row has minutes. Starters fmodel does not cover (fewer than three appearances), whose live chance comes from scoreCase, are not in the replay and are not scored here.

**The Super Sub chance** is `supersub.chance(own, s, rep)`, as `supersub.uplift` computes it:

- **s** is his share of starts ending before 85 minutes, over his last 38 appearances before the match (`supersub.sub_rate`, five starts or more), and his position is the most common one in those appearances (`supersub.position_of`). The live code reads the player's records in his team's last 38 games; here it is his last 38 appearances, which is the same for nearly everyone.
- **rep** is the chance a replacement for his position scores after he goes off without scoring. It is refitted before each month on earlier matches only, with supersub.fit's own pairing. The shipped `supersub_fit.json` is fitted on the whole cache, the test months included. It gives the same figures to the third decimal, and section 1 scores it as well.

Without five earlier starts, or for goalkeepers (rep 0), the chance is the own chance, as live.

**Settlement.** A Super Sub bet wins if he scored, or if he started, went off before 85 minutes and his replacement scored. The cache keeps line-ups but not substitution incidents, so the replacement is found as `supersub.fit` finds him: the first starter off is paired with the substitute who played longest. With a double change, the time pairing credits a goal to one of the two starters. That is right on average and noisy for each one. As a bound, a looser settlement credits a goal by any substitute who came on within three minutes of his exit. That double-counts double changes, and it lands at 1.15 of said (1.12 to 1.19). The truth is close to the first figure and below the second. Live settlement (`supersub.settle_row`) uses the real incidents.

**Intervals.** Rates carry a Wilson 95% interval. Ratios and log-loss differences carry a bootstrap 95% interval that resamples whole nights (2,000 draws, seed 20261023), because one night's starters share fixtures, weather and refereeing.

## Limits

- **Real line-ups.** The cache holds the real XI. The live page prices the predicted XI, and a player who does not start voids the bet at Paddy Power, so this measures the chance conditional on starting, which is the right one.
- **Pairing.** The replacement pairing is approximate (above); the looser settlement bounds how far off it could be.
- **Paddy Power prices.** There are none to replay, so the verdict counts are a scenario, not a count of real lines. In particular, Paddy Power presumably prices Super Sub into its own odds, so its real margin over the own chance is unknown.
- **The window.** Fourteen weeks, one season. fmodel is out of sample only from July.

## Files

- `supersub_check.py`: the replay and the report. It reads the cache, the scorer-audit replay and supersub.py from the checkout given, and writes nothing unless `--rows` is passed (`--from-rows` reports from that file).
- `tests/test_supersub_check.py`: 14 tests on synthetic line-ups. One of them checks the stand-in against the real `supersub.py` when `SUPERSUB_CODE` points at a checkout that has it, and is skipped otherwise.

## Every table

Generated 2026-10-23 18:30 UTC by `supersub_check.py`. Intervals resample whole nights, 2000 draws, seed 20261023.

25,269 starters with an fmodel to-score chance, 1,332 matches, 100 nights, 2026-07-01 to 2026-10-19. 21,119 of them had five or more earlier starts and an outfield position, so Super Sub adds to their chance; the rest are priced on their own chance, as supersub.uplift does.

### 1. The chance against Super Sub settlement

| set | starters | nights | landed (Super Sub) | 95% Wilson | said, Super Sub | landed / said (95% by night) | log loss, Super Sub | log loss, own chance only | Super Sub minus own (95% by night) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| every starter | 25,269 | 100 | 12.1% | 11.7% to 12.5% | 11.7% | 1.03 (1.00 to 1.06) | 0.3118 | 0.3135 | -0.0017 (-0.0024 to -0.0009) |
| where Super Sub adds | 21,119 | 100 | 13.5% | 13.1% to 14.0% | 13.1% | 1.03 (1.00 to 1.06) | 0.3457 | 0.3477 | -0.0020 (-0.0029 to -0.0010) |
| where Super Sub adds, shipped supersub_fit.json | 21,119 | 100 | 13.5% | 13.1% to 14.0% | 13.1% | 1.03 (1.00 to 1.06) | 0.3457 | 0.3477 | -0.0020 (-0.0029 to -0.0010) |
| where Super Sub adds, looser settlement | 21,119 | 100 | 15.1% | 14.7% to 15.6% | 13.1% | 1.15 (1.12 to 1.19) | 0.3765 | 0.3822 | -0.0056 (-0.0067 to -0.0045) |

For reference, the own chance against the player's own goals on the same rows: said 11.5%, scored 11.7%, landed / said 1.02 (0.98 to 1.05).

### 2. By position

| set | starters | nights | landed (Super Sub) | 95% Wilson | said, Super Sub | landed / said (95% by night) | log loss, Super Sub | log loss, own chance only | Super Sub minus own (95% by night) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| forwards | 4,433 | 100 | 29.8% | 28.4% to 31.1% | 28.4% | 1.05 (1.01 to 1.09) | 0.5820 | 0.5866 | -0.0046 (-0.0069 to -0.0024) |
| midfielders | 9,529 | 100 | 13.5% | 12.8% to 14.2% | 13.1% | 1.03 (0.98 to 1.07) | 0.3682 | 0.3701 | -0.0019 (-0.0034 to -0.0004) |
| defenders | 8,971 | 100 | 5.1% | 4.7% to 5.6% | 5.0% | 1.02 (0.94 to 1.12) | 0.1990 | 0.1993 | -0.0004 (-0.0009 to +0.0001) |
| goalkeepers | 2,336 | 100 | 0.0% | -0.0% to 0.2% | 0.3% | 0.00 (0.00 to 0.00) | 0.0029 | 0.0029 | +0.0000 (+0.0000 to +0.0000) |

### 3. By fair price (one over the Super Sub chance)

| set | starters | nights | landed (Super Sub) | 95% Wilson | said, Super Sub | landed / said (95% by night) | log loss, Super Sub | log loss, own chance only | Super Sub minus own (95% by night) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 to 2.5 | 608 | 88 | 49.0% | 45.1% to 53.0% | 45.3% | 1.08 (0.99 to 1.18) | 0.6826 | 0.6844 | -0.0018 (-0.0063 to +0.0027) |
| 2.5 to 4 | 2,694 | 99 | 32.1% | 30.4% to 33.9% | 31.1% | 1.03 (0.99 to 1.08) | 0.6242 | 0.6295 | -0.0053 (-0.0081 to -0.0026) |
| 4 to 7 | 3,974 | 100 | 20.2% | 19.0% to 21.5% | 19.4% | 1.04 (0.98 to 1.10) | 0.5008 | 0.5053 | -0.0045 (-0.0074 to -0.0015) |
| 7 to 12 | 3,225 | 100 | 11.1% | 10.1% to 12.2% | 10.9% | 1.02 (0.92 to 1.12) | 0.3467 | 0.3485 | -0.0018 (-0.0046 to +0.0009) |
| 12 to 25 | 7,540 | 99 | 5.6% | 5.1% to 6.2% | 5.8% | 0.98 (0.89 to 1.06) | 0.2149 | 0.2152 | -0.0002 (-0.0014 to +0.0009) |
| 25+ | 3,078 | 96 | 3.6% | 3.0% to 4.3% | 3.4% | 1.06 (0.88 to 1.26) | 0.1545 | 0.1549 | -0.0003 (-0.0012 to +0.0005) |

Forwards and midfielders by price:

| set | starters | nights | landed (Super Sub) | 95% Wilson | said, Super Sub | landed / said (95% by night) | log loss, Super Sub | log loss, own chance only | Super Sub minus own (95% by night) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| F, 1 to 2.5 | 571 | 87 | 48.7% | 44.6% to 52.8% | 45.3% | 1.07 (0.97 to 1.18) | 0.6824 | 0.6840 | -0.0016 (-0.0065 to +0.0034) |
| F, 2.5 to 4 | 1,989 | 97 | 33.6% | 31.6% to 35.7% | 31.6% | 1.06 (1.01 to 1.12) | 0.6372 | 0.6444 | -0.0073 (-0.0109 to -0.0038) |
| F, 4 to 7 | 1,342 | 95 | 19.2% | 17.1% to 21.3% | 20.4% | 0.94 (0.84 to 1.03) | 0.4867 | 0.4893 | -0.0025 (-0.0087 to +0.0038) |
| F, 7 to 12 | 84 | 48 | 16.7% | 10.2% to 26.1% | 12.4% | 1.35 (0.76 to 2.04) | 0.4533 | 0.4750 | -0.0217 (-0.0617 to +0.0128) |
| M, 2.5 to 4 | 703 | 88 | 28.0% | 24.8% to 31.5% | 29.5% | 0.95 (0.87 to 1.03) | 0.5883 | 0.5880 | +0.0003 (-0.0024 to +0.0033) |
| M, 4 to 7 | 2,570 | 100 | 20.9% | 19.3% to 22.5% | 18.9% | 1.11 (1.02 to 1.20) | 0.5099 | 0.5154 | -0.0056 (-0.0087 to -0.0027) |
| M, 7 to 12 | 2,620 | 99 | 11.0% | 9.9% to 12.2% | 11.0% | 1.00 (0.91 to 1.09) | 0.3442 | 0.3457 | -0.0015 (-0.0048 to +0.0015) |
| M, 12 to 25 | 2,799 | 96 | 5.8% | 4.9% to 6.7% | 6.4% | 0.89 (0.77 to 1.02) | 0.2188 | 0.2189 | -0.0001 (-0.0027 to +0.0024) |
| M, 25+ | 65 | 36 | 0.0% | 0.0% to 5.6% | 3.6% | 0.00 (0.00 to 0.00) | 0.0370 | 0.0322 | +0.0049 (+0.0039 to +0.0059) |

### 4. Calibration of the Super Sub chance

| chance | starters | said | landed | 95% Wilson |
|---|---:|---:|---:|---:|
| 0% to 5% | 5,549 | 3.9% | 3.8% | 3.3% to 4.3% |
| 5% to 10% | 6,316 | 6.9% | 7.2% | 6.5% to 7.8% |
| 10% to 15% | 2,258 | 12.3% | 12.3% | 11.0% to 13.7% |
| 15% to 20% | 1,993 | 17.5% | 18.1% | 16.5% to 19.9% |
| 20% to 30% | 2,943 | 24.5% | 25.3% | 23.7% to 26.9% |
| 30% to 40% | 1,452 | 34.2% | 35.7% | 33.3% to 38.2% |
| 40% to 50% | 519 | 43.9% | 46.2% | 42.0% to 50.5% |
| 50% to 100% | 89 | 53.2% | 65.2% | 54.8% to 74.3% |

### 5. The uplift on its own

Starters who did not score, where Super Sub applied: the predicted s x rep (the chance the bet is won by his replacement) against how often it was.

| set | starters | said | paid | landed / said (95% by night) | paid, looser settlement |
|---|---:|---:|---:|---:|---:|
| all | 18,653 | 1.86% | 2.12% | 1.14 (1.04 to 1.23) | 3.93% |
| forwards | 2,927 | 4.65% | 5.19% | 1.12 (0.96 to 1.28) | 7.96% |
| midfielders | 7,786 | 2.23% | 2.49% | 1.12 (0.97 to 1.26) | 4.80% |
| defenders | 7,940 | 0.47% | 0.62% | 1.30 (0.96 to 1.68) | 1.59% |
| taken off 0% to 20% of starts | 6,259 | 0.32% | 0.61% | 1.92 (1.35 to 2.53) | 1.33% |
| taken off 20% to 40% of starts | 5,086 | 1.23% | 1.63% | 1.32 (1.05 to 1.62) | 3.28% |
| taken off 40% to 60% of starts | 3,506 | 2.56% | 2.65% | 1.04 (0.85 to 1.21) | 4.99% |
| taken off 60% to 80% of starts | 2,453 | 4.08% | 4.00% | 0.98 (0.79 to 1.16) | 7.34% |
| taken off 80% to 100% of starts | 1,349 | 5.57% | 6.15% | 1.10 (0.87 to 1.35) | 9.49% |

And how often he went off when he did not score, against the record's s:

| set | starters | s said | went off |
|---|---:|---:|---:|
| F | 2,927 | 57.9% | 61.8% |
| M | 7,786 | 43.2% | 46.9% |
| D | 7,940 | 19.7% | 21.3% |

### 6. A fix to the uplift, fitted on July and August, scored on September and October

s shrunk towards the position's own rate (D 17.6%, F 50.1%, M 39.0%) by k pseudo-starts, and the uplift multiplied by c. Fitted on 8,513 starters: k = 5, c = 1.1.

| set | starters | landed | said, as shipped | said, fixed | landed / said, shipped | landed / said, fixed | log loss shipped | log loss fixed | fixed minus shipped (95% by night) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| all | 12,606 | 13.5% | 13.1% | 13.2% | 1.03 (0.99 to 1.07) | 1.02 (0.99 to 1.07) | 0.34364 | 0.34366 | +0.00002 (-0.00010 to +0.00014) |
| F | 2,381 | 30.3% | 29.4% | 29.5% | 1.03 (0.98 to 1.08) | 1.03 (0.98 to 1.07) | 0.58793 | 0.58804 | +0.00011 (-0.00017 to +0.00043) |
| M | 5,264 | 13.8% | 13.3% | 13.4% | 1.04 (0.97 to 1.11) | 1.03 (0.96 to 1.11) | 0.37266 | 0.37267 | +0.00001 (-0.00023 to +0.00025) |
| D | 4,961 | 5.1% | 5.1% | 5.1% | 1.01 (0.89 to 1.13) | 1.00 (0.89 to 1.13) | 0.19561 | 0.19559 | -0.00001 (-0.00011 to +0.00009) |

The uplift alone on the same months, starters who did not score: said 1.88% as shipped, 1.98% fixed, paid 2.14%.


### 7. How Super Sub moves the Paddy Power verdict

report.py verdictOf (#13) on each line, before and after the uplift. No Paddy Power goalscorer prices are held to replay, so the price is a scenario: Paddy Power priced off the starter's own chance with margin m. verdictOf calls anything under 50% a long shot before it looks at a +5% edge, so only lines at 50% or more can become avoid that way.

| margin m | starters | long to acceptable | long to avoid (edge 5%+) | acceptable to avoid (edge 5%+) | avoid (price 5% worse) to long | avoid (price 5% worse) to acceptable | unchanged |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0% | 21,119 | 14 | 13 | 3 | 0 | 0 | 21,089 |
| 5% | 21,119 | 27 | 0 | 0 | 0 | 0 | 21,092 |
| 10% | 21,119 | 0 | 0 | 0 | 17,316 | 21 | 3,782 |
| 15% | 21,119 | 0 | 0 | 0 | 13,256 | 0 | 7,863 |
| 20% | 21,119 | 0 | 0 | 0 | 9,898 | 0 | 11,221 |
| 30% | 21,119 | 0 | 0 | 0 | 5,434 | 0 | 15,685 |

89 starters had a Super Sub chance of 50% or more, 62 an own chance of 50% or more; they landed 65.2% against 53.2% said.
